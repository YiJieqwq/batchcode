"""Read-only system DNS diagnosis. No repair, no public resolver selection, no API requests."""
import json
import math
import socket
import statistics
import subprocess
import sys
import time
import urllib.parse
import engine as e

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
        obj=e.load_json(path)
        for field in (('url','extract_url') if folder=='websearch' else ('url',)):
            e.endpoint(obj.get(field),cfg)
            host=urllib.parse.urlsplit(obj[field]).hostname
            if host not in hosts:hosts.append(host)
    return hosts

def run(args,cfg):
    if not 1<=args.samples<=10 or not math.isfinite(args.timeout) or not 0.1<=args.timeout<=30:
        raise e.Failure('INVALID_ARGUMENT','samples must be 1–10, timeout 0.1–30 seconds per probe',2)
    hosts=hosts_for(args,cfg)
    records=[{'host':host,**summarize([probe(host,args.timeout) for _ in range(args.samples)])} for host in hosts]
    code=1 if any(r['status']!='ok' for r in records) else 0
    report={'mode':'read-only','checks':'system DNS only','status':'warning' if code else 'ok','hosts':records,
            'notes':['No system configuration changed. No API requests or keys sent.',
                     'Uses the system resolver (including hosts/NSS/cache). Speed is not proof of answer correctness.',
                     'Median >=1s is a heuristic warning, not a diagnosis. HTTPS/proxy/provider latency is not tested.']}
    if args.json:print(json.dumps(report,ensure_ascii=False,indent=2))
    else:
        print('doctor/status: '+report['status']+', read-only system DNS')
        for r in records:
            timings=', '.join(f"{s['status']} {s['elapsed']:.3f}s" for s in r['samples'])
            print(f"doctor/host/{r['host']}: {timings}; status={r['status']}")
        for note in report['notes']:print('doctor/note: '+note)
    if code:print('DNS failed or appears slow/intermittent; inspect container/host resolver and VPN configuration. Nothing was changed.',file=sys.stderr)
    return code

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--probe':sys.exit(2)
    start=time.monotonic()
    try:
        socket.getaddrinfo(sys.argv[2],443,type=socket.SOCK_STREAM)
        print(json.dumps({'status':'ok','elapsed':round(time.monotonic()-start,4)}))
    except OSError:sys.exit(1)
