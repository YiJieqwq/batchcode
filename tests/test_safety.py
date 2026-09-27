import contextlib
import copy
import fcntl
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import common as c
import configuration as conf
import storage as st
import tools
import doctor
import context as cx
from network import Assembler
import subprocess

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)/'project';self.root.mkdir()
        self.p=patch.object(c,'ROOT',self.root);self.p.start();self.p2=patch.object(tools,'ROOT',self.root);self.p2.start();c.init()
        (self.root/'input').mkdir();self.cfg=copy.deepcopy(conf.DEFAULTS);self.cfg.update(read_roots=['input','sub_workspace'],max_read_bytes=17,max_tool_result_chars=400)
        self.sid=st.add('one',{});self.tool=tools.Tools(self.cfg,None,None,self.sid)
    def tearDown(self):self.p2.stop();self.p.stop();self.t.cleanup()
    def test_write_traversal(self):
        for name in ['../x','/tmp/x','a/../../x','a//b','a\\b','./x']:
            with self.subTest(name=name),self.assertRaises(c.Failure):tools.sandbox_write(name,'x',100,self.sid)
    def test_symlinked_write_parent(self):
        outside=self.root.parent/'out';outside.mkdir();(self.root/'sub_workspace'/self.sid).symlink_to(outside)
        with self.assertRaises(OSError):tools.sandbox_write('x','BAD',100,self.sid)
        self.assertEqual(list(outside.iterdir()),[])
    def test_hardlink_replacement(self):
        d=self.root/'sub_workspace'/self.sid;d.mkdir();outside=self.root.parent/'keep';outside.write_text('KEEP');(d/'report').hardlink_to(outside)
        tools.sandbox_write('report','NEW',100,self.sid);self.assertEqual(outside.read_text(),'KEEP')
    def test_model_secret_deny_even_widened_root(self):
        self.cfg['read_roots']=[str(self.root)];t=tools.Tools(self.cfg,None,None,self.sid)
        for folder in ['model','websearch','session','startup','state','src']:
            with self.subTest(folder=folder),self.assertRaises(c.Failure):t.execute('read_file',{'path':str(self.root/folder/'x.txt')})
    def test_symlink_read_deny(self):
        p=self.root/'model/key.txt';p.write_text('secret');(self.root/'input/link').symlink_to(p)
        with self.assertRaises(c.Failure):self.tool.execute('read_file',{'path':'input/link'})
    def test_fifo_rejected_without_block(self):
        os.mkfifo(self.root/'input/pipe')
        with self.assertRaises(c.Failure):self.tool.execute('read_file',{'path':'input/pipe'})
    def test_utf8_pages_no_split(self):
        text='中文😀\n'*40;(self.root/'input/x').write_text(text);parts=[];offset=0
        for _ in range(100):
            o=self.tool.execute('read_file',{'path':'input/x','offset':offset});parts.append(o['content']);self.assertGreater(o['next_offset'],offset);offset=o['next_offset']
            if not o['truncated']:break
        self.assertEqual(''.join(parts),text)
    def test_raw_strings_unchanged_on_write(self):
        self.tool.execute('write_file',{'path':'x','content':'sk-example tvly-example'})
        self.assertEqual((self.root/'sub_workspace'/self.sid/'x').read_text(),'sk-example tvly-example')
    def test_public_urls_rejected(self):
        for url in ['file:///etc/passwd','http://127.0.0.1','http://[::1]','https://a:b@example.com','http://10.0.0.1','https://example.com:555']:
            with self.subTest(url=url),self.assertRaises(c.Failure):tools.public_url(url)
    def test_no_unavailable_tool_execution(self):
        with self.assertRaises(c.Failure):self.tool.execute('web_search',{'query':'x'})
    def test_lock_by_id(self):
        with st.session_locked(self.sid):
            with self.assertRaises(c.Failure):
                with st.session_locked(self.sid):pass
    def test_reserve_counter_no_reuse(self):
        s=st.Session(self.sid);i=s.alloc('evt');s=st.Session(self.sid);self.assertGreater(s.alloc('evt'),i)
    def test_new_id_after_del(self):
        with st.session_locked(self.sid):st.delete_all(self.sid)
        new=st.add('one',{});self.assertNotEqual(new,self.sid)
    def test_idx_redo_partial_create(self):
        with st.index_locked() as idx:
            sid=st.new_id();idx['names']['two']=sid;p=st.spath(sid);p.mkdir();c.atomic(p/'info.json',st.blank_info(sid))
            c.atomic(c.ROOT/'state/index-transaction.json',{'op':'create','index':idx,'entries':[{'id':sid,'info':st.blank_info(sid),'conf':{},'ctx':cx.empty()}]})
        self.assertEqual(st.resolve('two')[0],sid);s=st.Session(sid);self.assertEqual(s.ctx,cx.empty())
    def test_idx_recovery_does_not_reuse_artifact(self):
        p=self.root/'sub_workspace'/'s_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';p.mkdir()
        with st.index_locked() as idx:self.assertNotIn(p.name,idx['names'].values())
    def test_doctor_timeout(self):
        with patch('doctor.subprocess.run',side_effect=subprocess.TimeoutExpired('cmd',1)):
            self.assertEqual(doctor.probe('x',1)['status'],'timeout')
    def test_doctor_summary(self):
        self.assertEqual(doctor.summarize([{'status':'ok','elapsed':.05}])['status'],'ok')
        self.assertEqual(doctor.summarize([{'status':'ok','elapsed':5.0}])['status'],'warning')
    def test_parameters_zero_null_nan(self):
        conf.validate({'temperature':0,'top_p':None,'max_model_calls':0},True)
        for value in [True,float('nan'),-1,3]:
            with self.assertRaises(c.Failure):conf.validate({'temperature':value})
    def test_canonical_json_duplicate_keys(self):
        with self.assertRaises(ValueError):c.decode('{"a":1,"a":2}')
    def test_gconf_scope_modelconf(self):
        with self.assertRaises(c.Failure):conf.validate({'modelconf':'x'})
        conf.validate({'modelconf':'x'},True)
    def test_partial_call_never_complete_on_parseable_prefix(self):
        s=st.Session(self.sid);a=Assembler(s)
        a.feed({'tool_calls':[{'index':0,'id':'c','function':{'name':'write_file','arguments':'{}'}}]});a.abort()
        s=st.Session(self.sid);self.assertEqual(s.ctx['events'],[])
    def test_frozen_cfg_copy(self):
        p=conf.profile_path('ds');c.atomic(p,{**self.cfg,'api_key':'key'});c.atomic(self.root/'startup/selection.json',{'default_modelconf':'ds','default_websearch':None})
        cfg=conf.resolve({},c.Diagnostics());c.atomic(p,{**self.cfg,'api_key':'changed','temperature':.1})
        self.assertEqual(cfg['api_key'],'key');self.assertEqual(cfg['temperature'],1)
    def test_config_view_masks_only_config_keys(self):
        view=conf.safe_view({'api_key':'secret','model':'sk-example'})
        self.assertEqual(view['api_key'],'[SET]');self.assertEqual(view['model'],'sk-example')
    def test_diagnostic_dedup(self):
        d=c.Diagnostics()
        for _ in range(10):d.warning('EMPTY_MSG','ignored',msg_id=1)
        self.assertEqual(len(d.items),1)
