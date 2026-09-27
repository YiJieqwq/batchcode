"""Internal JSON pipe endpoint; never load credentials from task input."""
import json
import sys
from cli import worker
if __name__=='__main__':
    data=json.load(sys.stdin)
    print(json.dumps(worker(data['item'],data['cfg']),ensure_ascii=False))
