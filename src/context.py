"""Canonical shallow context, deterministic provider compiler and user-only editor."""
import copy
import common as c

KINDS={'user_content':'user','assistant_content':'assistant','reasoning_content':'assistant','tool_call':'assistant','tool':'tool'}
FIELDS={'user_content':'content','assistant_content':'content','reasoning_content':'reasoning_content'}

def empty():return {'schema_version':1,'msgs':[],'events':[]}

def serialize(ctx):
    # One organization/event record per physical line for exact raw-record queries.
    return '{"schema_version":1,"msgs":[\n'+',\n'.join(c.dumps(x) for x in ctx['msgs'])+'\n],"events":[\n'+',\n'.join(c.dumps(x) for x in ctx['events'])+'\n]}\n'

def indexes(ctx):return {m['msg_id']:m for m in ctx['msgs']},{e['evt_id']:e for e in ctx['events']}

def role(m,ev):
    roles={KINDS.get(ev[i]['kind']) for i in m['evt_ids'] if i in ev}
    if not roles:return None
    if len(roles)!=1 or None in roles:raise c.Failure('ROLE_CONFLICT','Incompatible event kinds in message',2,msg_id=m['msg_id'])
    return next(iter(roles))

def validate(ctx,diag):
    if not isinstance(ctx,dict) or ctx.get('schema_version')!=1 or not isinstance(ctx.get('msgs'),list) or not isinstance(ctx.get('events'),list):
        raise c.Failure('CTX_SCHEMA','Expected v1 msgs/events context',2)
    mi={};ev={};used=set()
    for e in ctx['events']:
        if not isinstance(e,dict) or type(e.get('evt_id')) is not int or e['evt_id']<1 or e.get('kind') not in KINDS or 'value' not in e or not isinstance(e.get('timestamp'),str) or not e['timestamp'].endswith('Z'):
            diag.critical('EVT_SCHEMA','Invalid event ID/kind/value/UTC timestamp');continue
        if e['evt_id'] in ev:diag.critical('DUPLICATE_EVT','Duplicate event ID',evt_id=e['evt_id'])
        ev[e['evt_id']]=e
    for m in ctx['msgs']:
        if not isinstance(m,dict) or type(m.get('msg_id')) is not int or m['msg_id']<1 or not isinstance(m.get('evt_ids'),list):
            diag.critical('MSG_SCHEMA','Invalid message organization');continue
        mid=m['msg_id']
        if mid in mi:diag.critical('DUPLICATE_MSG','Duplicate message ID',msg_id=mid)
        mi[mid]=m
        for i in m['evt_ids']:
            if type(i)is not int or i not in ev:diag.critical('MISSING_EVT','Message references absent event',msg_id=mid);continue
            if i in used:diag.critical('SHARED_EVT','An event must belong to exactly one message',evt_id=i)
            used.add(i)
        try:role(m,ev)
        except c.Failure as ex:diag.error(ex)
    for i in ev.keys()-used:diag.critical('ORPHAN_EVT','Unreferenced event',evt_id=i)
    diag.check()
    return mi,ev

def tool_calls(m,ev):
    return [ev[i]['value'] for i in m['evt_ids'] if ev[i]['kind']=='tool_call' and isinstance(ev[i]['value'],dict)]

def compile_ctx(ctx,provider,diag,allow_pending=False):
    _,ev=validate(ctx,diag);out=[];pending={};seen_calls=set()
    for m in ctx['msgs']:
        mid=m['msg_id']
        if not m['evt_ids']:
            diag.warning('EMPTY_MSG','Message has no events; ignored during compilation',msg_id=mid);continue
        if not m.get('complete',True):
            diag.warning('INCOMPLETE_MSG','Incomplete provider message omitted; completed blocks remain queryable',msg_id=mid);continue
        r=role(m,ev);body={'role':r};content=[];reasoning=[];calls=[];empty_calls=[];tools=[]
        fields=[]
        for i in m['evt_ids']:
            event=ev[i];k=event['kind'];v=copy.deepcopy(event['value'])
            if k in FIELDS:
                if not isinstance(v,str) and v is not None:
                    diag.critical('UNSUPPORTED_CONTENT','This adapter requires text or null; original retained',msg_id=mid,evt_id=i);continue
                field=FIELDS[k]
                if field not in fields:fields.append(field)
                (reasoning if k=='reasoning_content' else content).append((event,v))
            elif k=='tool_call':
                if 'tool_calls' not in fields:fields.append('tool_calls')
                if v is None or v==[]:empty_calls.append(v)
                elif isinstance(v,dict):
                    f=v.get('function',{})
                    if v.get('type')!='function' or not isinstance(v.get('id'),str) or not v['id'] or not isinstance(f,dict) or not isinstance(f.get('arguments'),str) or not isinstance(f.get('name'),str):
                        diag.critical('INVALID_TOOL_CALL','Malformed native tool call',msg_id=mid,evt_id=i)
                    else:calls.append({'id':v['id'],'type':'function','function':{'name':f['name'],'arguments':f['arguments']}})
                else:diag.critical('INVALID_TOOL_CALL','Invalid tool_call value',msg_id=mid,evt_id=i)
            else:tools.append((i,v))
        def text_value(parts):
            if len(parts)==1:return parts[0][1]
            if any(v is None for _,v in parts):
                diag.critical('NULL_FRAGMENT','Cannot concatenate null and other content without changing semantics',msg_id=mid);return None
            return ''.join(v for _,v in parts)
        if m.get('format','chat_completions')!='chat_completions':
            diag.critical('PROTOCOL_INCOMPATIBLE','Ordered block protocol cannot be silently flattened to Chat Completions',msg_id=mid)
        if r=='user' and content:
            value=text_value(content)
            if value is not None:value=f"[UTC {content[0][0]['timestamp']}]\n"+value
            body['content']=value
        else:
            for field in fields:
                if field=='content':body[field]=text_value(content)
                elif field=='reasoning_content':
                    if provider=='deepseek':body[field]=text_value(reasoning)
                    else:diag.warning('PROVIDER_FIELD_OMITTED','reasoning_content retained in ctx but not sent to this provider',msg_id=mid)
                else:
                    if empty_calls and (calls or len(empty_calls)>1):diag.critical('TOOL_FIELD_CONFLICT','Empty and nonempty tool_calls in same message',msg_id=mid)
                    body[field]=calls if calls else empty_calls[0] if empty_calls else []
        if r=='tool':
            if len(tools)!=1:diag.critical('TOOL_MESSAGE_SHAPE','One Chat Completions tool result per message required',msg_id=mid);continue
            i,v=tools[0]
            if not isinstance(v,dict) or not isinstance(v.get('tool_call_id'),str) or not isinstance(v.get('content'),str):
                diag.critical('INVALID_TOOL_RESULT','Tool result needs tool_call_id and text content',msg_id=mid,evt_id=i);continue
            body.update(tool_call_id=v['tool_call_id'],content=v['content'])
            if v['tool_call_id'] not in pending:diag.critical('UNPAIRED_TOOL','Feedback has no pending tool call',msg_id=mid,evt_id=i)
            else:pending.pop(v['tool_call_id'])
        else:
            if pending:diag.critical('TOOL_SEQUENCE','Message interrupts tool-call/feedback block',msg_id=mid)
            local_calls=set()
            for call in calls:
                cid=call['id']
                if cid in local_calls:diag.critical('DUPLICATE_TOOL_ID','Tool call ID repeated within one request',msg_id=mid)
                local_calls.add(cid);pending[cid]=mid
        if isinstance(m.get('native'),dict):
            for k in ('name','refusal'):
                if k in m['native']:body[k]=m['native'][k]
        out.append(body)
    if pending and not allow_pending:
        for cid,mid in pending.items():diag.critical('MISSING_TOOL_RESULT','Pending call has no feedback: '+cid,msg_id=mid)
    diag.check()
    return out,pending

def from_native(ctx,raw,alloc,complete=True):
    r=raw.get('role')
    if r not in ('user','assistant','tool'):raise c.Failure('UNSUPPORTED_ROLE','Unsupported role from provider',2)
    m={'msg_id':alloc('msg'),'evt_ids':[],'format':'chat_completions','complete':complete};ctx['msgs'].append(m)
    stamp=c.now()
    def emit(kind,value):
        event={'evt_id':alloc('evt'),'timestamp':stamp,'kind':kind,'value':copy.deepcopy(value)}
        ctx['events'].append(event);m['evt_ids'].append(event['evt_id'])
    if r=='tool':emit('tool',{k:raw[k] for k in ('tool_call_id','content') if k in raw})
    else:
        for k,v in raw.items():
            if k=='content':emit(r+'_content',v)
            elif k=='reasoning_content':
                if r!='assistant':raise c.Failure('BAD_PROVIDER_MESSAGE','Non-assistant reasoning field',2)
                emit(k,v)
            elif k=='tool_calls':
                if r!='assistant':raise c.Failure('BAD_PROVIDER_MESSAGE','Non-assistant tool calls',2)
                if isinstance(v,list) and v:
                    for call in v:emit('tool_call',call)
                else:emit('tool_call',v)
    native={k:raw[k] for k in ('name','refusal') if k in raw}
    if native:m['native']=native
    return m

def select(ctx,args):
    mi,ev=indexes(ctx)
    def test(i,typ):
        single=getattr(args,typ+'_id',None);start=getattr(args,typ+'_start',None);end=getattr(args,typ+'_end',None)
        return (single is None or i==single) and (start is None or i>=start) and (end is None or i<=end)
    axis='msg' if any(getattr(args,'msg_'+x,None)is not None for x in ('id','start','end')) else 'evt'
    if axis=='msg':
        msgs=[m for m in ctx['msgs'] if test(m['msg_id'],'msg')];ids={i for m in msgs for i in m['evt_ids']}
        return msgs,[e for e in ctx['events'] if e['evt_id'] in ids]
    return [],[e for e in ctx['events'] if test(e['evt_id'],'evt')]

def cut_after(ctx,mid,eid=None,include=False):
    mi,ev=indexes(ctx);m=mi[mid];pos=ctx['msgs'].index(m)
    if eid is None:
        ctx['msgs']=ctx['msgs'][:pos+(not include)]
    else:
        n=m['evt_ids'].index(eid);m['evt_ids']=m['evt_ids'][:n+(not include)]
        ctx['msgs']=ctx['msgs'][:pos+1]
    keep={i for x in ctx['msgs'] for i in x['evt_ids']};ctx['events']=[e for e in ctx['events'] if e['evt_id'] in keep]

def user_target(ctx,eid=None,mid=None):
    mi,ev=indexes(ctx)
    if eid is not None:
        if eid not in ev:raise c.Failure('NOT_FOUND','Event not found',2)
        if ev[eid]['kind']!='user_content':raise c.Failure('USER_ONLY','Only user events may be targeted',2)
        mid=next(m['msg_id'] for m in ctx['msgs'] if eid in m['evt_ids'])
    if mid not in mi:raise c.Failure('NOT_FOUND','Message not found',2)
    if role(mi[mid],ev) not in ('user',None):raise c.Failure('USER_ONLY','Only user messages may be targeted',2)
    return mi[mid]

def boundary(ctx,pos):
    """Refuse insertion anywhere inside a multi-call feedback section; empty msgs don't break it."""
    _,ev=indexes(ctx);pending=set()
    for m in ctx['msgs'][:pos]:
        for i in m['evt_ids']:
            e=ev[i];v=e['value']
            if e['kind']=='tool_call' and isinstance(v,dict):pending.add(v['id'])
            elif e['kind']=='tool' and isinstance(v,dict):pending.discard(v.get('tool_call_id'))
    if pending:raise c.Failure('TOOL_SEQUENCE','Cannot insert inside a tool-call/feedback block; no edit performed',2)

def edit(ctx,unit,action,args,alloc):
    ctx=copy.deepcopy(ctx);diag=c.Diagnostics();mi,ev=validate(ctx,diag)
    if getattr(args,'rerun',False) and not args.drop_suffix:raise c.Failure('DROP_SUFFIX_REQUIRED','--rerun requires --drop-suffix; nothing changed',2)
    target=None
    def new_event(m,at):
        e={'evt_id':alloc('evt'),'timestamp':c.now(),'kind':'user_content','value':args.content}
        ctx['events'].append(e);m['evt_ids'].insert(at,e['evt_id']);return e
    if action=='add':
        if unit=='msg':
            if args.after_msg==0:pos=0
            elif args.after_msg in mi:pos=ctx['msgs'].index(mi[args.after_msg])+1
            else:raise c.Failure('NOT_FOUND','Anchor message not found',2)
            boundary(ctx,pos);m={'msg_id':alloc('msg'),'evt_ids':[]}
            ctx['msgs'].insert(pos,m)
            if args.content is not None:new_event(m,0)
            target=m
        elif args.after_msg is not None:
            m=user_target(ctx,mid=args.after_msg)
            if not m['evt_ids']:boundary(ctx,ctx['msgs'].index(m))
            new_event(m,len(m['evt_ids']));target=m
        else:
            eid=args.after_evt
            if eid not in ev:raise c.Failure('NOT_FOUND','Anchor event not found',2)
            m=next(m for m in ctx['msgs'] if eid in m['evt_ids']);at=m['evt_ids'].index(eid)+1
            if ev[eid]['kind']=='user_content':new_event(m,at);target=m
            else:
                if at!=len(m['evt_ids']):raise c.Failure('MSG_BOUNDARY','Non-user anchor must be at message boundary',2)
                pos=ctx['msgs'].index(m)+1;boundary(ctx,pos)
                nxt=next((x for x in ctx['msgs'][pos:] if x['evt_ids']),None)
                if nxt and role(nxt,ev)=='user':m=nxt
                else:m={'msg_id':alloc('msg'),'evt_ids':[]};ctx['msgs'].insert(pos,m)
                new_event(m,0);target=m
    elif unit=='msg':
        m=user_target(ctx,mid=args.msg_id);target=m
        if args.drop_suffix:cut_after(ctx,m['msg_id'],include=True)
        else:
            ctx['msgs'].remove(m);ids=set(m['evt_ids']);ctx['events']=[e for e in ctx['events'] if e['evt_id'] not in ids]
    else:
        m=user_target(ctx,eid=args.evt_id);target=m
        if action=='edit':
            ev[args.evt_id]['value']=args.content;ev[args.evt_id]['timestamp']=c.now()
        if args.drop_suffix:cut_after(ctx,m['msg_id'],args.evt_id,include=action=='del')
        elif action=='del':
            m['evt_ids'].remove(args.evt_id);ctx['events']=[e for e in ctx['events'] if e['evt_id']!=args.evt_id]
    validate(ctx,c.Diagnostics())
    return ctx,target
