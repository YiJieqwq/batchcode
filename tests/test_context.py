import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import common as c
import context as cx

class ContextTests(unittest.TestCase):
    def setUp(self):self.ctx=cx.empty();self.h={'evt':0,'msg':0}
    def alloc(self,k):self.h[k]+=1;return self.h[k]
    def add(self,raw,complete=True):return cx.from_native(self.ctx,raw,self.alloc,complete)
    def wire(self,provider='deepseek',pending=False):return cx.compile_ctx(self.ctx,provider,c.Diagnostics(),pending)[0]
    def toolturn(self):
        self.add({'role':'user','content':'read'})
        self.add({'role':'assistant','content':'I read','tool_calls':[{'id':x,'type':'function','function':{'name':'read_file','arguments':'{"path":"x"}'}} for x in ['a','b']]})
        self.add({'role':'tool','tool_call_id':'a','content':'A'})
        self.add({'role':'tool','tool_call_id':'b','content':'B'})
        self.add({'role':'assistant','content':'done'})
    def test_01_native_field_order(self):
        self.add({'role':'assistant','content':'hello','tool_calls':[],'reasoning_content':'thinking'})
        self.assertEqual([e['kind'] for e in self.ctx['events']],['assistant_content','tool_call','reasoning_content'])
    def test_02_empty_tool_values(self):
        for v in [None,[]]:
            self.ctx=cx.empty();self.add({'role':'assistant','tool_calls':v})
            self.assertEqual(self.wire()[0],{'role':'assistant','tool_calls':v})
            self.assertEqual(len(self.ctx['events']),1)
    def test_03_missing_content_not_fabricated(self):
        self.add({'role':'assistant','tool_calls':[]});self.assertNotIn('content',self.wire()[0])
    def test_04_content_null_empty(self):
        for value in [None,'']:
            self.ctx=cx.empty();self.add({'role':'assistant','content':value});self.assertIs(self.wire()[0]['content'],value)
    def test_05_milestone_pure(self):
        self.add({'role':'user','content':'hello'});before=copy.deepcopy(self.ctx)
        a=self.wire();b=self.wire();self.assertEqual(a,b);self.assertEqual(before,self.ctx)
        self.assertEqual(a[0]['content'].count('[UTC'),1)
    def test_06_role_inference_reasoning(self):
        self.add({'role':'assistant','reasoning_content':'a'});self.assertEqual(self.wire()[0]['role'],'assistant')
    def test_07_duplicate_and_interleaved_content(self):
        m=self.add({'role':'assistant','content':'A','tool_calls':[]})
        i=self.alloc('evt');self.ctx['events'].append({'evt_id':i,'timestamp':c.now(),'kind':'assistant_content','value':'B'});m['evt_ids'].append(i)
        self.assertEqual(self.wire()[0]['content'],'AB');self.assertEqual(m['evt_ids'],[1,2,3])
    def test_08_cross_protocol_rejected(self):
        m=self.add({'role':'assistant','content':'a'});m['format']='blocks'
        with self.assertRaises(c.Failure):self.wire()
    def test_09_source_immutable_switch(self):
        self.add({'role':'assistant','reasoning_content':'x','content':'y'});before=copy.deepcopy(self.ctx)
        self.assertNotIn('reasoning_content',self.wire('openai')[0]);self.assertEqual(self.ctx,before)
    def test_10_role_conflict(self):
        m=self.add({'role':'user','content':'x'});n=self.add({'role':'assistant','content':'y'});m['evt_ids']+=n['evt_ids'];self.ctx['msgs'].remove(n)
        with self.assertRaises(c.Failure):self.wire()
    def test_11_orphan(self):
        self.add({'role':'user','content':'x'});self.ctx['msgs']=[]
        with self.assertRaises(c.Failure):self.wire()
    def test_12_shared_evt(self):
        m=self.add({'role':'user','content':'x'});self.ctx['msgs'].append({'msg_id':self.alloc('msg'),'evt_ids':m['evt_ids']})
        with self.assertRaises(c.Failure):self.wire()
    def test_13_pending_calls(self):
        self.toolturn();self.ctx['msgs'].pop(3);self.ctx['events']=[e for e in self.ctx['events'] if e['kind']!='tool' or e['value']['tool_call_id']!='b']
        with self.assertRaises(c.Failure):self.wire()
    def test_14_normal_pairing(self):self.toolturn();self.assertEqual(len(self.wire()),5)
    def test_15_multi_tool_boundaries(self):
        self.toolturn()
        for pos in [2,3]:
            with self.assertRaises(c.Failure):cx.boundary(self.ctx,pos)
        cx.boundary(self.ctx,4)
    def test_16_empty_group_skipped(self):
        self.ctx['msgs'].append({'msg_id':1,'evt_ids':[]});diag=c.Diagnostics()
        self.assertEqual(cx.compile_ctx(self.ctx,'deepseek',diag)[0],[])
        cx.compile_ctx(self.ctx,'deepseek',diag);self.assertEqual(len(diag.items),1)
    def test_17_partial_group_ignored(self):
        self.add({'role':'assistant','content':'received block'},False);diag=c.Diagnostics()
        self.assertEqual(cx.compile_ctx(self.ctx,'deepseek',diag)[0],[]);self.assertEqual(self.ctx['events'][0]['value'],'received block')
    def test_18_evt_add_inside_user(self):
        m=self.add({'role':'user','content':'a'});self.h['evt']=80
        out,t=cx.edit(self.ctx,'evt','add',NS(after_evt=1,after_msg=None,content='b'),self.alloc)
        self.assertEqual(out['msgs'][0]['evt_ids'],[1,81])
    def test_19_evt_add_after_nonuser_mid_rejected(self):
        self.add({'role':'assistant','content':'a','tool_calls':[]})
        with self.assertRaises(c.Failure):cx.edit(self.ctx,'evt','add',NS(after_evt=1,after_msg=None,content='x'),self.alloc)
    def test_20_msg_add_inside_tools_rejected(self):
        self.toolturn()
        for mid in [2,3]:
            with self.assertRaises(c.Failure):cx.edit(self.ctx,'msg','add',NS(after_msg=mid,content='x'),self.alloc)
    def test_21_evt_add_next_user(self):
        self.add({'role':'assistant','content':'a'});self.add({'role':'user','content':'b'})
        out,t=cx.edit(self.ctx,'evt','add',NS(after_evt=1,after_msg=None,content='x'),self.alloc)
        self.assertEqual(out['msgs'][1]['evt_ids'],[3,2]);self.assertEqual(len(out['msgs']),2)
    def test_22_msg_add_empty_and_fill(self):
        out,t=cx.edit(self.ctx,'msg','add',NS(after_msg=0,content=None),self.alloc)
        self.assertEqual(t['evt_ids'],[])
        out,t=cx.edit(out,'evt','add',NS(after_msg=t['msg_id'],after_evt=None,content='x'),self.alloc)
        self.assertEqual(len(out['events']),1)
    def test_23_delete_last_evt_leaves_placeholder(self):
        self.add({'role':'user','content':'x'})
        out,_=cx.edit(self.ctx,'evt','del',NS(evt_id=1,drop_suffix=False),self.alloc)
        self.assertEqual(out['msgs'][0]['evt_ids'],[])
    def test_24_edit_requires_explicit_drop(self):
        self.add({'role':'user','content':'x'})
        with self.assertRaises(c.Failure):cx.edit(self.ctx,'evt','edit',NS(evt_id=1,content='y',rerun=True,drop_suffix=False),self.alloc)
        self.assertEqual(self.ctx['events'][0]['value'],'x')
    def test_25_drop_evt_granularity(self):
        self.add({'role':'user','content':'a'})
        self.ctx,_=cx.edit(self.ctx,'evt','add',NS(after_evt=1,after_msg=None,content='b'),self.alloc)
        self.add({'role':'assistant','content':'c'})
        out,_=cx.edit(self.ctx,'evt','edit',NS(evt_id=1,content='z',drop_suffix=True,rerun=False),self.alloc)
        self.assertEqual(len(out['events']),1);self.assertEqual(out['events'][0]['value'],'z')
    def test_26_del_msg_suffix(self):
        self.toolturn();out,_=cx.edit(self.ctx,'msg','del',NS(msg_id=1,drop_suffix=True),self.alloc)
        self.assertEqual(out['msgs'],[]);self.assertEqual(out['events'],[])
    def test_27_get_ids_not_positions(self):
        self.add({'role':'user','content':'a'});self.h['evt']=20;self.add({'role':'assistant','content':'b'})
        _,ev=cx.select(self.ctx,NS(evt_id=21));self.assertEqual(ev[0]['value'],'b')
    def test_28_arguments_raw(self):
        args='{ "path" : "x", "text": "sk-not-a-secret" }'
        self.add({'role':'assistant','tool_calls':[{'id':'c','type':'function','function':{'name':'x','arguments':args}}]})
        self.assertEqual(self.wire(pending=True)[0]['tool_calls'][0]['function']['arguments'],args)
    def test_29_serializer_line_records(self):
        self.toolturn();txt=cx.serialize(self.ctx);self.assertEqual(json.loads(txt),self.ctx)
        for line in txt.splitlines():
            if 'evt_id' in line and 'evt_ids' not in line:self.assertIn('value',json.loads(line.rstrip(',')))
    def test_30_time_all_utc(self):
        self.toolturn();self.assertTrue(all(e['timestamp'].endswith('Z') for e in self.ctx['events']))
