"""Read-only system DNS diagnosis. No repair, no public resolver selection, no API requests."""
import json
import math
import socket
import statistics
import subprocess
import sys
import time
import urllib.parse
import common as e
import configuration as conf

def probe(host,timeout):
    start=time.monotonic()
    try:
        proc=subprocess.run([sys.executable, __file__, '--probe', host],capture_output=True,text=True,timeout=timeout)
        if proc.returncode==0:return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        return {'status':'timeout','elapsed':round(time.monotonic()-start,4)}
    except (OSError,ValueError):pass
    return {'status':'failed','elapsed':round(time.monotonic()-start,4)}

def summarize(samples):
    good=[s['elapsed'] for s in samples if s['status']=='ok']
    median=statistics.median(good) if good else None
    return {'samples':samples,'successes':len(good),'median_seconds':median,
            'status':'failed' if not good else ('warning' if len(good)<len(samples) or median>=1 else 'ok')}

def hosts_for(args,cfg):
    hosts=[]
    selected=[(args.model or cfg['default_model'],'model')]
    search=args.websearch if args.websearch is not None else cfg['websearch']
    if search and search!='none':selected.append((search,'websearch'))
    for name,folder in selected:
        if not isinstance(name,str) or not name or '/' in name or '\\' in name or '..' in name:
            raise e.Failure('INVALID_CONFIG_NAME','Use a profile filename',2)
        filename=name if name.endswith('.txt') else name+'.txt'
        path=e.ROOT/folder/filename
        if path.is_symlink():raise e.Failure('INVALID_CONFIG_NAME','No profile symlinks',2)
        obj=e.load(path)
        for field in (('url','extract_url') if folder=='websearch' else ('url',)):
            conf.endpoint(obj.get(field),cfg['allow_http_endpoints'])
            host=urllib.parse.urlsplit(obj[field]).hostname
            if host not in hosts:hosts.append(host)
    return hosts

def run_new(args):
    selection=conf.selection()
    args.model=args.modelconf or selection['default_modelconf']
    obj=e.load(conf.profile_path(args.model))
    cfg={'default_model':args.model,'websearch':selection.get('default_websearch'),'allow_http_endpoints':obj.get('allow_http_endpoints',False)}
    # Diagnostics use endpoint strings only, never check credentials or call APIs.
    if not 1<=args.samples<=10 or not math.isfinite(args.timeout) or not .1<=args.timeout<=30:
        raise e.Failure('INVALID_ARGUMENT','samples 1–10; timeout .1–30',2)
    hosts=hosts_for(args,cfg)
    records=[{'host':h,**summarize([probe(h,args.timeout) for _ in range(args.samples)])} for h in hosts]
    code=int(any(r['status']!='ok' for r in records))
    print('[critical 0, warning '+str(code)+']',file=sys.stderr)
    report={'mode':'read-only','status':'warning' if code else 'ok','checks':'system DNS only','hosts':records}
    print(json.dumps(report,ensure_ascii=False,indent=2) if args.json else '\n'.join(f"doctor/{r['host']}: {r['status']}, median={r['median_seconds']}s" for r in records))
    if code:print('warning/DNS: Slow/failed system resolution; no DNS or system configuration was changed.',file=sys.stderr)
    return code

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--probe':sys.exit(2)
    start=time.monotonic()
    try:
        socket.getaddrinfo(sys.argv[2],443,type=socket.SOCK_STREAM)
        print(json.dumps({'status':'ok','elapsed':round(time.monotonic()-start,4)}))
    except OSError:sys.exit(1)


