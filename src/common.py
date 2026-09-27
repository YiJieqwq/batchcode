"""Small shared primitives; no content redaction in persistence."""
import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import tempfile

VERSION = '0.3.0'
ROOT = Path(__file__).resolve().parents[1]
DISPLAY_LIMIT = 24000

class Failure(Exception):
    def __init__(self, code, text, exit_code=1, **location):
        super().__init__(text)
        self.code, self.text, self.exit_code, self.location = code, text, exit_code, location

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')

def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))

def decode(text):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out: raise ValueError('Duplicate JSON key')
            out[k]=v
        return out
    return json.loads(text, object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))

def load(path):
    try:
        if path.is_symlink(): raise Failure('UNSAFE_PATH','Symbolic link not allowed',2)
        return decode(path.read_text(encoding='utf-8'))
    except (ValueError, OSError, UnicodeError):
        raise Failure('INVALID_JSON',f'Cannot read valid JSON: {path.name}',2)

def fsync_dir(path):
    fd=os.open(path, os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

def atomic_text(path, text):
    if path.is_symlink(): raise Failure('UNSAFE_PATH','Symbolic link not allowed',2)
    fd,tmp=tempfile.mkstemp(prefix='.tmp-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path);fsync_dir(path.parent)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def atomic(path,value): atomic_text(path,dumps(value)+'\n')

@contextlib.contextmanager
def lock(path, shared=False, blocking=False):
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try: fcntl.flock(fd,(fcntl.LOCK_SH if shared else fcntl.LOCK_EX)|(0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError: raise Failure('BUSY','Object is busy; retry after current operation finishes',3)
        yield fd
    finally: os.close(fd)

def init():
    for name in ('session','sub_workspace','locks','running','state','startup','model','websearch'):
        p=ROOT/name
        if p.is_symlink(): raise Failure('UNSAFE_PATH',f'{name} must not be a symbolic link',2)
        p.mkdir(exist_ok=True,mode=0o700)

class Diagnostics:
    def __init__(self): self.items=[]; self.seen=set()
    def add(self,level,code,text,**where):
        entry={'level':level,'code':code,'text':text,**where}
        key=dumps(entry)
        if key not in self.seen:self.seen.add(key);self.items.append(entry)
    def warning(self,code,text,**where):self.add('warning',code,text,**where)
    def critical(self,code,text,**where):self.add('critical',code,text,**where)
    def error(self,exc):self.critical(exc.code,exc.text,**exc.location)
    def check(self):
        if any(x['level']=='critical' for x in self.items):
            raise Failure('COMPILE_FAILED','Context compilation failed; see located diagnostics',2)
