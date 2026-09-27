from http.server import BaseHTTPRequestHandler
import json
import time

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_obj(self,body,status=200):
        data=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        try:self.work()
        except (BrokenPipeError,ConnectionResetError):pass
    def work(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((self.path,body,self.headers.get('Authorization')))
        if self.path=='/401':self.send_obj({'error':'private-key-must-not-print'},401);return
        if self.path=='/search':self.send_obj({'results':[{'url':'https://93.184.216.34','content':'search text'}]});return
        if self.path=='/extract':self.send_obj({'results':[{'url':body['urls'][0],'raw_content':'full text'}],'failed_results':[]});return
        if self.path=='/slow':time.sleep(2)
        msgs=body['messages'];start=max(i for i,m in enumerate(msgs) if m['role']=='user');task=msgs[start]['content'].split('\n',1)[-1]
        tools=[m for m in msgs[start:] if m['role']=='tool'];n=len(tools)
        def call(name,args):return {'id':f'c{len(msgs)}','type':'function','function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}
        calls=[];text='Hello';finish='stop'
        if task in ('readwrite','report'):
            if n==0:text='VISIBLE_PROGRESS';calls=[call('read_file',{'path':str(self.server.root/'input/doc.md')})]
            elif n==1:text='UPPER_HALF';calls=[call('write_file',{'path':'report.md','content':'完整报告 sk-example'})]
            elif n==2:text='LOWER_HALF';calls=[call('submit_answer',{'answer':'FINAL_SUBMISSION'})]
            else:text='GOODBYE'
        elif task=='revise':
            if n<2:text='STEP'+str(n);calls=[call('submit_answer',{'answer':'FIRST' if n==0 else 'REVISED '+('长'*800)})]
            else:text='CLOSING'
        elif task=='invalid_submit':
            if n==0:text='first';calls=[call('submit_answer',{'answer':'VALID'})]
            elif n==1:text='bad';calls=[call('submit_answer',{'answer':''})]
            else:text='closing'
        elif task=='failafter':
            if n==0:text='work';calls=[call('submit_answer',{'answer':'BEFORE_ERROR'})]
            else:self.send_obj({'error':'upstream'},503);return
        elif task=='web':
            if n==0:text='searching';calls=[call('web_search',{'query':'test'})]
            elif n==1:text='reading';calls=[call('fetch_url',{'url':'https://93.184.216.34/'})]
            else:text='sources';calls=[call('submit_answer',{'answer':'WEB_DONE'})] if n==2 else []
        elif task=='hello' and getattr(self.server,'submit_greeting',False):
            if n==0:text='';calls=[call('submit_answer',{'answer':'GREETING_SUBMITTED'})]
            else:text='CLOSING'
        elif task=='missingfile':
            if n==0:text='read';calls=[call('read_file',{'path':str(self.server.root/'input/absent.md')})]
            else:text='FILE_ERROR_HANDLED'
        elif task=='badjson':
            if n==0:
                text='read';calls=[call('read_file',{'path':'unused'})];calls[0]['function']['arguments']='{"path":'
            else:text='ARGUMENT_ERROR_HANDLED'
        elif task=='loop':text='loop';calls=[call('list_directory',{'path':str(self.server.root/'input')})]
        elif task=='history':text='HISTORY_OK' if any(m.get('content')=='GOODBYE' for m in msgs) else 'NO_HISTORY'
        elif task=='secret':text='sk-example tvly-example'
        elif task=='length':text='truncated';finish='length'
        elif task=='tools':text=','.join(t['function']['name'] for t in body['tools'])
        if calls:finish='tool_calls'
        raw={'role':'assistant','content':text}
        if calls:raw['tool_calls']=calls;raw['reasoning_content']='PRIVATE_REASONING'
        if not body.get('stream'):
            self.send_obj({'choices':[{'index':0,'message':raw,'finish_reason':finish}],'usage':{'prompt_tokens':5,'completion_tokens':5}});return
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        def event(obj):self.wfile.write(('data: '+json.dumps(obj,ensure_ascii=False)+'\n\n').encode());self.wfile.flush()
        def delta(d,reason=None):event({'choices':[{'index':0,'delta':d,'finish_reason':reason}]})
        delta({'role':'assistant'})
        delta({'content':text[:len(text)//2]});delta({'content':text[len(text)//2:]})
        for idx,tc in enumerate(calls):
            arg=tc['function']['arguments'];cut=len(arg)//2
            delta({'tool_calls':[{'index':idx,'id':tc['id'],'type':'function','function':{'name':tc['function']['name'],'arguments':arg[:cut]}}]})
            delta({'tool_calls':[{'index':idx,'function':{'arguments':arg[cut:]}}]})
        if calls:delta({'reasoning_content':'PRIVATE_REASONING'})
        if task=='streambreak':return
        delta({},finish);event({'choices':[],'usage':{'prompt_tokens':5,'completion_tokens':5}})
        self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
