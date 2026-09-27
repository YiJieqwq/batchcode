"""Internal subprocess endpoint. stdout carries a short result-file reference, not transcript bodies."""
import json
import sys
import common as c
import storage
from runner import execute
if __name__=='__main__':
    data=json.load(sys.stdin)
    with c.lock(c.ROOT/'locks/lifecycle.lock',shared=True),storage.running_locked(data['sid']):
        r=execute(data['sid'],data['cfg'],data['input_mid'],data['rid'])
        print(c.dumps({'result_file':str(c.ROOT/'session'/data['sid']/'runs'/(r['run_id']+'.json'))}))
