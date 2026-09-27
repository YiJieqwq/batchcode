from http.server import ThreadingHTTPServer
import contextlib
import copy
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS
from mock_server import Handler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import common as c
import context as cx
import configuration as conf
import storage as st
from network import Assembler
import tools
import doctor

class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='batchcode-v3-test-');self.root=Path(self.tmp.name)/'app'
        shutil.copytree(ROOT,self.root,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','dist','session','sessions','state','logs','locks','running','sub_workspace','session_index.json'))
        (self.root/'input').mkdir();(self.root/'input/doc.md').write_text('source 文档')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.root=self.root;self.server.requests=[]
        threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.02),daemon=True).start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        self.cfg=copy.deepcopy(conf.DEFAULTS);self.cfg.update(provider='deepseek',url=self.url+'/chat',api_key='mock-key',allow_http_endpoints=True,read_roots=['./input','./sub_workspace'],http_retries=0,task_timeout_seconds=10)
        self.savecfg()
        (self.root/'websearch/tavily.txt').write_text(json.dumps({'url':self.url+'/search','extract_url':self.url+'/extract','api_key':'mock-search'}))
        (self.root/'startup/selection.json').write_text(json.dumps({'default_modelconf':'deepseek-flash','default_websearch':'tavily'}))
    def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def savecfg(self):(self.root/'model/deepseek-flash.txt').write_text(json.dumps(self.cfg))
    def cli(self,*args,stdin=None):
        return subprocess.run([sys.executable,str(self.root/'src/cli.py'),*args],input=stdin,capture_output=True,text=True,timeout=25,cwd='/tmp')
    def sid(self,name):return json.loads((self.root/'session_index.json').read_text())['names'][name]
    def file(self,name,filename):return self.root/'session'/self.sid(name)/filename
    def ctx(self,name):return json.loads(self.file(name,'ctx.json').read_text())
    def info(self,name):return json.loads(self.file(name,'info.json').read_text())
    def test_01_summary_stream(self):
        r=self.cli('task','--name=one','--content=readwrite','--granularity=fine');self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('FINAL_SUBMISSION',r.stdout);self.assertNotIn('GOODBYE',r.stdout);self.assertNotIn('VISIBLE_PROGRESS',r.stdout)
        self.assertNotIn('PRIVATE_REASONING',r.stdout+r.stderr);self.assertNotIn('FINAL_SUBMISSION',r.stderr)
        self.assertTrue((self.root/'sub_workspace'/self.sid('one')/'report.md').exists())
        self.assertIn('GOODBYE',self.file('one','ctx.json').read_text())
        self.assertTrue(r.stderr.startswith('[critical 0, warning 0]'))
    def test_02_full_nonstream(self):
        r=self.cli('task','--name=one','--stream=false','--answer=full','--content=readwrite')
        self.assertEqual(r.returncode,0,r.stderr)
        for text in ['VISIBLE_PROGRESS','UPPER_HALF','LOWER_HALF','GOODBYE']:self.assertIn(text,r.stdout)
        self.assertIn('Tool call records are hidden',r.stderr)
        self.assertIn('one/answer: FINAL_SUBMISSION',r.stdout)
        self.assertLess(r.stdout.index('GOODBYE'),r.stdout.index('one/answer:'))
    def test_03_revisions_not_truncated(self):
        r=self.cli('task','--name=one','--content=revise')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('长'*800,r.stdout);self.assertNotIn('FIRST',r.stdout)
        run=json.loads(next((self.file('one','runs')).glob('*.json')).read_text());self.assertEqual(run['submits'],2)
    def test_04_invalid_revision_keeps_valid(self):
        r=self.cli('task','--name=one','--content=invalid_submit');self.assertEqual(r.returncode,0,r.stderr);self.assertIn('VALID',r.stdout);self.assertIn('TOOL_FAILED',r.stderr)
    def test_05_history_submit_not_counted(self):
        self.cli('task','--name=one','--content=readwrite');r=self.cli('task','one','--content=hello')
        self.assertIn('submitted=false',r.stdout);self.assertNotIn('FINAL_SUBMISSION',r.stdout);self.assertIn('NO_SUBMISSION',r.stderr);self.assertIn('evt_start=',r.stderr)
    def test_06_fail_after_submission(self):
        r=self.cli('task','--name=one','--content=failafter');self.assertNotEqual(r.returncode,0);self.assertIn('BEFORE_ERROR',r.stdout);self.assertIn('status: failed',r.stdout)
        self.assertIn('API_HTTP_ERROR',r.stderr)
    def test_07_fallback(self):
        r=self.cli('task','--name=one','--content=hello');self.assertEqual(r.returncode,0,r.stderr);self.assertIn('Hello',r.stdout);self.assertIn('NO_SUBMISSION',r.stderr)
    def test_08_keys_raw_body_preserved(self):
        r=self.cli('task','--name=one','--content=secret');self.assertIn('sk-example tvly-example',r.stdout);self.assertIn('sk-example',self.file('one','ctx.json').read_text())
    def test_09_task_overrides_persist(self):
        r=self.cli('task','--name=one','--temperature=0','--task-timeout-seconds=12','--content=hello');self.assertEqual(r.returncode,0,r.stderr)
        obj=json.loads(self.file('one','config.json').read_text());self.assertEqual(obj['temperature'],0);self.assertEqual(obj['task_timeout_seconds'],12);self.assertNotIn('read_roots',obj)
        self.cli('task','one','--content=hello');self.assertEqual(self.server.requests[-1][1]['temperature'],0)
    def test_10_zero_token_caps_omitted(self):
        self.cfg['extra_body']={'max_tokens':3,'max_completion_tokens':4};self.savecfg()
        r=self.cli('task','--name=one','--content=hello');self.assertEqual(r.returncode,0,r.stderr)
        body=self.server.requests[-1][1];self.assertNotIn('max_tokens',body);self.assertNotIn('max_completion_tokens',body)
    def test_11_base_empty_key_session_supplies(self):
        self.cfg['api_key']='';self.savecfg()
        r=self.cli('task','--name=one','--api-key=override-key','--content=hello');self.assertEqual(r.returncode,0,r.stderr);self.assertIn('GLOBAL_KEY_EMPTY',r.stderr);self.assertNotIn('override-key',r.stdout+r.stderr)
    def test_12_no_routing(self):
        self.cfg['api_key']='';self.savecfg();other={**self.cfg,'api_key':'other'};(self.root/'model/other.txt').write_text(json.dumps(other))
        r=self.cli('task','--name=one','--content=hello');self.assertEqual(r.returncode,2);self.assertEqual(len(self.server.requests),0)
    def test_13_search_unavailable_dynamic(self):
        (self.root/'websearch/tavily.txt').write_text('{"api_key":""}')
        r=self.cli('task','--name=one','--content=tools');self.assertEqual(r.returncode,0,r.stderr);self.assertNotIn('web_search',r.stdout)
        payload=self.server.requests[-1][1];self.assertIn('web_search is temporarily unavailable',payload['messages'][0]['content'])
        self.assertNotIn('temporarily unavailable',self.file('one','ctx.json').read_text())
    def test_14_search_enabled(self):
        r=self.cli('task','--name=one','--content=web');self.assertEqual(r.returncode,0,r.stderr);self.assertIn('WEB_DONE',r.stdout)
        self.assertIn('/extract',[x[0] for x in self.server.requests])
    def test_15_name_rename_id(self):
        self.cli('task','--name=old','--content=hello');sid=self.sid('old');r=self.cli('session','rename',sid,'新名字');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.sid('新名字'),sid);self.assertNotIn('name',self.info('新名字'))
        self.assertEqual(self.cli('task',sid,'--content=hello').returncode,0)
    def test_16_duplicate_id_and_name(self):
        self.cli('session','add','one');sid=self.sid('one')
        r=self.cli('task','--task='+json.dumps({'session':'one','content':'x'}),'--task='+json.dumps({'session':sid,'content':'y'}))
        self.assertEqual(r.returncode,2);self.assertIn('DUPLICATE_SESSION',r.stderr);self.assertFalse(self.server.requests)
    def test_17_fork_same_snapshot(self):
        self.cli('task','--name=base','--content=readwrite')
        r=self.cli('task','--parallel=2','--task={"name":"a","fork_from":"base","content":"history"}','--task={"name":"b","fork_from":"base","content":"history"}')
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.count('HISTORY_OK'),2)
        self.assertEqual(self.info('a')['parent_id'],self.sid('base'));self.assertFalse((self.root/'sub_workspace'/self.sid('a')/'report.md').exists())
    def test_18_batch_isolation(self):
        r=self.cli('task','--parallel=2','--task={"name":"a","content":"length"}','--task={"name":"b","content":"hello"}')
        self.assertNotEqual(r.returncode,0);self.assertIn('b/status: completed',r.stdout);self.assertLess(r.stdout.index('a/status'),r.stdout.index('b/status'))
    def test_19_clear_no_id_reuse(self):
        self.cli('task','--name=one','--content=hello');hi=self.info('one')['evt_high']
        self.cli('session','del','ctx','one');self.cli('task','one','--content=hello')
        self.assertGreater(self.ctx('one')['events'][0]['evt_id'],hi)
    def test_20_recreate_id_no_artifact_collision(self):
        self.cli('task','--name=one','--content=readwrite');sid=self.sid('one')
        self.cli('session','del','all','one');self.cli('session','add','one')
        self.assertNotEqual(self.sid('one'),sid);self.assertTrue((self.root/'sub_workspace'/sid/'report.md').exists())
    def test_21_raw_query(self):
        self.cli('task','--name=one','--content=hello');ctx=self.ctx('one');eid=ctx['events'][0]['evt_id']
        r=self.cli('session','get','ctx','one','--evt_id='+str(eid));self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout),ctx['events'][0]);self.assertNotIn('[UTC',r.stdout)
        r=self.cli('session','get','ctx','one','--msg_id=1');self.assertEqual(len(r.stdout.splitlines()),2)
    def test_22_raw_display_refusal_export(self):
        self.cli('session','add','one');r=self.cli('session','msg','add','one','--after_msg=0','--content='+'x'*25000);self.assertEqual(r.returncode,0,r.stderr)
        r=self.cli('session','get','ctx','one');self.assertEqual(r.returncode,2);self.assertEqual(r.stdout,'');self.assertIn('DISPLAY_LIMIT',r.stderr)
        dest=Path(self.tmp.name)/'ctx.json';self.assertEqual(self.cli('session','export','ctx','one',str(dest)).returncode,0);self.assertTrue(dest.exists())
        self.assertNotEqual(self.cli('session','export','ctx','one',str(dest)).returncode,0)
    def test_23_edit_and_rerun(self):
        self.cli('task','--name=one','--content=hello');before=self.ctx('one');eid=before['events'][0]['evt_id'];stamp=before['events'][0]['timestamp'];hi=self.info('one')['evt_high']
        r=self.cli('task','rerun','one','--evt_id='+str(eid));self.assertEqual(r.returncode,0,r.stderr)
        after=self.ctx('one');self.assertEqual(after['events'][0]['timestamp'],stamp);self.assertGreater(after['events'][1]['evt_id'],hi)
        text=self.file('one','ctx.json').read_text()
        r=self.cli('session','evt','edit','one','--evt_id='+str(eid),'--content=changed','--rerun')
        self.assertEqual(r.returncode,2);self.assertEqual(text,self.file('one','ctx.json').read_text())
        r=self.cli('session','evt','edit','one','--evt_id='+str(eid),'--content=secret','--rerun','--drop-suffix')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('sk-example',r.stdout)
    def test_24_history_insertion_sequence(self):
        self.cli('task','--name=one','--content=hello');self.cli('session','evt','add','one','--after_evt=1','--content=added')
        self.assertEqual(self.ctx('one')['msgs'][0]['evt_ids'],[1,3])
    def test_25_empty_msg_retained_and_ignored(self):
        self.cli('session','add','one');r=self.cli('session','msg','add','one','--after_msg=0');self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('EMPTY_MSG',r.stderr);self.assertEqual(self.ctx('one')['msgs'][0]['evt_ids'],[])
        r=self.cli('session','evt','add','one','--after_msg=1','--content=hello');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.cli('task','rerun','one','--msg_id=1').returncode,0)
    def test_26_edit_only_user(self):
        self.cli('task','--name=one','--content=hello');raw=self.file('one','ctx.json').read_text()
        r=self.cli('session','evt','edit','one','--evt_id=2','--content=x');self.assertEqual(r.returncode,2);self.assertEqual(raw,self.file('one','ctx.json').read_text())
    def test_27_config_management_with_broken_default(self):
        (self.root/'model/deepseek-flash.txt').unlink()
        self.assertEqual(self.cli('session','add','one').returncode,0)
        self.assertEqual(self.cli('session','get','conf','one').returncode,0)
        r=self.cli('gconf','add','new','--heredoc',stdin=json.dumps({'url':self.url+'/chat','model':'mock','api_key':''}));self.assertEqual(r.returncode,0,r.stderr)
    def test_28_limits_positive(self):
        r=self.cli('task','--name=one','--max-tool-calls=1','--content=loop');self.assertIn('TOOL_LIMIT',r.stderr);self.assertNotEqual(r.returncode,0)
    def test_29_timeout(self):
        self.cfg['url']=self.url+'/slow';self.savecfg()
        r=self.cli('task','--name=one','--task-timeout-seconds=1','--content=hello');self.assertEqual(r.returncode,4,r.stderr);self.assertIn('interrupted',r.stdout)
    def test_30_partial_stream(self):
        r=self.cli('task','--name=one','--content=streambreak');self.assertNotEqual(r.returncode,0)
        ctx=self.ctx('one');self.assertEqual([e['kind'] for e in ctx['events']],['user_content']);self.assertFalse(ctx['msgs'][-1]['complete'])
    def test_31_fork_modes(self):
        self.cli('task','--name=one','--temperature=0.4','--content=hello')
        for mode in ['ctx','conf','all']:
            r=self.cli('session','fork',mode,'one',mode);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(self.file('ctx','config.json').read_text()),{})
        self.assertEqual(self.ctx('conf')['events'],[])
    def test_32_get_no_autocreate(self):
        r=self.cli('session','get','info','absent');self.assertEqual(r.returncode,2);self.assertIn('NOT_FOUND',r.stderr)
        self.assertNotIn('absent',json.loads((self.root/'session_index.json').read_text())['names'])
    def test_33_unknown_id_no_autocreate(self):
        r=self.cli('task','s_'+'a'*32,'--content=hello');self.assertEqual(r.returncode,2)
    def test_34_schema_keys_not_sent(self):
        self.cli('task','--name=one','--content=readwrite')
        for _,body,_ in self.server.requests:
            for m in body.get('messages',[]):
                self.assertFalse(set(m)&{'msg_id','evt_id','timestamp','evt_ids','kind','format'})
    def test_35_config_zero_null_and_auto(self):
        r=self.cli('task','--name=one','--temperature=0','--top-p=null','--reasoning-effort=auto','--content=hello');self.assertEqual(r.returncode,0,r.stderr)
        body=self.server.requests[-1][1];self.assertEqual(body['temperature'],0);self.assertNotIn('top_p',body);self.assertNotIn('reasoning_effort',body)
    def test_36_boundary_edit_not_written(self):
        self.cli('task','--name=one','--content=readwrite');ctx=self.ctx('one');m=next(m for m in ctx['msgs'] if any(e['kind']=='tool_call' and e['evt_id']in m['evt_ids'] for e in ctx['events']))
        raw=self.file('one','ctx.json').read_text()
        r=self.cli('session','msg','add','one','--after_msg='+str(m['msg_id']),'--content=x');self.assertEqual(r.returncode,2);self.assertEqual(raw,self.file('one','ctx.json').read_text())
    def test_37_running_list_overlap(self):
        self.cfg['url']=self.url+'/slow';self.savecfg()
        proc=subprocess.Popen([sys.executable,str(self.root/'src/cli.py'),'task','--task={"name":"a","content":"hello"}','--task={"name":"b","content":"hello"}'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        overlap=False
        for _ in range(20):
            time.sleep(.1);out=self.cli('session','list').stdout.split('Inactive sessions:')[0]
            if 'a\ts_' in out and 'b\ts_' in out:overlap=True;break
        out,err=proc.communicate(timeout=20);self.assertEqual(proc.returncode,0,err);self.assertTrue(overlap)
    def test_38_storage_transactions_recover(self):
        with patch.object(c,'ROOT',self.root):
            c.init();sid=st.add('one',{});s=st.Session(sid)
            c.atomic(s.path/'.transaction.json',{'config.json':{'temperature':.2},'info.json':s.info,'ctx.json':s.ctx})
            s=st.Session(sid);self.assertEqual(s.conf['temperature'],.2);self.assertFalse((s.path/'.transaction.json').exists())
            with st.index_locked() as idx:
                idx['names']['two']=idx['names'].pop('one');c.atomic(c.ROOT/'state/index-transaction.json',{'op':'rename','index':idx})
            self.assertEqual(st.resolve('two')[0],sid)
    def test_39_stream_assembler_completed_blocks(self):
        with patch.object(c,'ROOT',self.root):
            c.init();sid=st.add('one',{});s=st.Session(sid);a=Assembler(s)
            a.feed({'content':'complete'});a.feed({'tool_calls':[{'index':0,'id':'call','type':'function','function':{'name':'x','arguments':'{"half'}}]});a.abort()
            s=st.Session(sid);self.assertEqual([e['value'] for e in s.ctx['events']],['complete']);self.assertGreater(s.info['evt_high'],s.ctx['events'][-1]['evt_id'])
    def test_40_install_uninstall_reinstall(self):
        def script(name,*args):return subprocess.run(['bash',str(self.root/name),*args],capture_output=True,text=True,timeout=30)
        self.assertEqual(script('install.sh','--local').returncode,0)
        self.assertEqual(script('uninstall.sh').returncode,0)
        self.assertTrue((self.root/'model/deepseek-flash.txt').exists());self.assertEqual(script('install.sh','--local').returncode,0)
    def test_41_no_legacy_cli(self):
        self.assertEqual(self.cli('op','self-check').returncode,2);self.assertEqual(self.cli('task','--json','--content=hello').returncode,2)
    def test_42_prompt_no_task_instruction(self):
        self.cli('task','--name=one','--content=hello');sysmsg=self.server.requests[-1][1]['messages'][0]['content']
        self.assertIn('不要因此扫描目录',sysmsg);self.assertNotIn('当前时间',sysmsg)

    def test_43_query_broken_reference_allowed(self):
        self.cli('task','--name=one','--content=hello');p=self.file('one','ctx.json');ctx=self.ctx('one');ctx['msgs'][0]['evt_ids'].append(999);p.write_text(cx.serialize(ctx))
        r=self.cli('session','get','ctx','one','--evt_id=1');self.assertEqual(r.returncode,0,r.stderr)
        r=self.cli('task','one','--content=hello');self.assertNotEqual(r.returncode,0);self.assertIn('MISSING_EVT',r.stderr)
    def test_44_bad_config_edit_does_not_create(self):
        r=self.cli('session','set','conf','ghost','--temperature=1','--unset=temperature');self.assertEqual(r.returncode,2)
        self.assertNotIn('ghost',json.loads((self.root/'session_index.json').read_text())['names']) if (self.root/'session_index.json').exists() else None
    def test_45_missing_fork_does_not_cancel_other(self):
        r=self.cli('task','--task={"name":"bad","fork_from":"missing","content":"hello"}','--task={"name":"ok","content":"hello"}')
        self.assertNotEqual(r.returncode,0);self.assertIn('ok/status: completed',r.stdout)
    def test_46_parent_termination(self):
        self.cfg['url']=self.url+'/slow';self.savecfg()
        proc=subprocess.Popen([sys.executable,str(self.root/'src/cli.py'),'task','--name=one','--content=hello'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        for _ in range(30):
            time.sleep(.05)
            if (self.root/'session_index.json').exists():
                idx=json.loads((self.root/'session_index.json').read_text())['names']
                if 'one' in idx and list((self.root/'session'/idx['one']/'runs').glob('*.json')):break
        proc.terminate();out,err=proc.communicate(timeout=15)
        self.assertNotEqual(proc.returncode,0);self.assertIn('interrupted',out)
    def test_47_install_move(self):
        def install():return subprocess.run(['bash',str(self.root/'install.sh'),'--local'],capture_output=True,text=True,timeout=30)
        self.assertEqual(install().returncode,0)
        moved=self.root.parent/'moved app';self.root.rename(moved);self.root=moved
        self.assertEqual(install().returncode,0)
    def test_48_lifecycle_blocks_uninstall(self):
        self.cli('self-check')
        with open(self.root/'locks/lifecycle.lock','r+') as f:
            fcntl.flock(f,fcntl.LOCK_SH|fcntl.LOCK_NB)
            r=subprocess.run(['bash',str(self.root/'uninstall.sh')],capture_output=True,text=True)
            self.assertEqual(r.returncode,3);self.assertIn('BUSY',r.stderr)
    def test_49_gconf_add_set_del_and_get_filter(self):
        r=self.cli('gconf','add','scratch','--heredoc',stdin=json.dumps({'url':self.url+'/chat','model':'mock','api_key':'example'}));self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.cli('gconf','set','scratch','--temperature=0.2').returncode,0)
        r=self.cli('gconf','get','scratch','--temperature');self.assertEqual(json.loads(r.stdout),{'temperature':.2})
        self.assertEqual(self.cli('gconf','get','scratch','--temperature=0.2').returncode,2)
        self.assertEqual(self.cli('gconf','del','scratch').returncode,0)
    def test_50_mixed_config_failure_no_cancel(self):
        r=self.cli('task','--task={"name":"a","modelconf":"missing","content":"hello"}','--task={"name":"b","content":"hello"}')
        self.assertNotEqual(r.returncode,0);self.assertIn('b/status: completed',r.stdout)
    def test_51_invalid_edit_rerun_keeps_suffix(self):
        self.cli('task','--name=one','--content=hello');before=self.file('one','ctx.json').read_text()
        r=self.cli('session','evt','edit','one','--evt_id=1','--content=changed','--rerun','--drop-suffix','--api-key=')
        self.assertEqual(r.returncode,2);self.assertEqual(before,self.file('one','ctx.json').read_text())
    def test_52_missing_input_no_new_session(self):
        self.assertEqual(self.cli('task','ghost').returncode,2)
        if (self.root/'session_index.json').exists():self.assertNotIn('ghost',json.loads((self.root/'session_index.json').read_text())['names'])

    def test_53_doctor_offline_localhost_no_api(self):
        self.cfg['url']='https://localhost/v1/chat/completions';self.cfg['api_key']='';self.savecfg()
        before=Path('/etc/resolv.conf').read_bytes()
        r=self.cli('doctor','--websearch=none','--samples=1','--timeout=2','--json')
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['hosts'][0]['host'],'localhost')
        self.assertEqual(before,Path('/etc/resolv.conf').read_bytes());self.assertFalse(self.server.requests)
    def test_54_truncated_json_still_exportable(self):
        self.cli('session','add','one');self.file('one','ctx.json').write_text('{broken')
        r=self.cli('session','get','ctx','one');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout,'{broken')
        r=self.cli('session','export','ctx','one',str(Path(self.tmp.name)/'copy'));self.assertEqual(r.returncode,0,r.stderr)
    def test_55_invalid_get_selector(self):
        self.cli('session','add','one');r=self.cli('session','get','info','one','--evt_id=1');self.assertEqual(r.returncode,2)
    def test_56_create_without_provider_access(self):
        self.cfg['api_key']='';self.savecfg();self.assertEqual(self.cli('session','add','one','--heredoc',stdin='{"temperature":0.3}').returncode,0)
        self.assertEqual(self.cli('session','get','info','one').returncode,0)

    def test_57_nonstream_truncation_not_fallback(self):
        r=self.cli('task','--name=one','--stream=false','--content=length');self.assertNotEqual(r.returncode,0);self.assertNotIn('one/answer:',r.stdout)
        self.assertFalse(any(e['kind']=='assistant_content' for e in self.ctx('one')['events']))

    def test_58_display_effective_default_search(self):
        self.cli('session','add','one')
        r=self.cli('session','get','conf','one','--websearch')
        self.assertEqual(json.loads(r.stdout)['websearch'],{'value':'tavily','source':'startup'})
    def test_59_clear_conf_with_invalid_ctx(self):
        self.assertEqual(self.cli('session','add','one').returncode,0)
        self.cli('session','set','conf','one','--temperature=0.5')
        self.file('one','ctx.json').write_text('{broken')
        r=self.cli('session','del','conf','one');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.file('one','ctx.json').read_text(),'{broken')
        self.assertEqual(json.loads(self.file('one','config.json').read_text()),{})
    def test_60_edit_returns_new_event_id(self):
        self.cli('session','add','one')
        r=self.cli('session','msg','add','one','--after_msg=0','--content=a')
        self.assertIn('evt_ids=[1]',r.stdout)
        r=self.cli('session','evt','add','one','--after_evt=1','--content=b')
        self.assertIn('evt_ids=[2]',r.stdout)

    def test_61_typo_reference_errors_without_new_session(self):
        self.cli('task','--name=named1','--content=hello')
        before=(self.root/'session_index.json').read_bytes();ctx=self.file('named1','ctx.json').read_bytes();requests=len(self.server.requests)
        r=self.cli('task','named1_typo','--content=hello')
        self.assertEqual(r.returncode,2,r.stderr);self.assertIn('NOT_FOUND',r.stderr)
        self.assertEqual(before,(self.root/'session_index.json').read_bytes())
        self.assertEqual(ctx,self.file('named1','ctx.json').read_bytes());self.assertEqual(len(self.server.requests),requests)

    def test_62_omitted_ref_creates_named_and_auto_sessions(self):
        r=self.cli('task','--name=调研','--content=hello')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('调研/session: created',r.stdout)
        sid=self.sid('调研');self.assertNotIn('name',self.info('调研'))
        self.assertNotIn('name',json.loads(self.file('调研','config.json').read_text()))
        r=self.cli('task','--content=hello');self.assertEqual(r.returncode,0,r.stderr)
        names=json.loads((self.root/'session_index.json').read_text())['names']
        self.assertEqual(len(names),2);self.assertIn(sid,names.values())

    def test_63_name_on_existing_ref_renames_and_continues(self):
        self.cli('task','--name=old','--content=readwrite');sid=self.sid('old')
        old_ctx=self.ctx('old');oldpath=self.root/'sub_workspace'/sid/'report.md'
        r=self.cli('task','old','--name=新名称','--content=history')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('HISTORY_OK',r.stdout)
        self.assertIn('新名称/answer:',r.stdout);self.assertIn('新名称/renamed-from: old',r.stdout)
        self.assertEqual(self.sid('新名称'),sid);self.assertTrue(oldpath.exists())
        self.assertEqual(old_ctx['msgs'],self.ctx('新名称')['msgs'][:len(old_ctx['msgs'])])
        self.assertNotIn('name',self.info('新名称'))
        self.assertNotIn('old',json.loads((self.root/'session_index.json').read_text())['names'])

    def test_64_id_reference_outputs_human_name_not_id_prefix(self):
        self.cli('task','--name=名字','--content=hello');sid=self.sid('名字')
        r=self.cli('task',sid,'--answer=full','--granularity=fine','--content=readwrite')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('名字/evt/',r.stdout);self.assertIn('名字/evt/',r.stderr)
        self.assertNotIn(sid+'/',r.stderr);self.assertNotIn(sid+'/evt/',r.stdout)
        self.assertEqual(sum(sid in line for line in r.stdout.splitlines() if '/artifact:' not in line),1)
        r=self.cli('task',sid,'--name=再次改名','--answer=summary','--content=hello')
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.sid('再次改名'),sid)
        self.assertIn('再次改名/answer:',r.stdout);self.assertNotIn('sessionid=',r.stderr)

    def test_65_named_new_never_resumes_existing_name(self):
        self.cli('task','--name=one','--content=hello');before=self.file('one','ctx.json').read_bytes()
        r=self.cli('task','--name=one','--content=history')
        self.assertEqual(r.returncode,2);self.assertIn('TARGET_EXISTS',r.stderr)
        self.assertEqual(before,self.file('one','ctx.json').read_bytes())

    def test_66_rename_collision_does_not_change_history_or_conf(self):
        self.cli('task','--name=a','--content=hello');self.cli('task','--name=b','--content=hello')
        before=(self.root/'session_index.json').read_bytes();ctx=self.file('a','ctx.json').read_bytes();cfg=self.file('a','config.json').read_bytes()
        r=self.cli('task','a','--name=b','--temperature=0.4','--content=hello')
        self.assertEqual(r.returncode,2);self.assertIn('TARGET_EXISTS',r.stderr)
        self.assertEqual(before,(self.root/'session_index.json').read_bytes());self.assertEqual(ctx,self.file('a','ctx.json').read_bytes());self.assertEqual(cfg,self.file('a','config.json').read_bytes())

    def test_67_missing_ref_with_name_still_fails(self):
        r=self.cli('task','typo','--name=newname','--content=hello')
        self.assertEqual(r.returncode,2);self.assertIn('NOT_FOUND',r.stderr)
        self.assertEqual(json.loads((self.root/'session_index.json').read_text())['names'],{})

    def test_68_set_conf_missing_never_creates(self):
        r=self.cli('session','set','conf','typo','--temperature=0.6')
        self.assertEqual(r.returncode,2);self.assertIn('NOT_FOUND',r.stderr)
        self.assertEqual(json.loads((self.root/'session_index.json').read_text())['names'],{})

    def test_69_batch_per_task_name_and_rename(self):
        self.cli('task','--name=old','--content=hello');sid=self.sid('old')
        r=self.cli('task','--task={"session":"old","name":"renamed","content":"hello"}','--task={"name":"created","content":"hello"}')
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.sid('renamed'),sid)
        self.assertIn('renamed/answer:',r.stdout);self.assertIn('created/answer:',r.stdout)
        self.assertNotIn('old',json.loads((self.root/'session_index.json').read_text())['names'])

    def test_70_duplicate_batch_names_refused_before_creation(self):
        r=self.cli('task','--task={"name":"new","content":"hello"}','--task={"name":"new","content":"hello"}')
        self.assertEqual(r.returncode,2);self.assertIn('DUPLICATE_SESSION',r.stderr)
        self.assertEqual(json.loads((self.root/'session_index.json').read_text())['names'],{});self.assertFalse(self.server.requests)

    def test_71_batch_unknown_reference_isolated(self):
        r=self.cli('task','--task={"session":"typo","content":"hello"}','--task={"name":"valid","content":"hello"}')
        self.assertEqual(r.returncode,1);self.assertIn('valid/status: completed',r.stdout)
        self.assertEqual(set(json.loads((self.root/'session_index.json').read_text())['names']),{'valid'})

    def test_72_fork_uses_name_not_session_target(self):
        self.cli('task','--name=source','--content=readwrite')
        r=self.cli('task','--task={"fork_from":"source","name":"branch","content":"history"}')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('HISTORY_OK',r.stdout);self.assertEqual(self.info('branch')['parent_id'],self.sid('source'))
        r=self.cli('task','--task={"fork_from":"source","session":"ambiguous","content":"hello"}')
        self.assertEqual(r.returncode,2);self.assertIn('INPUT_CONFLICT',r.stderr);self.assertNotIn('ambiguous',json.loads((self.root/'session_index.json').read_text())['names'])

    def test_73_same_name_is_noop(self):
        self.cli('task','--name=one','--content=hello');sid=self.sid('one')
        r=self.cli('task','one','--name=one','--content=hello');self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotIn('/renamed-from:',r.stdout);self.assertEqual(self.sid('one'),sid)

    def test_74_rename_preflight_failure_preserves_name(self):
        self.cli('task','--name=old','--content=hello');before=self.file('old','ctx.json').read_text()
        r=self.cli('task','old','--name=new','--api-key=','--content=hello');self.assertEqual(r.returncode,2)
        self.assertIn('old',json.loads((self.root/'session_index.json').read_text())['names']);self.assertEqual(before,self.file('old','ctx.json').read_text())

    def test_75_successful_rename_not_undone_by_remote_failure(self):
        self.cli('task','--name=old','--content=hello');sid=self.sid('old')
        r=self.cli('task','old','--name=new','--url='+self.url+'/401','--content=hello')
        self.assertEqual(r.returncode,1);self.assertEqual(self.sid('new'),sid);self.assertIn('new/status: failed',r.stdout)

    def test_76_rename_rerun_preserves_input_timestamp(self):
        self.cli('task','--name=old','--content=hello');stamp=self.ctx('old')['events'][0]['timestamp'];sid=self.sid('old')
        r=self.cli('task','rerun','old','--msg_id=1','--name=new')
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.sid('new'),sid);self.assertEqual(self.ctx('new')['events'][0]['timestamp'],stamp)

    def test_77_empty_or_reserved_names_rejected(self):
        for flag in ('--name=','--name= bad','--name=s_'+'a'*32):
            r=self.cli('task',flag,'--content=hello');self.assertEqual(r.returncode,2,r.stderr)
        r=self.cli('task','--task={"session":"","content":"hello"}')
        self.assertEqual(r.returncode,2);self.assertIn('INVALID_REF',r.stderr);self.assertFalse(self.server.requests)

    def test_78_global_batch_name_rejected(self):
        r=self.cli('task','--name=x','--task={"name":"a","content":"hello"}')
        self.assertEqual(r.returncode,2);self.assertIn('INPUT_CONFLICT',r.stderr)

    def test_79_del_ctx_keeps_runnable_identity(self):
        self.cli('task','--name=one','--content=hello');sid=self.sid('one')
        self.cli('session','del','ctx','one')
        self.assertIn('one\t'+sid,self.cli('session','list').stdout)
        r=self.cli('task','one','--content=hello');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(self.sid('one'),sid)

    def test_80_summary_instructions_include_no_task_submission(self):
        self.cli('task','--name=one','--content=hello')
        system=self.server.requests[-1][1]['messages'][0]['content']
        for phrase in ('没有任务且无后续操作时','以上情形至少提交一次','用户正文提出字数或篇幅要求','未提出时自行简短回答','本次提交的字符数','最后一次有效提交','不要因此扫描目录'):
            self.assertIn(phrase,system)
        self.assertNotIn('有实际委派任务时',system)
        # Actual-model compliance is NOT tested here; mock intentionally omits submit to exercise fallback.
        self.assertIn('Hello',self.cli('task','one','--content=hello').stdout)

    def test_81_full_also_requires_submission(self):
        self.cli('task','--name=one','--answer=full','--content=hello')
        system=self.server.requests[-1][1]['messages'][0]['content']
        self.assertIn('full 模式下',system);self.assertIn('问候或测试也通过 submit_answer',system)
        self.assertIn('以上情形至少提交一次',system)

    def test_82_missing_file_reason_reaches_model_and_parent(self):
        r=self.cli('task','--name=one','--content=missingfile')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('FILE_NOT_FOUND',r.stderr);self.assertNotIn('Invalid tool JSON',r.stderr)
        toolmsg=next(m for _,body,_ in self.server.requests for m in body.get('messages',[]) if m['role']=='tool')
        result=json.loads(toolmsg['content']);self.assertEqual(result['error'],'FILE_NOT_FOUND');self.assertEqual(result['errno'],'ENOENT')
        self.assertEqual(result['path'],str(self.root/'input/absent.md'));self.assertIn('No such file',result['message'])
        self.assertNotIn('valid JSON',result['message'])

    def test_83_bad_json_still_reports_bad_json(self):
        r=self.cli('task','--name=one','--content=badjson')
        self.assertEqual(r.returncode,0,r.stderr)
        values=[json.loads(e['value']['content']) for e in self.ctx('one')['events'] if e['kind']=='tool']
        self.assertEqual(values[0]['error'],'INVALID_TOOL_ARGUMENTS');self.assertNotIn('errno',values[0])

    def test_84_summary_mock_greeting_submission_lifecycle(self):
        self.server.submit_greeting=True
        r=self.cli('task','--name=one','--content=hello')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('submitted=true',r.stdout);self.assertNotIn('NO_SUBMISSION',r.stderr)
        self.assertIn('GREETING_SUBMITTED',r.stdout);self.assertNotIn('CLOSING',r.stdout)
        calls=[e['value']['function']['name'] for e in self.ctx('one')['events'] if e['kind']=='tool_call' and isinstance(e['value'],dict)]
        self.assertEqual(calls,['submit_answer'])
        self.assertTrue(any(e['kind']=='assistant_content' and e['value']=='CLOSING' for e in self.ctx('one')['events']))

    def test_85_busy_session_cannot_be_renamed_via_task(self):
        self.cli('session','add','old');sid=self.sid('old')
        with open(self.root/'locks'/(sid+'.lock'),'w') as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            r=self.cli('task',sid,'--name=new','--content=hello');self.assertEqual(r.returncode,3,r.stderr)
        self.assertEqual(self.sid('old'),sid);self.assertNotIn('new',json.loads((self.root/'session_index.json').read_text())['names'])

    def test_86_full_last_submission_with_revisions(self):
        r=self.cli('task','--name=one','--answer=full','--granularity=fine','--content=revise')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('STEP0',r.stdout);self.assertIn('STEP1',r.stdout);self.assertIn('CLOSING',r.stdout)
        self.assertIn('one/answer: REVISED '+('长'*800),r.stdout)
        self.assertEqual(r.stdout.count('one/answer:'),1);self.assertNotIn('FIRST',r.stdout)
        self.assertNotIn('REVISED',r.stderr);self.assertNotIn('长'*800,r.stderr)

    def test_87_full_greeting_submits_and_closes(self):
        self.server.submit_greeting=True
        r=self.cli('task','--name=one','--answer=full','--content=hello')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('submitted=true',r.stdout)
        self.assertIn('CLOSING',r.stdout);self.assertIn('one/answer: GREETING_SUBMITTED',r.stdout)
        self.assertNotIn('NO_SUBMISSION',r.stderr)
        calls=[e['value']['function']['name'] for e in self.ctx('one')['events'] if e['kind']=='tool_call' and isinstance(e['value'],dict)]
        self.assertEqual(calls,['submit_answer'])

    def test_88_full_missing_submission_still_warns_and_marks_answer(self):
        r=self.cli('task','--name=one','--answer=full','--content=hello')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('NO_SUBMISSION',r.stderr)
        self.assertIn('submitted=false',r.stdout);self.assertIn('one/answer: Hello',r.stdout)
        self.assertTrue(any('/evt/'in line and 'Hello'in line for line in r.stdout.splitlines()))

    def test_89_full_failure_after_submit_not_success(self):
        r=self.cli('task','--name=one','--answer=full','--content=failafter')
        self.assertNotEqual(r.returncode,0);self.assertIn('status: failed',r.stdout)
        self.assertIn('one/answer: BEFORE_ERROR',r.stdout);self.assertIn('API_HTTP_ERROR',r.stderr)

    def test_90_full_invalid_resubmit_keeps_last_valid(self):
        r=self.cli('task','--name=one','--answer=full','--content=invalid_submit')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('one/answer: VALID',r.stdout)
        self.assertEqual(r.stdout.count('one/answer:'),1);self.assertIn('TOOL_FAILED',r.stderr)

    def test_91_full_submission_without_visible_content(self):
        r=self.cli('task','--name=one','--answer=full','--content=onlysubmit')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('one/answer: ONLY_SUBMITTED_BODY',r.stdout)
        self.assertNotIn('one/evt/',r.stdout);self.assertIn('submitted=true',r.stdout)

    def test_92_no_length_setting_in_help_profiles_or_config(self):
        for command in [('task','--help'),('session','set','conf','--help'),('gconf','set','--help'),('gconf','get','deepseek-flash')]:
            r=self.cli(*command);self.assertEqual(r.returncode,0,r.stderr)
            self.assertNotIn('summary_chars',r.stdout);self.assertNotIn('summary-chars',r.stdout)
        for args in [('task','--summary-chars=1','--content=hello'),('gconf','set','deepseek-flash','--summary_chars=1')]:
            r=self.cli(*args);self.assertEqual(r.returncode,2)
        r=self.cli('task','--task={"name":"one","content":"hello","summary_chars":10}')
        self.assertEqual(r.returncode,2);self.assertFalse(self.server.requests)

    def test_93_feedback_actual_characters_without_length_target(self):
        r=self.cli('task','--name=one','--answer=full','--content=unicode_submit')
        self.assertEqual(r.returncode,0,r.stderr)
        values=[json.loads(e['value']['content']) for e in self.ctx('one')['events'] if e['kind']=='tool']
        self.assertEqual(values[0]['chars'],len('好，A !\n🙂'))
        self.assertEqual(set(values[0]),{'submitted','chars','note'})
        self.assertNotIn('target',values[0]['note'].lower())
        cfg=json.loads(self.file('one','config.json').read_text());self.assertNotIn('summary_chars',cfg)
        self.assertNotIn('summary_chars',self.info('one')['last_effective']['values'])

    def test_94_same_submission_policy_across_modes(self):
        for mode in ('summary','full'):
            r=self.cli('task','--name='+mode,'--answer='+mode,'--content=hello')
            self.assertEqual(r.returncode,0,r.stderr)
            body=self.server.requests[-1][1];system=body['messages'][0]['content']
            self.assertIn('无论 summary 还是 full，以上情形至少提交一次',system)
            self.assertIn('按用户要求组织答案',system);self.assertIn('未提出时自行简短回答',system)
            for retired in ('summary_chars','target_chars','约 200','可超出的软目标'):self.assertNotIn(retired,system)
            fn=next(x['function'] for x in body['tools'] if x['function']['name']=='submit_answer')
            self.assertIn('所有回答模式',fn['description'])
            self.assertEqual(fn['parameters']['required'],['answer'])

    def test_95_full_does_not_reuse_previous_submission(self):
        self.cli('task','--name=one','--answer=full','--content=readwrite')
        r=self.cli('task','one','--content=hello')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('NO_SUBMISSION',r.stderr)
        self.assertIn('one/answer: Hello',r.stdout);self.assertNotIn('FINAL_SUBMISSION',r.stdout)

    def test_96_install_cleans_legacy_config_without_changing_context(self):
        self.cli('task','--name=one','--content=hello')
        self.cfg['summary_chars']=123;self.savecfg()
        cfg=json.loads(self.file('one','config.json').read_text());cfg.update(summary_chars=456,temperature=.4)
        self.file('one','config.json').write_text(json.dumps(cfg))
        oldctx=self.file('one','ctx.json').read_bytes();oldinfo=self.file('one','info.json').read_bytes()
        r=subprocess.run(['bash',str(self.root/'install.sh'),'--local'],capture_output=True,text=True,timeout=30)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertNotIn('summary_chars',json.loads((self.root/'model/deepseek-flash.txt').read_text()))
        self.assertEqual(json.loads((self.root/'model/deepseek-flash.txt').read_text())['api_key'],'mock-key')
        self.assertEqual(json.loads(self.file('one','config.json').read_text()),{'temperature':.4})
        self.assertEqual(self.file('one','ctx.json').read_bytes(),oldctx)
        self.assertEqual(self.file('one','info.json').read_bytes(),oldinfo)
        self.assertNotIn('mock-key',r.stdout+r.stderr)
        r=self.cli('task','one','--answer=full','--content=hello');self.assertEqual(r.returncode,0,r.stderr)
