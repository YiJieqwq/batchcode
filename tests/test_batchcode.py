import concurrent.futures
import fcntl
from http.server import ThreadingHTTPServer
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
from mock_server import MockHandler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import engine as e

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='batchcode-test-')
        self.root=Path(self.tmp.name)/'app'
        shutil.copytree(ROOT,self.root,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','sessions','logs','locks','running','sub_workspace','dist'))
        (self.root/'input').mkdir();(self.root/'input/doc.md').write_text('文档测试内容')
        self.cfg=json.loads((self.root/'config.default.json').read_text())
        self.cfg.update(allow_http_endpoints=True,read_roots=['./input','./sub_workspace'],http_retries=0)
        self.savecfg()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),MockHandler)
        self.server.root=self.root;self.server.requests=[]
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        self.model('/chat')
        (self.root/'websearch/tavily.txt').write_text(json.dumps({'url':self.url+'/search','extract_url':self.url+'/extract','api_key':'tvly-mock-secret'}))
    def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def savecfg(self):(self.root/'config.json').write_text(json.dumps(self.cfg))
    def model(self,route):
        (self.root/'model/deepseek-flash.txt').write_text(json.dumps({'url':self.url+route,'model':'mock','api_key':'sk-mock-secret'}))
    def cli(self,*args,stdin=None):
        return subprocess.run([sys.executable,str(self.root/'src/cli.py'),*args],input=stdin,text=True,capture_output=True,timeout=15,cwd='/tmp')
    def obj(self,sid):return json.loads((self.root/'sessions'/f'{sid}.json').read_text())
    def test_single_full_content_and_streams(self):
        for gran in ['coarse','fine']:
            r=self.cli('task','--session='+gran,'--content=readwrite','--granularity='+gran)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertIn('VISIBLE_PROGRESS',r.stdout);self.assertIn('FINAL_OK',r.stdout)
            self.assertNotIn('private-reasoning',r.stdout+r.stderr)
            self.assertNotIn('tool_call',r.stdout)
            self.assertTrue((self.root/'sub_workspace'/gran/'report.md').exists())
            if gran=='fine':self.assertIn('read_file:',r.stderr)
            else:self.assertEqual(r.stderr,'Tool call records are hidden\n')
    def test_resume_sequence(self):
        self.cli('task','--session=01','--content=readwrite')
        first=self.obj('01')['seq']
        r=self.cli('task','--session=01','--content=history')
        self.assertIn('HISTORY_OK',r.stdout);self.assertIn(f'01/evt/{first+1}',r.stdout)
    def test_config_create_inherit_unset(self):
        self.assertIn('not_found',self.cli('op','config','s','--session=01').stdout)
        self.assertFalse((self.root/'sessions/01.json').exists())
        self.assertEqual(self.cli('op','config','s','--session=01','--websearch=tavily').returncode,0)
        self.assertEqual(self.cli('op','config','g','--granularity=fine').returncode,0)
        r=self.cli('task','--session=01','--content=web')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('web_search:',r.stderr)
        self.assertEqual(self.cli('op','config','s','--session=01','--unset=websearch').returncode,0)
        self.assertEqual(self.obj('01')['overrides'],{})
        self.assertIn('source=global',self.cli('op','config','s','--session=01').stdout)
    def test_override_does_not_persist(self):
        self.cli('op','config','s','--session=01','--websearch=tavily')
        r=self.cli('task','--session=01','--websearch=none','--content=test')
        self.assertEqual(r.returncode,0)
        names=[t['function']['name'] for t in self.server.requests[-1][1]['tools']]
        self.assertNotIn('web_search',names);self.assertEqual(self.obj('01')['overrides']['websearch'],'tavily')
    def test_fork_delete(self):
        self.cli('task','--session=base','--content=readwrite')
        r=self.cli('op','fork-session','--session=base','--target-session=branch')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.obj('branch')['messages'],self.obj('base')['messages'])
        self.assertFalse((self.root/'sub_workspace/branch/report.md').exists())
        self.assertIn('HISTORY_OK',self.cli('task','--session=branch','--content=history').stdout)
        self.assertNotEqual(self.cli('op','fork-session','--session=base','--target-session=branch').returncode,0)
        self.cli('op','delete-session','--session=base')
        self.assertTrue((self.root/'sub_workspace/base/report.md').exists())
        self.assertIn('not_found',self.cli('op','delete-session','--session=base').stdout)
    def test_batch_parallel_isolation_order(self):
        r=self.cli('task','--parallel=2','--granularity=fine','--task={"session":"a","content":"readwrite"}','--task={"session":"b","content":"readwrite"}')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('[task 2/2 done',r.stdout)
        self.assertLess(r.stdout.index('a/status'),r.stdout.index('b/status'))
        for sid in ['a','b']:self.assertTrue((self.root/f'sub_workspace/{sid}/report.md').exists())
    def test_batch_fork_snapshot(self):
        self.cli('task','--session=base','--content=test')
        r=self.cli('task','--tasks-stdin',stdin=json.dumps([{'fork_from':'base','session':s,'content':'history'} for s in ['a','b']]))
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.count('HISTORY_OK'),2)
        self.assertEqual(self.obj('a')['parent'],'base')
    def test_mixed_failure_continues(self):
        r=self.cli('task','--task={"session":"a","content":"length"}','--task={"session":"b","content":"test"}')
        self.assertEqual(r.returncode,1);self.assertIn('b/status: completed',r.stdout);self.assertIn('MODEL_INCOMPLETE',r.stderr)
    def test_validation_before_execution(self):
        r=self.cli('task','--task={"session":"a","content":"test"}','--task={"session":"a","content":"test"}')
        self.assertEqual(r.returncode,2);self.assertFalse((self.root/'sessions/a.json').exists())
        self.assertEqual(self.cli('task','--session=../x','--content=test').returncode,2)
        self.assertEqual(self.cli('op','config','s','--session=01','--parallel=2').returncode,2)
    def test_list_and_locks(self):
        self.cli('op','config','s','--session=01','--granularity=fine')
        self.cli('op','config','s','--session=02','--granularity=fine')
        with open(self.root/'running/01.lock','w') as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(self.cli('task','list').stdout,'Active sessions:\n01\nInactive sessions:\n02\n')
        with open(self.root/'locks/01.lock','w') as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(self.cli('task','--session=01','--content=test').returncode,3)
            self.assertEqual(self.cli('op','delete-session','--session=01').returncode,3)
            self.assertIn('Active sessions:\nInactive sessions:',self.cli('task','list').stdout)
    def test_http_failure_details(self):
        self.model('/fail');r=self.cli('task','--session=bad','--content=test')
        self.assertEqual(r.returncode,1);self.assertNotIn('sk-secret',r.stdout+r.stderr)
        self.assertEqual(self.obj('bad')['error_detail']['http_status'],401)
        self.assertIn('401',(self.root/'logs/bad.jsonl').read_text())
    def test_timeout_resume(self):
        self.model('/slow');self.cfg['task_timeout_seconds']=1;self.savecfg()
        r=self.cli('task','--session=t','--content=test');self.assertEqual(r.returncode,4,r.stdout+r.stderr)
        self.assertEqual(self.obj('t')['status'],'interrupted')
        self.model('/chat');self.cfg['task_timeout_seconds']=10;self.savecfg()
        self.assertEqual(self.cli('task','--session=t','--content=test').returncode,0)
    def test_secret_and_empty_key(self):
        r=self.cli('task','--session=s','--content=secret');self.assertNotIn('sk-mock-secret',r.stdout+r.stderr)
        p=self.root/'model/deepseek-flash.txt';obj=json.loads(p.read_text());obj['api_key']='';p.write_text(json.dumps(obj))
        self.assertEqual(self.cli('op','self-check').returncode,0)
        self.assertEqual(self.cli('task','--content=test').returncode,2)
    def test_write_boundaries(self):
        with patch.object(e,'ROOT',self.root):
            e.init_dirs()
            for name in ['../escape','/tmp/escape','a/../../escape']:
                with self.assertRaises(e.Failure):e.sandbox_write(name,'bad',100,'01')
            outside=Path(self.tmp.name)/'outside';outside.mkdir()
            (self.root/'sub_workspace/01').symlink_to(outside)
            with self.assertRaises(OSError):e.sandbox_write('x','bad',100,'01')
            (self.root/'sub_workspace/01').unlink();(self.root/'sub_workspace/01').mkdir()
            target=outside/'file';target.write_text('KEEP')
            (self.root/'sub_workspace/01/hard').hardlink_to(target)
            e.sandbox_write('hard','NEW',100,'01');self.assertEqual(target.read_text(),'KEEP')
    def test_read_boundaries(self):
        with patch.object(e,'ROOT',self.root):
            e.init_dirs();tools=e.Tools(self.cfg,None,None,'01')
            for p in ['/etc/passwd',str(self.root/'model/deepseek-flash.txt')]:
                with self.assertRaises(e.Failure):tools.execute('read_file',{'path':p})
            (self.root/'input/link').symlink_to(self.root/'model/deepseek-flash.txt')
            with self.assertRaises(e.Failure):tools.execute('read_file',{'path':str(self.root/'input/link')})
    def test_public_urls(self):
        for url in ['file:///etc/passwd','http://127.0.0.1','http://10.0.0.1','https://user:pass@example.com']:
            with self.assertRaises(e.Failure):e.public_url(url)
    def test_install_local_repeat_move(self):
        def install():return subprocess.run(['bash',str(self.root/'install.sh'),'--local'],capture_output=True,text=True,timeout=30)
        key=(self.root/'model/deepseek-flash.txt').read_bytes()
        self.assertEqual(install().returncode,0);self.assertEqual(install().returncode,0)
        self.assertEqual(key,(self.root/'model/deepseek-flash.txt').read_bytes())
        dst=self.root.parent/'moved app';self.root.rename(dst);self.root=dst
        self.assertEqual(install().returncode,0)
    def test_real_overlap_and_active_list(self):
        self.model('/slow')
        command=[sys.executable,str(self.root/'src/cli.py'),'task','--parallel=2',
            '--task={"session":"a","content":"test"}','--task={"session":"b","content":"test"}']
        proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        overlap=False
        for _ in range(20):
            time.sleep(0.1)
            listing=self.cli('task','list').stdout
            if 'Active sessions:\na\nb\nInactive sessions:' in listing:overlap=True;break
        out,err=proc.communicate(timeout=10)
        self.assertEqual(proc.returncode,0,out+err);self.assertTrue(overlap,listing)
    def test_model_switch_and_fork_overrides(self):
        self.cli('task','--session=base','--content=readwrite')
        shutil.copy(self.root/'model/deepseek-flash.txt',self.root/'model/other.txt')
        self.assertEqual(self.cli('op','config','s','--session=base','--model=other').returncode,0)
        self.assertEqual(self.cli('op','fork-session','--session=base','--target-session=b').returncode,0)
        self.assertEqual(self.obj('b')['overrides']['model'],'other')
        self.assertEqual(self.cli('task','--session=b','--content=history').returncode,0)
        messages=self.server.requests[-1][1]['messages']
        self.assertFalse(any('reasoning_content' in m for m in messages))
    def test_interrupted_tool_history_and_null_calls(self):
        self.cli('task','--session=base','--content=test')
        p=self.root/'sessions/base.json';obj=self.obj('base');obj['status']='running'
        obj['messages'][-1]['tool_calls']=None
        obj['messages'].append({'role':'assistant','content':None,'tool_calls':[{'id':'pending','type':'function','function':{'name':'read_file','arguments':'{}'}}]})
        p.write_text(json.dumps(obj))
        r=self.cli('task','--session=base','--content=test')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('PREVIOUS_RUN_INTERRUPTED',r.stderr)
        self.assertTrue(any(m.get('tool_call_id')=='pending' for m in self.obj('base')['messages']))
    def test_round_context_write_limits(self):
        self.cfg['max_model_calls']=1;self.savecfg()
        self.assertIn('ROUND_LIMIT',self.cli('task','--content=loop').stderr)
        self.cfg['max_context_chars']=100;self.savecfg()
        self.assertIn('CONTEXT_LIMIT',self.cli('task','--content=test').stderr)
        with patch.object(e,'ROOT',self.root):
            with self.assertRaises(e.Failure):e.sandbox_write('big','x'*11,10,'a')
    def test_fetch_and_no_tools(self):
        r=self.cli('task','--websearch=tavily','--content=web')
        self.assertEqual(r.returncode,0,r.stderr)
        paths=[p for p,b,a in self.server.requests]
        self.assertIn('/search',paths);self.assertIn('/extract',paths)
        self.cli('task','--content=test')
        self.assertNotIn('web_search',[t['function']['name'] for t in self.server.requests[-1][1]['tools']])
    def test_invalid_global_config(self):
        self.cfg['unknown']=True;self.savecfg()
        self.assertIn('INVALID_CONFIG',self.cli('task','--content=test').stdout)
    def test_stdin_and_limits(self):
        self.assertEqual(self.cli('task','--content-stdin',stdin='test').returncode,0)
        self.cfg['max_tool_calls']=1;self.savecfg()
        r=self.cli('task','--content=loop');self.assertIn('TOOL_LIMIT',r.stderr)

if __name__=='__main__':unittest.main(verbosity=2)
