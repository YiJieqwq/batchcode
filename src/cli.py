#!/usr/bin/env python3
"""Object-first CLI. No old op/sconf aliases; final diagnostics precede stderr traces."""
import argparse
import concurrent.futures
import contextlib
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid
import tempfile
import common as c
import configuration as conf
import context as cx
import storage as st

class Parser(argparse.ArgumentParser):
    def error(self,text):raise c.Failure('INVALID_ARGUMENT',text,2)

def value(k,text):
    if text=='null' and k in set(conf.API_PARAMS)|{'websearch'}:return None
    if k=='websearch' and text=='none':return None
    default=conf.DEFAULTS.get(k)
    if type(default)in (dict,list,bool) or type(default)is int or k in ('temperature','top_p','presence_penalty','frequency_penalty'):
        try:return c.decode(text)
        except ValueError:raise argparse.ArgumentTypeError(f'{k} expects a JSON value')
    return text

def options(p,get=False,session=True,batch=False):
    for k in sorted(conf.SESSION_FIELDS if session else conf.FIELDS):
        if k=='parallel' and session and not batch:continue
        flags=['--'+k.replace('_','-')]
        if flags[0]!='--'+k:flags.append('--'+k)
        if get:p.add_argument(*flags,dest=k,action='store_true',default=argparse.SUPPRESS)
        else:p.add_argument(*flags,dest=k,type=lambda s,k=k:value(k,s),default=argparse.SUPPRESS)

def target_flags(p):
    g=p.add_mutually_exclusive_group(required=True);g.add_argument('--evt_id',type=int);g.add_argument('--msg_id',type=int)

def parser():
    p=Parser(prog='batchcode');p.add_argument('--version',action='version',version=c.VERSION)
    top=p.add_subparsers(dest='command',required=True)
    t=top.add_parser('task');t.add_argument('refs',nargs='*',help='[session ref] or rerun <ref>')
    options(t,batch=True);target=t.add_mutually_exclusive_group();target.add_argument('--evt_id',type=int);target.add_argument('--msg_id',type=int)
    t.add_argument('--content');t.add_argument('--content-stdin',action='store_true');t.add_argument('--task',action='append');t.add_argument('--tasks-stdin',action='store_true')
    g=top.add_parser('gconf').add_subparsers(dest='action',required=True)
    for action in ('add','set','get','del'):
        q=g.add_parser(action);q.add_argument('name')
        if action=='add':q.add_argument('--heredoc',action='store_true',required=True)
        if action in ('set','get'):options(q,get=action=='get',session=False)
        if action=='set':q.add_argument('--unset',action='append',choices=sorted(conf.FIELDS))
    se=top.add_parser('session').add_subparsers(dest='action',required=True)
    q=se.add_parser('add');q.add_argument('ref');q.add_argument('--heredoc',action='store_true')
    q=se.add_parser('set');q.add_argument('part',choices=['conf']);q.add_argument('ref');options(q);q.add_argument('--unset',action='append',choices=sorted(conf.SESSION_FIELDS-{'parallel'}))
    q=se.add_parser('get');q.add_argument('part',choices=['ctx','conf','info']);q.add_argument('ref');options(q,get=True)
    for axis in ('evt','msg'):
        for suffix in ('id','start','end'):q.add_argument('--'+axis+'_'+suffix,type=int)
    q=se.add_parser('export');q.add_argument('part',choices=['ctx']);q.add_argument('ref');q.add_argument('path')
    q=se.add_parser('del');q.add_argument('part',choices=['ctx','conf','all']);q.add_argument('ref')
    q=se.add_parser('fork');q.add_argument('part',choices=['ctx','conf','all']);q.add_argument('ref');q.add_argument('dst')
    q=se.add_parser('rename');q.add_argument('ref');q.add_argument('dst')
    se.add_parser('list')
    for unit in ('evt','msg'):
        sub=se.add_parser(unit).add_subparsers(dest='edit_action',required=True)
        for action in (('add','edit','del') if unit=='evt' else ('add','del')):
            q=sub.add_parser(action);q.add_argument('ref')
            if action=='add':
                ag=q.add_mutually_exclusive_group(required=True);ag.add_argument('--after_msg',type=int)
                if unit=='evt':ag.add_argument('--after_evt',type=int)
                else:q.set_defaults(after_evt=None)
                q.add_argument('--content',required=unit=='evt')
            else:
                q.add_argument('--'+unit+'_id',type=int,required=True);q.add_argument('--drop-suffix',action='store_true')
                if action=='edit':q.add_argument('--content',required=True);q.add_argument('--rerun',action='store_true');options(q)
    d=top.add_parser('doctor');d.add_argument('--modelconf');d.add_argument('--websearch');d.add_argument('--samples',type=int,default=3);d.add_argument('--timeout',type=float,default=10);d.add_argument('--json',action='store_true')
    top.add_parser('self-check')
    return p

def changes(a):return {k:v for k,v in vars(a).items() if k in conf.SESSION_FIELDS}

def stdin():
    if sys.stdin.isatty():raise c.Failure('STDIN_REQUIRED','Use a finite pipe or quoted heredoc',2)
    return sys.stdin.read()

def json_stdin():
    try:return c.decode(stdin())
    except ValueError:raise c.Failure('INVALID_JSON','Invalid stdin JSON',2)

def diag_print(items,force=False):
    unique=[];seen=set()
    for x in items:
        k=c.dumps(x)
        if k not in seen:seen.add(k);unique.append(x)
    if not unique and not force:return
    print(f"[critical {sum(x['level']=='critical' for x in unique)}, warning {sum(x['level']=='warning' for x in unique)}]",file=sys.stderr)
    for x in unique:
        where=' '.join(f'{k}={v}' for k,v in x.items() if k not in ('level','code','text'))
        print(f"{x['level']}/{x['code']}: {where} {x['text']}",file=sys.stderr)

def gconf(a):
    p=conf.profile_path(a.name)
    with c.lock(c.ROOT/'locks/profiles.lock',blocking=True):
        if a.action=='del':
            if p.exists():
                selected=conf.selection().get('default_modelconf')
                with st.index_locked() as idx:
                    referenced=any((st.spath(sid)/'config.json').exists() and c.load(st.spath(sid)/'config.json').get('modelconf') in (p.stem,p.name) for sid in idx['names'].values())
                if selected in (p.stem,p.name) or referenced:raise c.Failure('PROFILE_REFERENCED','Change default/session references before deleting this profile',2)
            p.unlink(missing_ok=True);print(f'gconf/{p.stem}: deleted or already absent');return
        if a.action=='add':
            if p.exists():raise c.Failure('TARGET_EXISTS','Model config already exists',2)
            obj=json_stdin();conf.validate(obj)
            for k in ('url','model','api_key'):
                if k not in obj:raise c.Failure('MISSING_CONFIG_FIELD','Required field: '+k,2)
            obj={**copy.deepcopy(conf.DEFAULTS),**obj};c.atomic(p,obj)
        elif a.action=='set':
            obj=c.load(p);updates=changes(a);conf.validate(updates);unset=a.unset or []
            if set(unset)&set(updates):raise c.Failure('INVALID_ARGUMENT','Cannot set and unset same field',2)
            obj.update(updates)
            for k in unset:obj.pop(k,None)
            conf.validate(obj);c.atomic(p,obj)
        else:
            obj=conf.base(a.name);select=changes(a)
            if select:obj={k:obj.get(k) for k in select}
            print(json.dumps(conf.safe_view(obj),ensure_ascii=False,indent=2));return
        print(f'gconf/{p.stem}: saved')

def raw_query(s,a,diag):
    supplied=[axis for axis in ('evt','msg') if any(getattr(a,axis+'_'+part,None)is not None for part in ('id','start','end'))]
    if len(supplied)>1:raise c.Failure('QUERY_CONFLICT','Choose evt OR msg selection',2)
    for axis in supplied:
        one=getattr(a,axis+'_id');lo=getattr(a,axis+'_start');hi=getattr(a,axis+'_end')
        if one is not None and (lo is not None or hi is not None):raise c.Failure('QUERY_CONFLICT','Choose single ID OR range',2)
        if any(x is not None and x<1 for x in (one,lo,hi)) or (lo is not None and hi is not None and lo>hi):raise c.Failure('INVALID_RANGE','Positive inclusive ID range required',2)
    text=(s.path/'ctx.json').read_text(encoding='utf-8')
    if not supplied:out=text
    else:
        if s.ctx is None:raise s.ctx_error
        msgs,events=cx.select(s.ctx,a);mids={m['msg_id'] for m in msgs};eids={e['evt_id'] for e in events};lines=[]
        for line in text.splitlines():
            raw=line.removesuffix(',')
            try:o=c.decode(raw)
            except ValueError:continue
            if isinstance(o,dict) and (o.get('msg_id') in mids or o.get('evt_id') in eids):lines.append(raw)
        out='\n'.join(lines)+ ('\n' if lines else '')
        if not lines:raise c.Failure('NOT_FOUND','No ctx records matched the IDs',2)
    if len(out)>c.DISPLAY_LIMIT:raise c.Failure('DISPLAY_LIMIT',f'{len(out)} characters exceeds display limit {c.DISPLAY_LIMIT}; narrow selection or session export ctx',2)
    sys.stdout.write(out)

def management(a,diag):
    if a.command=='gconf':return gconf(a)
    if a.command=='doctor':
        import doctor
        return doctor.run_new(a)
    if a.command=='self-check':
        for p in (c.ROOT/'model').glob('*.txt'):conf.validate(c.load(p))
        with st.index_locked() as idx:
            for sid in idx['names'].values():
                if not st.spath(sid).exists():raise c.Failure('INDEX_CORRUPT','Missing indexed directory',2)
        print(f'batchcode/status: ready, version {c.VERSION}, offline check');return
    if a.action=='list':
        with st.index_locked() as idx:items=list(idx['names'].items())
        states=[(name,sid,st.active(sid)) for name,sid in items]
        for label,flag in [('Active',True),('Inactive',False)]:
            print(label+' sessions:')
            for name,sid,running in sorted(states):
                if running==flag:print(f'{name}\t{sid}')
        return
    if a.action=='add':
        obj=json_stdin() if a.heredoc else {};conf.validate(obj,True)
        sid=st.add(a.ref,obj);print(f'{a.ref}/status: created, sessionid={sid}');return
    if a.action=='evt' and a.edit_action=='edit' and a.rerun:
        if not a.drop_suffix:raise c.Failure('DROP_SUFFIX_REQUIRED','--rerun requires --drop-suffix; no edit performed',2)
        item={'session':a.ref,'edit':{'evt_id':a.evt_id,'content':a.content},'overrides':changes(a)}
        return run_batch([item],None,diag)
    create=a.action=='set';updates=changes(a)
    if create:
        conf.validate(updates,True)
        if set(a.unset or [])&set(updates):raise c.Failure('INVALID_ARGUMENT','Cannot set and unset same field',2)
    if a.action=='evt' and a.edit_action=='edit' and updates:
        raise c.Failure('INVALID_ARGUMENT','Configuration overrides on edit require --rerun',2)
    try:sid,name=st.resolve(a.ref,create=create)
    except c.Failure as ex:
        if ex.code=='NOT_FOUND' and a.action in ('get','del'):print(f'{a.ref}/status: not_found');return
        raise
    if a.action=='fork':
        dst=st.fork_batch([(sid,a.dst,a.part)])[0];print(f'{a.dst}/status: forked, sessionid={dst}, parent_id={sid}');return
    with st.session_locked(sid) as (s,name,fd):
        if a.action=='rename':st.rename(sid,a.dst);print(f'{a.dst}/status: renamed, sessionid={sid}');return
        if a.action=='export':
            p=Path(a.path).expanduser().absolute();data=(s.path/'ctx.json').read_bytes()
            with open(p,'xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
            print(f'{name}/export: {p}, bytes={len(data)}');return
        if a.action=='get':
            if a.part!='ctx' and any(getattr(a,x+'_'+y,None)is not None for x in ('evt','msg') for y in ('id','start','end')):raise c.Failure('INVALID_ARGUMENT','Context selectors require get ctx',2)
            if a.part=='ctx':
                if updates:raise c.Failure('INVALID_ARGUMENT','Config filters do not apply to ctx',2)
                raw_query(s,a,diag)
            elif a.part=='info':
                if updates:raise c.Failure('INVALID_ARGUMENT','info has no config filters',2)
                print(json.dumps({'name':name,**s.info},ensure_ascii=False,indent=2))
            else:
                choice=s.conf.get('modelconf') or conf.selection()['default_modelconf']
                try:base=conf.base(choice)
                except c.Failure:base={};diag.warning('BASE_UNAVAILABLE','Base profile unavailable; showing stored overrides')
                effective={**base,**s.conf,'modelconf':choice}
                startup_search='websearch' not in effective
                if startup_search:effective['websearch']=conf.selection().get('default_websearch')
                fields=updates or effective
                print(json.dumps({k:{'value':conf.safe_view({k:effective.get(k)})[k],'source':'session' if k in s.conf else 'startup' if (k=='websearch' and startup_search) or (k=='modelconf' and k not in s.conf) else 'modelconf/default'} for k in fields},ensure_ascii=False,indent=2))
            return
        if a.action=='set':
            unset=a.unset or []
            if set(unset)&set(updates):raise c.Failure('INVALID_ARGUMENT','Cannot set and unset same field',2)
            s.conf.update(updates)
            for k in unset:s.conf.pop(k,None)
            s.save(False);print(f'{name}/conf: saved, sessionid={sid}, fields='+','.join(sorted(set(updates)|set(unset))));return
        if a.action=='del':
            if a.part=='all':st.delete_all(sid)
            else:
                if a.part=='conf':s.conf={}
                else:s.ctx=cx.empty()
                s.save(include_ctx=a.part=='ctx')
            print(f'{name}/del: {a.part}, sessionid={sid}, artifacts retained');return
        if a.action in ('evt','msg'):
            before=(len(s.ctx['msgs']),len(s.ctx['events']))
            original_ids={e['evt_id'] for e in s.ctx['events']}
            new,target=cx.edit(s.ctx,a.action,a.edit_action,a,s.alloc)
            affected=([e['evt_id'] for e in new['events'] if e['evt_id'] not in original_ids] if a.edit_action=='add' else [a.evt_id] if a.action=='evt' else target['evt_ids'])
            s.ctx=new;s.save()
            print(f'{name}/{a.action}/{a.edit_action}: msg_id={target["msg_id"]}, evt_ids={c.dumps(affected)}, msgs_delta={len(new["msgs"])-before[0]}, evts_delta={len(new["events"])-before[1]}, sessionid={sid}')
            for m in new['msgs']:
                if not m['evt_ids']:diag.warning('EMPTY_MSG','Message has no events; ignored during compilation',msg_id=m['msg_id'])

CHILDREN=set();CHILD_LOCK=threading.Lock();CANCEL=threading.Event()

def cancel_children():
    CANCEL.set()
    with CHILD_LOCK:
        for p in CHILDREN:
            try:p.terminate()
            except OSError:pass

def build_tasks(a):
    overrides=changes(a);parallel=overrides.pop('parallel',None);conf.validate(overrides,True)
    if parallel is not None:conf.validate({'parallel':parallel})
    if a.task or a.tasks_stdin:
        if a.refs or a.content is not None or a.content_stdin or a.evt_id or a.msg_id:raise c.Failure('INPUT_CONFLICT','Do not mix batch/single/rerun inputs',2)
        if a.task and a.tasks_stdin:raise c.Failure('INPUT_CONFLICT','Choose --task or --tasks-stdin',2)
        try:items=json_stdin() if a.tasks_stdin else [c.decode(x) for x in a.task]
        except ValueError:raise c.Failure('INVALID_JSON','Invalid task object',2)
    elif len(a.refs)==2 and a.refs[0]=='rerun':
        if (a.evt_id is None)==(a.msg_id is None) or a.content is not None or a.content_stdin:raise c.Failure('RERUN_SELECTOR','rerun needs exactly one --evt_id/--msg_id and no content',2)
        items=[{'session':a.refs[1],'rerun':{'evt_id':a.evt_id,'msg_id':a.msg_id}}]
    else:
        if len(a.refs)>1 or a.evt_id is not None or a.msg_id is not None:raise c.Failure('INVALID_ARGUMENT','task [ref] or task rerun <ref>',2)
        if a.content_stdin and a.content is not None:raise c.Failure('INPUT_CONFLICT','Choose content or stdin',2)
        items=[{'session':a.refs[0] if a.refs else None,'content':stdin() if a.content_stdin else a.content}]
    if not isinstance(items,list) or not items:raise c.Failure('INVALID_TASKS','Expected nonempty task array',2)
    result=[]
    for i in items:
        if not isinstance(i,dict) or set(i)-({'session','content','fork_from','rerun'}|conf.SESSION_FIELDS-{'parallel'}):raise c.Failure('INVALID_TASK','Unknown task fields',2)
        if 'rerun' in i:
            rr=i['rerun']
            if not isinstance(rr,dict) or set(rr)-{'evt_id','msg_id'} or sum(rr.get(k)is not None for k in ('evt_id','msg_id'))!=1 or any(v is not None and (type(v)is not int or v<1) for v in rr.values()) or 'fork_from'in i or i.get('content') is not None:raise c.Failure('RERUN_SELECTOR','rerun object requires exactly one positive user ID and no content/fork',2)
        if 'rerun' not in i and (not isinstance(i.get('content'),str) or not i['content'].strip()):raise c.Failure('MISSING_CONTENT','Each task needs content',2)
        per={k:v for k,v in i.items() if k in conf.SESSION_FIELDS};conf.validate(per,True)
        item={k:v for k,v in i.items() if k not in conf.SESSION_FIELDS};item['overrides']={**overrides,**per};result.append(item)
    return result,parallel

def prepare_refs(items):
    ids=set();destnames=set();groups={}
    for item in items:
        ref=item.get('session') or 'session-'+uuid.uuid4().hex[:10]
        if not isinstance(ref,str):raise c.Failure('INVALID_REF','Session ref must be a name or ID string',2)
        item['name']=ref
        if 'fork_from' in item:
            st.valid_name(ref)
            if ref in destnames:raise c.Failure('DUPLICATE_SESSION','Duplicate target name',2)
            destnames.add(ref)
            try:
                src,_=st.resolve(item['fork_from'])
                try:st.resolve(ref)
                except c.Failure as ex:
                    if ex.code!='NOT_FOUND':raise
                else:raise c.Failure('TARGET_EXISTS','Fork target already exists',2)
                item['source_id']=src;groups.setdefault(src,[]).append(item)
            except c.Failure as ex:item['pre_error']=ex
            continue
        try:
            sid,name=st.resolve(ref);item.update(sid=sid,name=name)
        except c.Failure as ex:
            if ex.code=='NOT_FOUND' and not ('rerun'in item or 'edit'in item or st.ID_RE.fullmatch(ref)):
                st.valid_name(ref);sid='new:'+ref
            else:
                item['pre_error']=ex;sid='unresolved:'+ref
        if sid in ids or ref in destnames:raise c.Failure('DUPLICATE_SESSION','Two tasks resolve to same ID/name',2)
        ids.add(sid);destnames.add(ref)
    if set(groups)&ids:raise c.Failure('FORK_CONFLICT','Cannot run a fork source in the same batch',2)
    for item in items:
        if 'pre_error' in item:continue
        if 'fork_from'not in item and 'sid'not in item:
            try:item['sid'],item['name']=st.resolve(item['name'],create=True)
            except c.Failure as ex:item['pre_error']=ex
    for src,group in groups.items():
        try:
            generated=st.fork_batch([(src,i['name'],'all') for i in group])
            for item,sid in zip(group,generated):item['sid']=sid
        except c.Failure as ex:
            for item in group:item['pre_error']=ex


def launch(item):
    sid=item.get('sid','unresolved');diag=c.Diagnostics();start=time.monotonic();proc=None
    result={'sessionid':sid,'name':item['name'],'status':'failed','exit':1,'events':[],'artifacts':[],'diagnostics':[], 'elapsed':0,'granularity':'coarse','answer':'summary'}
    try:
        if 'pre_error'in item:raise item['pre_error']
        if CANCEL.is_set():raise c.Failure('INTERRUPTED','Batch cancelled before task started',4)
        with st.session_locked(sid) as (s,name,fd):
            result['name']=name
            overrides=item['overrides'];conf.validate(overrides,True)
            s.conf.update(overrides);s.save(False)
            with c.lock(c.ROOT/'locks/profiles.lock',shared=True,blocking=True):cfg=conf.resolve(s.conf,diag)
            result.update(granularity=cfg['granularity'],answer=cfg['answer'])
            if 'edit'in item:
                a=argparse.Namespace(**item['edit'],drop_suffix=True,rerun=True)
                candidate,target=cx.edit(s.ctx,'evt','edit',a,s.alloc)
            elif 'rerun'in item:
                select=item['rerun'];target=cx.user_target(s.ctx,eid=select.get('evt_id'),mid=select.get('msg_id'))
                if not target['evt_ids']:raise c.Failure('EMPTY_USER','Cannot rerun empty placeholder',2)
                candidate=copy.deepcopy(s.ctx);cx.cut_after(candidate,target['msg_id'])
            else:
                candidate=copy.deepcopy(s.ctx);target=cx.from_native(candidate,{'role':'user','content':item['content']},s.alloc)
            # No destructive edit/truncation committed until final config+candidate compile checks pass.
            cx.compile_ctx(candidate,cfg['provider'],diag)
            removed_msgs=len(s.ctx['msgs'])-len(candidate['msgs']);removed_evts=len(s.ctx['events'])-len(candidate['events'])
            s.ctx=candidate;s.save();mid=target['msg_id'];rid=uuid.uuid4().hex
            result.update(input_msg_id=mid,input_evt_ids=target['evt_ids'])
            if 'rerun'in item or 'edit'in item:diag.warning('HISTORY_TRUNCATED',f'Suffix permanently discarded: {removed_msgs} msgs, {removed_evts} evts; prior file side effects are not rolled back',msg_id=mid)
            with CHILD_LOCK:
                if CANCEL.is_set():raise c.Failure('INTERRUPTED','Batch cancelled before worker launch',4)
                proc=subprocess.Popen([sys.executable,str(c.ROOT/'src/worker.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,pass_fds=(fd,))
                CHILDREN.add(proc)
            try:
                out,err=proc.communicate(c.dumps({'sid':sid,'cfg':cfg,'input_mid':mid,'rid':rid}),timeout=cfg['task_timeout_seconds']+15)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:out,err=proc.communicate(timeout=3)
                except subprocess.TimeoutExpired:proc.kill();out,err=proc.communicate()
            rp=s.path/'runs'/(rid+'.json')
            if rp.exists():
                result.update(c.load(rp))
                if proc.returncode!=0 or result['status'] not in ('completed','failed','interrupted'):
                    result.update(status='interrupted',exit=4);diag.critical('WORKER_INTERRUPTED','Worker ended unexpectedly; persisted partial result recovered')
            else:raise c.Failure('WORKER_FAILED','Worker did not produce a recoverable result',4 if CANCEL.is_set() else 1)
            if CANCEL.is_set() and result['exit']==0:result.update(status='interrupted',exit=4);diag.critical('INTERRUPTED','Parent invocation cancelled')
            result['spools']=spool_result(result,sid,name)
    except c.Failure as ex:
        if ex.code!='COMPILE_FAILED' or not diag.items:diag.error(ex)
        result.update(status='interrupted' if ex.exit_code==4 else 'failed',exit=ex.exit_code,error=ex.code)
    except Exception:
        result.update(status='failed',exit=1)
        diag.critical('INTERNAL_ERROR','Task failed unexpectedly; already saved data retained')
    finally:
        if proc:
            with CHILD_LOCK:CHILDREN.discard(proc)
    result['diagnostics']=diag.items+result.get('diagnostics',[]);result['elapsed']=round(time.monotonic()-start,3)
    return result

def spool_result(r,sid,name):
    paths=[]
    for _ in range(2):
        fd,p=tempfile.mkstemp(prefix='output-',dir=c.ROOT/'state');os.close(fd);paths.append(p)
    with open(paths[0],'w',encoding='utf-8') as out,open(paths[1],'w',encoding='utf-8') as trace:
        try:ctx=c.load(st.spath(sid)/'ctx.json');_,ev=cx.indexes(ctx)
        except c.Failure:ctx=cx.empty();ev={}
        fresh=[e for e in ctx['events'] if r.get('new_evt_start',10**30)<=e['evt_id']<=r.get('evt_end',0)]
        if r['answer']=='full':
            for e in fresh:
                if e['kind']=='assistant_content' and isinstance(e['value'],str) and e['value']:print(f'{name}/evt/{e["evt_id"]}: {e["value"]}',file=out)
        else:
            answer=None
            if r.get('answer_evt') in ev:
                try:answer=c.decode(ev[r['answer_evt']]['value']['function']['arguments'])['answer']
                except (ValueError,KeyError,TypeError):pass
            elif r.get('fallback_evt') in ev:answer=ev[r['fallback_evt']]['value']
            if answer is not None:print(f'{name}/answer: {answer}',file=out)
        if r['granularity']=='fine':
            for e in fresh:
                if e['kind']=='tool_call' and isinstance(e['value'],dict):
                    call=e['value'];fn=call.get('function',{});toolname=fn.get('name','?')
                    try:args=c.decode(fn.get('arguments','{}'));brief={k:str(v)[:200] for k,v in args.items() if k in ('path','query','url','offset')}
                    except (ValueError,AttributeError):brief={}
                    if toolname=='submit_answer':brief={'answer':'[submission body hidden]'}
                    print(f'{name}/evt/{e["evt_id"]}: {toolname}: {c.dumps(brief)}',file=trace)
    return paths

def emit_spool(path,stream):
    try:
        with open(path,encoding='utf-8') as f:
            while True:
                chunk=f.read(65536)
                if not chunk:break
                stream.write(chunk)
    finally:Path(path).unlink(missing_ok=True)

def render(results,initial):
    diagnostics=initial.items+[{**x,'sessionid':r['sessionid']} for r in results for x in r['diagnostics']]
    diag_print(diagnostics,True)
    fine=any(r['granularity']=='fine' for r in results)
    print('[tool feedbacks are hidden in stderr]' if fine else 'Tool call records are hidden',file=sys.stderr)
    print(f'[task {len(results)}/{len(results)} done, max_elapsed {max(r["elapsed"] for r in results):.1f}s]')
    for r in results:
        name=r['name'];sid=r['sessionid']
        print(f'\n{name}/status: {r["status"]}, sessionid={sid}, elapsed {r["elapsed"]:.1f}s, submitted={str(r.get("submitted",False)).lower()}')
        if 'input_msg_id'in r:
            label='evt_id='+str(r['input_evt_ids'][0]) if len(r['input_evt_ids'])==1 else 'evt_ids='+c.dumps(r['input_evt_ids'])
            print(f'{name}/input: msg_id={r["input_msg_id"]}, {label}')
        if r.get('spools'):
            emit_spool(r['spools'][0],sys.stdout);emit_spool(r['spools'][1],sys.stderr)
        for artifact in r.get('artifacts',[]):print(f'{name}/artifact: {artifact}')
    codes={r['exit'] for r in results};return 0 if codes=={0} else next(iter(codes)) if len(codes)==1 else 1

def run_batch(items,parallel,diag):
    CANCEL.clear();prepare_refs(items)
    if parallel is None:
        choice=items[0]['overrides'].get('modelconf') or conf.selection()['default_modelconf']
        try:parallel=conf.base(choice)['parallel']
        except c.Failure:parallel=2  # Scheduling default only; never model/provider routing.
    def interrupt(sig,frame):cancel_children()
    old={sig:signal.signal(sig,interrupt) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:results=list(pool.map(launch,items))
    finally:
        for sig,handler in old.items():signal.signal(sig,handler)
    return render(results,diag)

def main(argv=None):
    os.umask(0o077);diag=c.Diagnostics()
    try:
        a=parser().parse_args(argv);c.init()
        with (contextlib.nullcontext() if a.command=='self-check' and os.environ.get('BATCHCODE_INSTALL_SELF_CHECK')=='1' else c.lock(c.ROOT/'locks/lifecycle.lock',shared=True)):
            if a.command=='task':
                items,parallel=build_tasks(a);return run_batch(items,parallel,diag)
            code=management(a,diag);diag_print(diag.items);return code or 0
    except c.Failure as ex:
        diag.error(ex);diag_print(diag.items);return ex.exit_code
    except (OSError,ValueError,KeyError,TypeError) as ex:
        diag.critical('LOCAL_OPERATION_FAILED',f'Operation failed ({type(ex).__name__}); inspect permissions/config/context. No secrets printed.')
        diag_print(diag.items);return 2
    except Exception as ex:
        diag.critical('INTERNAL_ERROR',f'Unexpected {type(ex).__name__}; no exception values or credentials printed')
        diag_print(diag.items);return 1
    except KeyboardInterrupt:
        cancel_children();diag.critical('INTERRUPTED','Interrupted');diag_print(diag.items);return 4

if __name__=='__main__':sys.exit(main())
