#!/usr/bin/env python3
"""Batchcode public CLI. Parent aggregates isolated worker processes."""
import argparse
import concurrent.futures
import contextlib
import datetime
import fcntl
import json
import subprocess
import os
from pathlib import Path
import signal
import sys
import time
from types import SimpleNamespace
import uuid
import engine as e

class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise e.Failure('INVALID_ARGUMENT', message, 2)

SETTING_KEYS = ('model','websearch','granularity','parallel') + e.PARAMETERS

def settings(p, parallel=True):
    for name in ('temperature','top_p','presence_penalty','frequency_penalty'):
        p.add_argument('--'+name.replace('_','-'), '--'+name, dest=name, type=float)
    p.add_argument('--reasoning-effort', '--reasoning_effort', dest='reasoning_effort')
    p.add_argument('--thinking', choices=['auto','enabled','disabled'])
    p.add_argument('--model')
    p.add_argument('--websearch')
    p.add_argument('--granularity', choices=['fine','coarse'])
    if parallel: p.add_argument('--parallel', type=int)

def parser():
    p=Parser(prog='batchcode',description='One invocation, multiple agents. Collect BOTH stdout and stderr.')
    p.add_argument('--version',action='version',version=e.VERSION)
    sub=p.add_subparsers(dest='command',required=True)
    t=sub.add_parser('task',help='Run task(s), or task list')
    t.add_argument('action',nargs='?',choices=['list'])
    settings(t)
    t.add_argument('--session');t.add_argument('--content');t.add_argument('--content-stdin',action='store_true')
    t.add_argument('--task',action='append',help='Repeat a JSON object for concurrent tasks')
    t.add_argument('--tasks-stdin',action='store_true',help='Read JSON task array from stdin')
    op=sub.add_parser('op'); ops=op.add_subparsers(dest='operation',required=True)
    for name in ('delete-session','fork-session'):
        q=ops.add_parser(name);q.add_argument('--session',required=True)
        if name=='fork-session':q.add_argument('--target-session')
    q=ops.add_parser('config');q.add_argument('scope',choices=['g','s']);q.add_argument('--session')
    settings(q);q.add_argument('--unset',action='append',choices=SETTING_KEYS)
    ops.add_parser('self-check')
    d=ops.add_parser('doctor', help='Read-only DNS diagnosis; no API calls or repairs')
    d.add_argument('--model');d.add_argument('--websearch');d.add_argument('--json', action='store_true')
    d.add_argument('--samples', type=int, default=3);d.add_argument('--timeout', type=float, default=10)
    return p

def new_id():
    return datetime.datetime.now().strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]

def path(sid):return e.ROOT/'sessions'/(e.safe_id(sid)+'.json')
def exists(sid):return path(sid).exists()
def read(sid):
    p=path(sid)
    if p.is_symlink():raise e.Failure('UNSAFE_SESSION','Session file cannot be a symlink',2)
    return e.load_json(p) if p.exists() else None

def blank(sid):return {'version':e.VERSION,'session':sid,'status':'inactive','messages':[],'seq':0,'overrides':{}}

def changes(a):
    d={k:getattr(a,k) for k in SETTING_KEYS if getattr(a,k,None) is not None}
    if d.get('websearch')=='none':d['websearch']=None
    return d

def validate(d):
    e.validate_parameters(d)
    if set(d)-set(SETTING_KEYS):raise e.Failure('INVALID_CONFIG','Unknown setting',2)
    if 'parallel' in d and (type(d['parallel']) is not int or not 1<=d['parallel']<=32):raise e.Failure('INVALID_CONFIG','parallel must be 1–32',2)
    if 'granularity' in d and d['granularity'] not in ('fine','coarse'):raise e.Failure('INVALID_CONFIG','Invalid granularity',2)
    for k,folder in [('model','model'),('websearch','websearch')]:
        if k not in d or (k=='websearch' and d[k] is None):continue
        name=d[k]
        if not isinstance(name,str) or not name or '/' in name or '\\' in name or '..' in name:raise e.Failure('INVALID_CONFIG_NAME','Use a profile filename',2)
        if not name.endswith('.txt'):name+='.txt'
        p=e.ROOT/folder/name
        if p.is_symlink():raise e.Failure('INVALID_CONFIG_NAME','Profile symlinks forbidden',2)
        e.load_json(p)  # Configure without requiring a live key.

def effective(cfg,override=None):
    return {'model':cfg['default_model'],'websearch':cfg['websearch'],'granularity':cfg['granularity'],'parallel':cfg['parallel'],**{k:cfg[k] for k in e.PARAMETERS if cfg.get(k) is not None},**(override or {})}

@contextlib.contextmanager
def active(sid):
    fd=os.open(e.ROOT/'running'/(sid+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:os.close(fd)

def is_active(sid):
    p=e.ROOT/'running'/(sid+'.lock')
    if not p.exists():return False
    fd=os.open(p,os.O_RDWR|os.O_NOFOLLOW)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);return False
        except BlockingIOError:return True
    finally:os.close(fd)

def repair(messages):
    pending={}
    for m in messages:
        if m.get('role')=='assistant':
            for c in m.get('tool_calls') or []:pending[c['id']]=True
        elif m.get('role')=='tool':pending.pop(m.get('tool_call_id'),None)
    for cid in pending:messages.append({'role':'tool','tool_call_id':cid,'content':'{"error":"PREVIOUS_RUN_INTERRUPTED","message":"Result unknown; operation may have executed"}'})

def fork_many(items):
    if not items:return
    ids=sorted({x for src,dst in items for x in (src,dst)})
    with contextlib.ExitStack() as stack:
        for sid in ids:stack.enter_context(e.session_lock(sid))
        snapshots={}
        for src,dst in items:
            if src==dst or exists(dst):raise e.Failure('TARGET_EXISTS',f'Target exists: {dst}',2)
            if src not in snapshots:
                snapshots[src]=read(src)
                if snapshots[src] is None:raise e.Failure('NOT_FOUND',f'Source session not found: {src}',2)
        # Each shared source is read exactly once under the lock.
        created=[]
        try:
            for src,dst in items:
                obj=json.loads(json.dumps(snapshots[src]));obj.update(session=dst,parent=src,status='inactive')
                obj.pop('error',None);obj.pop('error_detail',None);obj.pop('artifacts',None)
                repair(obj['messages']);e.atomic_json(path(dst),obj);created.append(dst)
        except BaseException:
            for dst in created:path(dst).unlink(missing_ok=True)
            raise

def management(a,cfg):
    if a.operation=='doctor':
        import doctor
        return doctor.run(a,cfg)
    if a.operation=='self-check':
        validate(effective(cfg))
        for folder in ('model','websearch'):
            for p in (e.ROOT/folder).glob('*.txt'):e.load_json(p)
        print(f'batchcode/status: ready, version {e.VERSION}, offline check');return
    if a.operation=='config':
        if a.scope=='g' and a.session:raise e.Failure('INVALID_ARGUMENT','Global config does not take session',2)
        if a.scope=='s' and not a.session:raise e.Failure('MISSING_SESSION','Session config requires --session',2)
        d=changes(a);validate(d)
        unset=a.unset or []
        if set(d)&set(unset):raise e.Failure('INVALID_ARGUMENT','Cannot set and unset the same field',2)
        if a.scope=='s' and ('parallel' in d or 'parallel' in unset):raise e.Failure('INVALID_ARGUMENT','parallel is batch/global only',2)
        if a.scope=='g':
            with e.session_lock('_global_config'):
                obj=e.load_json(e.ROOT/'config.json')
                for k,v in d.items():obj['default_model' if k=='model' else k]=v
                for k in unset:
                    key='default_model' if k=='model' else k;obj[key]=e.DEFAULTS[key]
                if d or unset:e.atomic_json(e.ROOT/'config.json',obj)
                for k,v in effective(obj).items():print(f'global/config/{k}: {e.dumps(v)}')
        else:
            sid=e.safe_id(a.session)
            with e.session_lock(sid):
                obj=read(sid)
                if obj is None and not d and not unset:print(f'{sid}/status: not_found');return
                obj=obj or blank(sid);over=obj.setdefault('overrides',{});over.update(d)
                for k in unset:over.pop(k,None)
                if d or unset:e.atomic_json(path(sid),obj)
                for k,v in effective(cfg,over).items():print(f'{sid}/config/{k}: {e.dumps(v)}, source={"session" if k in over else "global"}')
        return
    sid=e.safe_id(a.session)
    if a.operation=='delete-session':
        with e.session_lock(sid):
            found=exists(sid)
            path(sid).unlink(missing_ok=True);(e.ROOT/'logs'/(sid+'.jsonl')).unlink(missing_ok=True)
        print(f'{sid}/status: {"deleted" if found else "not_found"}, artifacts retained');return
    target=e.safe_id(a.target_session) if a.target_session else new_id()
    fork_many([(sid,target)]);print(f'{target}/status: forked, parent {sid}')

def input_text(limit):
    if sys.stdin.isatty():raise e.Failure('STDIN_REQUIRED','Supply a pipe or heredoc, not interactive stdin',2)
    text=sys.stdin.read(limit+1)
    if len(text)>limit:raise e.Failure('INPUT_TOO_LARGE','stdin exceeds limit',2)
    return text

def tasks(a,cfg):
    if a.tasks_stdin and a.task:raise e.Failure('INVALID_ARGUMENT','Choose --task or --tasks-stdin',2)
    if (a.task or a.tasks_stdin) and (a.session or a.content is not None or a.content_stdin):raise e.Failure('INVALID_ARGUMENT','Do not mix batch and single-task arguments',2)
    try:
        if a.tasks_stdin:items=json.loads(input_text(cfg['max_context_chars']))
        elif a.task:items=[json.loads(x) for x in a.task]
        else:
            if a.content_stdin and a.content is not None:raise e.Failure('INVALID_ARGUMENT','Choose --content or --content-stdin',2)
            items=[{'session':a.session or new_id(),'content':input_text(cfg['max_context_chars']) if a.content_stdin else a.content}]
    except ValueError:raise e.Failure('INVALID_ARGUMENT','Invalid task JSON',2)
    if not isinstance(items,list) or not 1<=len(items)<=128:raise e.Failure('INVALID_ARGUMENT','Expected 1–128 tasks',2)
    shared=changes(a);validate(shared)
    ids=set()
    for item in items:
        if not isinstance(item,dict) or set(item)-({'session','content','fork_from','model','websearch','granularity'} | set(e.PARAMETERS)):raise e.Failure('INVALID_ARGUMENT','Invalid task object fields',2)
        if not isinstance(item.get('content'),str) or not item['content'].strip():raise e.Failure('MISSING_CONTENT','Each task needs nonempty content',2)
        if len(item['content'])>cfg['max_context_chars']:raise e.Failure('INPUT_TOO_LARGE','Task content exceeds limit',2)
        item['session']=e.safe_id(item['session']) if item.get('session') else new_id()
        if item['session'] in ids:raise e.Failure('DUPLICATE_SESSION','One batch cannot run the same session twice',2)
        ids.add(item['session'])
        if 'fork_from' in item:item['fork_from']=e.safe_id(item['fork_from'])
        override={k:v for k,v in item.items() if k in (('model','websearch','granularity') + e.PARAMETERS)}
        if override.get('websearch')=='none':override['websearch']=None
        validate(override);item['override']={**shared,**override}
    sources={i['fork_from'] for i in items if 'fork_from' in i}
    if sources&ids:raise e.Failure('INVALID_ARGUMENT','Fork sources cannot also be tasks/targets in the same batch',2)
    fork_many([(i['fork_from'],i['session']) for i in items if 'fork_from' in i])
    return items,shared.get('parallel',cfg['parallel'])

def deadline(signum,frame):
    raise e.Failure('TASK_TIMEOUT' if signum==signal.SIGALRM else 'INTERRUPTED','Task timed out or was interrupted',4)

def worker(item,cfg):
    os.umask(0o077);e.SECRETS.clear()
    sid=item['session'];start=time.monotonic();runner=None
    result={'session':sid,'events':[],'artifacts':[],'status':'failed','exit':1,'granularity':cfg['granularity']}
    try:
        with e.session_lock(sid),active(sid):
            obj=read(sid) or blank(sid)
            opts={**effective(cfg,obj.get('overrides',{})),**item['override']}
            result['granularity']=opts['granularity']
            # Parameters have been validated; editing a missing session creates it.
            if not exists(sid):e.atomic_json(path(sid),obj)
            mn,model=e.profile(opts['model'],'model',cfg)
            overrides={k:opts[k] for k in e.PARAMETERS if k in opts}
            model = dict(model, extra_body=e.model_body(model,overrides))
            for k in e.PARAMETERS: model.pop(k,None)
            sn,search=e.profile(opts['websearch'],'search',cfg) if opts['websearch'] else (None,None)
            args=SimpleNamespace(session=sid,granularity=opts['granularity'])
            runner=e.Runner(args,cfg,mn,model,sn,search)
            for sig in (signal.SIGALRM,signal.SIGTERM,signal.SIGINT):signal.signal(sig,deadline)
            signal.setitimer(signal.ITIMER_REAL,cfg['task_timeout_seconds'])
            try:
                runner.run(item['content'])
                result.update(status='completed',exit=0)
            except e.Failure as exc:
                signal.setitimer(signal.ITIMER_REAL,0)
                status='interrupted' if exc.exit_code==4 else 'failed'
                runner.save(status,error=exc.code,error_detail=exc.detail,artifacts=runner.tools.writes)
                runner.event('failed',code=exc.code,detail=exc.detail)
                raise
            finally:signal.setitimer(signal.ITIMER_REAL,0)
    except e.Failure as exc:result.update(status='interrupted' if exc.exit_code==4 else 'failed',exit=exc.exit_code,error=exc.code,message=e.clean(exc.message),detail=exc.detail)
    except Exception:result.update(error='INTERNAL_ERROR',message='Internal error; check config, session and filesystem permissions')
    if runner:result.update(events=runner.events,artifacts=runner.tools.writes)
    result['elapsed']=time.monotonic()-start
    return result

def launch_worker(item,cfg):
    start=time.monotonic()
    # No multiprocessing semaphores: compatible with Android proot without /dev/shm.
    proc=subprocess.Popen([sys.executable,str(e.ROOT/'src/worker.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        out,err=proc.communicate(json.dumps({'item':item,'cfg':cfg}),timeout=cfg['task_timeout_seconds']+15)
        if proc.returncode==0:return json.loads(out)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:proc.kill();proc.communicate()
        return {'session':item['session'],'events':[],'artifacts':[],'status':'interrupted','exit':4,'error':'WORKER_TIMEOUT','message':'Worker exceeded outer deadline','granularity':item['override'].get('granularity',cfg['granularity']),'elapsed':time.monotonic()-start}
    except (ValueError,OSError):pass
    return {'session':item['session'],'events':[],'artifacts':[],'status':'failed','exit':1,'error':'WORKER_FAILED','message':'Worker failed without a valid result','granularity':item['override'].get('granularity',cfg['granularity']),'elapsed':time.monotonic()-start}

def render(results):
    print(f'[task {len(results)}/{len(results)} done, max_elapsed {max(r["elapsed"] for r in results):.1f}s]')
    fine=any(r['granularity']=='fine' for r in results)
    print('[tool feedbacks are hidden in stderr]' if fine else 'Tool call records are hidden',file=sys.stderr)
    for r in results:
        sid=r['session']
        print(f'\n{sid}/status: {r["status"]}, elapsed {r["elapsed"]:.1f}s'+(f', code {r["error"]}' if 'error'in r else ''))
        for event in r['events']:
            if event['kind']=='message':print(f'{sid}/evt/{event["id"]}: {event["text"]}')
            elif event['kind']=='warning' or r['granularity']=='fine':print(f'{sid}/evt/{event["id"]}: {event["text"]}',file=sys.stderr)
        for artifact in dict.fromkeys(r['artifacts']):print(f'{sid}/artifact: {artifact}')
        if 'error' in r:print(f'{sid}/error/{r["error"]}: {r["message"]}',file=sys.stderr)
    codes={r['exit'] for r in results}
    return 0 if codes=={0} else (next(iter(codes)) if len(codes)==1 else 1)

def main():
    os.umask(0o077)
    try:
        a=parser().parse_args();cfg=e.config();e.init_dirs();validate(effective(cfg))
        if a.command=='op':return management(a,cfg) or 0
        if a.action=='list':
            if any(getattr(a,k,None) for k in ('session','content','content_stdin','task','tasks_stdin','model','websearch','granularity','parallel') + e.PARAMETERS):raise e.Failure('INVALID_ARGUMENT','task list takes no run arguments',2)
            ids=sorted(p.stem for p in (e.ROOT/'sessions').glob('*.json'))
            groups={True:[],False:[]}
            for sid in ids:groups[is_active(sid)].append(sid)
            print('Active sessions:');print('\n'.join(groups[True]),end='\n' if groups[True] else '')
            print('Inactive sessions:');print('\n'.join(groups[False]),end='\n' if groups[False] else '')
            return 0
        items,parallel=tasks(a,cfg)
        if len(items)==1:return render([worker(items[0],cfg)])
        # Workers do not write terminal streams; parent emits grouped results in submission order.
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
            futures=[pool.submit(launch_worker,i,cfg) for i in items]
            results=[f.result() for f in futures]
        return render(results)
    except e.Failure as exc:
        print(f'batchcode/status: failed, code {exc.code}')
        print(e.clean(exc.message),file=sys.stderr);return exc.exit_code
    except KeyboardInterrupt:
        print('batchcode/status: interrupted');print('Interrupted',file=sys.stderr);return 4
    except Exception:
        print('batchcode/status: failed, code INTERNAL_ERROR');print('Internal error; check configuration and filesystem permissions',file=sys.stderr);return 1

if __name__=='__main__':sys.exit(main())
