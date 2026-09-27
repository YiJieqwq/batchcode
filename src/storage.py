"""Stable IDs, short index transactions and per-session recoverable commits."""
import contextlib
import copy
import os
import re
import shutil
import uuid
import common as c
import context as ctxmod

ID_RE=re.compile(r's_[0-9a-f]{32}')

def valid_name(name):
    if not isinstance(name,str) or not name.strip() or len(name)>128 or name!=name.strip() or name.startswith('-') or any(ord(x)<32 or ord(x)==127 for x in name) or any(x in name for x in '/\\') or ID_RE.fullmatch(name):
        raise c.Failure('INVALID_NAME','Use a nonempty display name, not a reserved ID/path/control string',2)
    return name

def spath(sid):
    if not isinstance(sid,str) or not ID_RE.fullmatch(sid):raise c.Failure('INVALID_ID','Invalid generated session ID',2)
    p=c.ROOT/'session'/sid
    if p.is_symlink():raise c.Failure('UNSAFE_PATH','Session directory must not be a symlink',2)
    return p

def new_id():
    while True:
        sid='s_'+uuid.uuid4().hex
        if not spath(sid).exists() and not (c.ROOT/'sub_workspace'/sid).exists():return sid

def blank_info(sid,parent=None):
    return {'id':sid,'parent_id':parent,'created_at':c.now(),'last_write':c.now(),'last_run_started_at':None,'last_run_finished_at':None,'status':'inactive','evt_high':0,'msg_high':0}

def check_index(obj):
    if not isinstance(obj,dict) or obj.get('schema_version')!=1 or not isinstance(obj.get('names'),dict):raise c.Failure('INDEX_CORRUPT','Invalid session index; recover explicitly from backup after inspection',2)
    ids=[]
    for name,sid in obj['names'].items():valid_name(name);spath(sid);ids.append(sid)
    if len(ids)!=len(set(ids)):raise c.Failure('INDEX_CORRUPT','Several names refer to one ID',2)

def recover_index():
    journal=c.ROOT/'state/index-transaction.json'
    if not journal.exists():return
    tx=c.load(journal);check_index(tx['index'])
    if tx['op']=='create':
        for entry in tx['entries']:
            p=spath(entry['id']);p.mkdir(exist_ok=True,mode=0o700)
            c.atomic(p/'info.json',entry['info']);c.atomic(p/'config.json',entry['conf']);c.atomic_text(p/'ctx.json',ctxmod.serialize(entry['ctx']))
    elif tx['op']=='delete':
        p=spath(tx['id'])
        if p.exists():shutil.rmtree(p)
    c.atomic(c.ROOT/'session_index.json',tx['index']);journal.unlink();c.fsync_dir(journal.parent)

def read_index():
    recover_index()
    p=c.ROOT/'session_index.json'
    if not p.exists():c.atomic(p,{'schema_version':1,'names':{}})
    obj=c.load(p);check_index(obj);return obj

@contextlib.contextmanager
def index_locked():
    with c.lock(c.ROOT/'locks/index.lock',blocking=True):yield read_index()

def transaction(index,op,**extra):
    old=c.ROOT/'session_index.json'
    if old.exists():c.atomic(c.ROOT/'state/session_index.backup.json',c.load(old))
    c.atomic(c.ROOT/'state/index-transaction.json',{'op':op,'index':index,**extra})
    recover_index()

def resolve(ref):
    """Resolve an existing name/ID only. Creation is always a separate explicit action."""
    if not isinstance(ref,str) or not ref:
        raise c.Failure('INVALID_REF','Expected a nonempty existing session name or ID',2)
    with index_locked() as idx:
        if ID_RE.fullmatch(ref):
            if ref not in idx['names'].values():raise c.Failure('NOT_FOUND','Session ID not found; no session was created',2)
            sid=ref
        elif ref in idx['names']:sid=idx['names'][ref]
        else:raise c.Failure('NOT_FOUND','Session name not found. Omit the task reference and use --name to create, or use session add. No session was created.',2)
        return sid,next(n for n,i in idx['names'].items() if i==sid)

def ensure_registered(sid):
    with index_locked() as idx:
        if sid not in idx['names'].values():raise c.Failure('NOT_FOUND','Session was removed before operation acquired its lock',2)
        if not spath(sid).is_dir():raise c.Failure('INDEX_CORRUPT','Indexed session directory missing',2)
        return next(n for n,i in idx['names'].items() if i==sid)

@contextlib.contextmanager
def session_locked(sid):
    with c.lock(c.ROOT/'locks'/(sid+'.lock')) as fd:
        name=ensure_registered(sid);s=Session(sid);yield s,name,fd

class Session:
    def __init__(self,sid):
        self.id=sid;self.path=spath(sid);self.recover()
        self.info=c.load(self.path/'info.json');self.conf=c.load(self.path/'config.json')
        self.ctx_error=None
        try:self.ctx=c.load(self.path/'ctx.json')
        except c.Failure as ex:self.ctx=None;self.ctx_error=ex
        if self.info.get('id')!=sid or 'name'in self.info:raise c.Failure('SESSION_CORRUPT','info identity mismatch/name duplication',2)
        # Inspection/export must not require a successful compiler pass.
        obj=self.ctx if isinstance(self.ctx,dict) else {}
        es=obj.get('events',[]);ms=obj.get('msgs',[])
        ev=[e.get('evt_id',0) for e in es if isinstance(e,dict)] if isinstance(es,list) else []
        mi=[m.get('msg_id',0) for m in ms if isinstance(m,dict)] if isinstance(ms,list) else []
        self.info['evt_high']=max([self.info.get('evt_high',0)]+[i for i in ev if type(i)is int])
        self.info['msg_high']=max([self.info.get('msg_high',0)]+[i for i in mi if type(i)is int])
    def recover(self):
        p=self.path/'.transaction.json'
        if p.exists():
            tx=c.load(p)
            for name,value in tx.items():
                if name not in ('info.json','config.json','ctx.json'):raise c.Failure('JOURNAL_CORRUPT','Unknown transaction member',2)
                if name=='ctx.json':c.atomic_text(self.path/name,ctxmod.serialize(value))
                else:c.atomic(self.path/name,value)
            p.unlink();c.fsync_dir(self.path)
    def alloc(self,kind):
        field=kind+'_high';self.info[field]+=1
        c.atomic(self.path/'info.json',self.info)
        return self.info[field]
    def save(self,include_ctx=True):
        self.info['last_write']=c.now()
        tx={'config.json':self.conf,'info.json':self.info}
        if include_ctx:
            if self.ctx is None:raise self.ctx_error or c.Failure('CTX_SCHEMA','Cannot save an unparsed context',2)
            tx['ctx.json']=self.ctx
        c.atomic(self.path/'.transaction.json',tx);self.recover()
    def add(self,raw,complete=True):
        m=ctxmod.from_native(self.ctx,raw,self.alloc,complete);self.save();return m
    def runpath(self,rid):
        p=self.path/'runs';p.mkdir(exist_ok=True,mode=0o700)
        return p/(rid+'.json')

def add(name,conf):
    valid_name(name)
    with index_locked() as idx:
        if name in idx['names']:raise c.Failure('TARGET_EXISTS','Session name exists',2)
        sid=new_id();idx['names'][name]=sid
        transaction(idx,'create',entries=[{'id':sid,'info':blank_info(sid),'conf':conf,'ctx':ctxmod.empty()}])
        return sid

def check_name_available(name,sid=None):
    valid_name(name)
    with index_locked() as idx:
        if name in idx['names'] and idx['names'][name]!=sid:
            raise c.Failure('TARGET_EXISTS','Target name belongs to another session; nothing was renamed',2)

def rename(sid,newname):
    valid_name(newname)
    with index_locked() as idx:
        old=next((n for n,i in idx['names'].items() if i==sid),None)
        if old is None:raise c.Failure('NOT_FOUND','Session deleted',2)
        if old==newname:return False
        if newname in idx['names']:raise c.Failure('TARGET_EXISTS','Target name exists; nothing was renamed',2)
        del idx['names'][old];idx['names'][newname]=sid;transaction(idx,'rename')
        return True

def delete_all(sid):
    with index_locked() as idx:
        idx['names']={n:i for n,i in idx['names'].items() if i!=sid}
        transaction(idx,'delete',id=sid)

def fork_batch(items):
    """Caller passes resolved source IDs; snapshots under sorted session locks, index held only for commit."""
    with contextlib.ExitStack() as stack:
        sources={sid:stack.enter_context(session_locked(sid))[0] for sid in sorted({x[0] for x in items})}
        with index_locked() as idx:
            entries=[];ids=[]
            for src,name,part in items:
                valid_name(name)
                if name in idx['names']:raise c.Failure('TARGET_EXISTS','Fork destination exists',2)
                sid=new_id();s=sources[src];info=blank_info(sid,src)
                ctx=copy.deepcopy(s.ctx) if part in ('ctx','all') else ctxmod.empty()
                conf=copy.deepcopy(s.conf) if part in ('conf','all') else {}
                if part in ('ctx','all'):info.update(evt_high=s.info['evt_high'],msg_high=s.info['msg_high'])
                idx['names'][name]=sid;ids.append(sid);entries.append({'id':sid,'info':info,'conf':conf,'ctx':ctx})
            transaction(idx,'create',entries=entries);return ids

def active(sid):
    p=c.ROOT/'running'/(sid+'.lock')
    try:
        with c.lock(p):return False
    except c.Failure as ex:
        if ex.exit_code==3:return True
        raise
