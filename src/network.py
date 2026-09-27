"""Chat Completions HTTP + SSE. Only completed blocks are persisted; no retry after stream bytes."""
import copy
import json
import time
import urllib.request
import urllib.error
import common as c

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None

class HTTP:
    def __init__(self,cfg):self.cfg=cfg;self.opener=urllib.request.build_opener(NoRedirect())
    def open(self,url,key,body):
        request=urllib.request.Request(url,c.dumps(body).encode(),{'Authorization':'Bearer '+key,'Content-Type':'application/json','User-Agent':'batchcode/'+c.VERSION},method='POST')
        for n in range(self.cfg['http_retries']+1):
            try:return self.opener.open(request,timeout=self.cfg['request_timeout_seconds'])
            except urllib.error.HTTPError as ex:
                status=ex.code;ex.close()
                if status!=429 and not 500<=status<600 or n==self.cfg['http_retries']:
                    raise c.Failure('API_HTTP_ERROR',f'API HTTP {status}; response omitted',http_status=status,retries=n,attempts=n+1)
            except (urllib.error.URLError,OSError,TimeoutError):
                if n==self.cfg['http_retries']:raise c.Failure('API_NETWORK_ERROR','Connection failed or timed out',retries=n)
            time.sleep(min(2**n,8))
    def post(self,url,key,body):
        with self.open(url,key,body) as response:
            data=response.read(self.cfg['max_http_response_bytes']+1)
        if len(data)>self.cfg['max_http_response_bytes']:raise c.Failure('HTTP_SIZE_LIMIT','HTTP response exceeded explicit per-response safety limit')
        try:
            obj=c.decode(data.decode('utf-8'))
            if not isinstance(obj,dict):raise ValueError()
            return obj
        except (ValueError,UnicodeError):raise c.Failure('API_PROTOCOL_ERROR','Invalid JSON response')

class Assembler:
    def __init__(self,session):
        self.s=session;self.blocks=[];self.current=None;self.calls={};self.stamp=c.now()
        self.msg={'msg_id':session.alloc('msg'),'evt_ids':[],'format':'chat_completions','complete':False}
        session.ctx['msgs'].append(self.msg)
    def block(self,kind,key=None):
        b={'evt_id':self.s.alloc('evt'),'timestamp':c.now(),'kind':kind,'value':'' if kind!='tool_call' else {'id':'','type':'function','function':{'name':'','arguments':''}},'_key':key,'_done':False}
        self.blocks.append(b);self.msg['evt_ids'].append(b['evt_id']);return b
    def finish_text(self):
        if self.current is not None:
            self.current['_done']=True;self.current=None;self.persist()
    def feed(self,delta):
        # Decoder retains source JSON field occurrence order, never sorts by kind.
        for field,v in delta.items():
            if field in ('content','reasoning_content'):
                if v is None:continue  # Streaming null deltas carry no text block.
                if not isinstance(v,str):raise c.Failure('API_PROTOCOL_ERROR','Non-text streaming delta')
                kind='assistant_content' if field=='content' else field
                if self.current is None or self.current['kind']!=kind:
                    self.finish_text();self.current=self.block(kind)
                self.current['value']+=v
            elif field=='tool_calls':
                self.finish_text()
                if v is None or v==[]:
                    b=self.block('tool_call');b['value']=v;b['_done']=True;self.persist();continue
                for fragment in v:
                    index=fragment.get('index')
                    if type(index)is not int or index<0:raise c.Failure('API_PROTOCOL_ERROR','Missing stream tool index')
                    if index not in self.calls:self.calls[index]=self.block('tool_call',index)
                    b=self.calls[index];call=b['value']
                    for name in ('id','type'):
                        if fragment.get(name):
                            if name=='id':call[name]+=fragment[name]
                            else:call[name]=fragment[name]
                    f=fragment.get('function',{})
                    for name in ('name','arguments'):
                        if name in f:
                            if not isinstance(f[name],str):raise c.Failure('API_PROTOCOL_ERROR','Invalid tool delta')
                            call['function'][name]+=f[name]
            elif field in ('name','refusal') and v is not None:
                self.msg.setdefault('native',{})[field]=self.msg.get('native',{}).get(field,'')+v
    def persist(self):
        ids={b['evt_id'] for b in self.blocks}
        self.s.ctx['events']=[e for e in self.s.ctx['events'] if e['evt_id'] not in ids]+[{k:v for k,v in b.items() if not k.startswith('_')} for b in self.blocks if b['_done']]
        # Pending block IDs are not dangling persisted references.
        self.msg['evt_ids']=[b['evt_id'] for b in self.blocks if b['_done']]
        self.s.save()
    def finish(self):
        self.finish_text()
        for b in self.blocks:b['_done']=True
        self.persist();self.msg['complete']=True;self.s.save()
        return self.msg
    def abort(self):
        self.current=None
        self.persist()  # Completed blocks remain, partial fragments are deliberately discarded.

def model_call(http,cfg,payload,s):
    if not cfg['stream']:
        obj=http.post(cfg['url'],cfg['api_key'],payload)
        try:
            choice=obj['choices'][0];raw=choice['message'];reason=choice['finish_reason']
            if raw.get('role')!='assistant':raise ValueError()
        except (KeyError,IndexError,TypeError,ValueError):raise c.Failure('API_PROTOCOL_ERROR','Malformed Chat Completions response')
        if reason not in ('stop','tool_calls'):
            # Nonstreaming gives no trustworthy internal block-end markers on truncation.
            # Do not save a truncated content/tool-call as complete or make it a fallback.
            s.add({'role':'assistant'},complete=False)
            raise c.Failure('MODEL_INCOMPLETE','Model did not finish normally: '+str(reason))
        m=s.add(raw,complete=True)
        return m,obj.get('usage',{})
    a=None;finished=None;usage={};size=0;buffer=[]
    try:
        with http.open(cfg['url'],cfg['api_key'],payload) as response:
            while True:
                line=response.readline(cfg['max_http_response_bytes']+1)
                if not line:break
                size+=len(line)
                if size>cfg['max_http_response_bytes']:raise c.Failure('HTTP_SIZE_LIMIT','Streaming response exceeded explicit per-response safety limit')
                try:line=line.decode('utf-8').rstrip('\r\n')
                except UnicodeError:raise c.Failure('API_PROTOCOL_ERROR','Invalid UTF-8 SSE')
                if line.startswith('data:'):buffer.append(line[5:].lstrip())
                if line or not buffer:continue
                text='\n'.join(buffer);buffer=[]
                if text=='[DONE]':break
                try:obj=c.decode(text)
                except ValueError:raise c.Failure('API_PROTOCOL_ERROR','Invalid SSE JSON')
                if obj.get('usage'):usage=obj['usage']
                for choice in obj.get('choices',[]):
                    if choice.get('index',0)!=0:raise c.Failure('API_PROTOCOL_ERROR','Multiple completions unsupported')
                    delta=choice.get('delta',{})
                    if delta:
                        if a is None:a=Assembler(s)
                        a.feed(delta)
                    if choice.get('finish_reason') is not None:
                        finished=choice['finish_reason']
                        if finished in ('stop','tool_calls'):
                            if a is None:a=Assembler(s)
                            a.finish()
                        else:raise c.Failure('MODEL_INCOMPLETE','Model output incomplete: '+str(finished))
        if finished not in ('stop','tool_calls') or a is None:raise c.Failure('STREAM_INTERRUPTED','Stream ended before completion')
        return a.msg,usage
    except (OSError,TimeoutError,urllib.error.URLError):
        if a:a.abort()
        raise c.Failure('STREAM_INTERRUPTED','Network stream interrupted; partial blocks discarded')
    except BaseException:
        if a and not a.msg.get('complete'):a.abort()
        raise
