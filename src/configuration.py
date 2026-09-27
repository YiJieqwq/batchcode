"""Named model configs hold runtime defaults; session files hold explicit overrides only."""
import copy
import hashlib
import math
import re
import urllib.parse
import common as c

DEFAULTS={
 'url':'https://api.deepseek.com/v1/chat/completions','model':'deepseek-flash','api_key':'',
 'provider':'auto','thinking':'enabled','reasoning_effort':'auto','temperature':1,'top_p':1,
 'answer':'summary','granularity':'coarse','parallel':2,'stream':True,
 'task_timeout_seconds':1800,'request_timeout_seconds':90,'http_retries':1,
 'max_model_calls':0,'max_tool_calls':0,'max_context_chars':0,'max_output_tokens':0,
 'max_read_bytes':65536,'max_tool_result_chars':24000,'max_write_bytes':262144,
 'max_http_response_bytes':16777216,'max_directory_entries':200,
 'read_roots':['../inbox','./sub_workspace'],'deny_read_paths':[],
 'extract_depth':'basic','fetch_timeout_seconds':30,'allow_http_endpoints':False,
 'extra_body':{}
}
OPTIONAL={'websearch','presence_penalty','frequency_penalty'}
FIELDS=set(DEFAULTS)|OPTIONAL
SESSION_FIELDS=FIELDS|{'modelconf'}
API_PARAMS=('temperature','top_p','presence_penalty','frequency_penalty','reasoning_effort','thinking')
ZERO_FIELDS={'max_model_calls','max_tool_calls','max_context_chars','max_output_tokens','http_retries'}
ENUMS={'answer':('summary','full'),'granularity':('coarse','fine'),'thinking':('enabled','disabled','auto'),
       'extract_depth':('basic','advanced'),'provider':('auto','deepseek','openai')}

def profile_path(name,folder='model'):
    if not isinstance(name,str) or not re.fullmatch(r'[\w\-][\w.\-]{0,100}',name) or '..' in name:
        raise c.Failure('INVALID_CONFIG_NAME','Use a profile name, not a path',2)
    return c.ROOT/folder/(name if name.endswith('.txt') else name+'.txt')

def normalized(name):return profile_path(name).stem

def selection():
    p=c.ROOT/'startup/selection.json'
    return c.load(p) if p.exists() else {'default_modelconf':'deepseek-flash','default_websearch':'tavily'}

def validate(values,session=False):
    if not isinstance(values,dict) or set(values)-(SESSION_FIELDS if session else FIELDS):
        raise c.Failure('INVALID_CONFIG','Unknown configuration fields or non-object JSON',2)
    for k,v in values.items():
        if v is None and k in set(API_PARAMS)|{'websearch'}:continue
        if k in ENUMS:
            if v not in ENUMS[k]:raise c.Failure('INVALID_CONFIG',f'Invalid {k}',2)
        elif k in ('temperature','top_p','presence_penalty','frequency_penalty'):
            lo,hi={'temperature':(0,2),'top_p':(0,1),'presence_penalty':(-2,2),'frequency_penalty':(-2,2)}[k]
            if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:raise c.Failure('INVALID_CONFIG',f'Invalid {k} range [{lo},{hi}]',2)
        elif k in ('modelconf','websearch'):profile_path(v)
        elif k in ('url','model','api_key','reasoning_effort'):
            if not isinstance(v,str) or (k!='api_key' and not v):raise c.Failure('INVALID_CONFIG',f'{k} must be text',2)
        elif k in ('read_roots','deny_read_paths'):
            if not isinstance(v,list) or not all(isinstance(x,str) and x for x in v):raise c.Failure('INVALID_CONFIG',f'{k} must be a JSON string array',2)
        elif k=='extra_body':
            if not isinstance(v,dict) or set(v)&{'model','messages','tools','api_key','stream','n','tool_choice'}:
                raise c.Failure('INVALID_CONFIG','extra_body cannot override model/messages/tools/stream/auth/n',2)
        elif type(DEFAULTS.get(k)) is bool:
            if type(v) is not bool:raise c.Failure('INVALID_CONFIG',f'{k} must be true/false',2)
        elif type(DEFAULTS.get(k)) is int:
            if type(v) is not int or v<(0 if k in ZERO_FIELDS else 1):raise c.Failure('INVALID_CONFIG',f'Invalid nonnegative/positive integer: {k}',2)
    if session and 'parallel' in values:raise c.Failure('BATCH_ONLY','parallel cannot be stored in a session',2)
    if 'parallel'in values and values['parallel']>32:raise c.Failure('INVALID_CONFIG','parallel maximum is 32',2)
    if 'fetch_timeout_seconds'in values and values['fetch_timeout_seconds']>60:raise c.Failure('INVALID_CONFIG','fetch timeout maximum is 60',2)

def endpoint(url,allow_http=False):
    try:
        p=urllib.parse.urlsplit(url)
        if p.scheme not in (('http','https') if allow_http else ('https',)) or not p.hostname or p.username or p.password or p.fragment:raise ValueError()
        _=p.port
    except (ValueError,TypeError):raise c.Failure('INVALID_ENDPOINT','Expected a full HTTPS API URL without user credentials',2)

def base(name):
    obj=c.load(profile_path(name));validate(obj)
    result={**copy.deepcopy(DEFAULTS),**obj}
    # Missing connection fields must not silently select the built-in service URL/model.
    for k in ('url','model','api_key'):result[k]=obj.get(k,'')
    return result

def resolve(overrides,diag):
    validate(overrides,True)
    sel=selection();name=normalized(overrides.get('modelconf') or sel['default_modelconf'])
    b=base(name)
    cfg={**b,**overrides,'modelconf':name}
    cfg.setdefault('websearch',sel.get('default_websearch'))
    validate({k:v for k,v in cfg.items() if k!='modelconf'})
    if cfg['provider']=='auto':cfg['provider']='deepseek' if urllib.parse.urlsplit(cfg['url']).hostname=='api.deepseek.com' else 'openai'
    if not b.get('api_key','').strip():diag.warning('GLOBAL_KEY_EMPTY',f'model/{name}.txt api_key is empty; checking final session configuration')
    if not cfg['api_key'].strip():raise c.Failure('MISSING_API_KEY','Selected final model configuration has no api_key; no automatic routing',2)
    endpoint(cfg['url'],cfg['allow_http_endpoints'])
    search=None
    if cfg.get('websearch') not in (None,'none'):
        try:
            p=profile_path(cfg['websearch'],'websearch');s=c.load(p)
            if not isinstance(s,dict) or not isinstance(s.get('api_key'),str) or not s['api_key'].strip():raise c.Failure('SEARCH_UNAVAILABLE','Search key is empty',2)
            endpoint(s.get('url'),cfg['allow_http_endpoints']);endpoint(s.get('extract_url'),cfg['allow_http_endpoints'])
            if type(s.get('max_results',10)) is not int or not 1<=s.get('max_results',10)<=20:raise c.Failure('SEARCH_UNAVAILABLE','Invalid max_results',2)
            if s.get('search_depth','advanced') not in ('basic','advanced','fast','ultra-fast') or s.get('topic','general') not in ('general','news','finance'):raise c.Failure('SEARCH_UNAVAILABLE','Invalid search depth/topic',2)
            for k in ('include_images','include_raw_content'):
                if type(s.get(k,False))is not bool:raise c.Failure('SEARCH_UNAVAILABLE','Invalid boolean search field',2)
            search=s
        except c.Failure as exc:diag.warning('SEARCH_UNAVAILABLE','Selected web search configuration unavailable: '+exc.code)
    cfg['_search']=search
    return cfg

def safe_view(obj):
    if isinstance(obj,dict):return {k:('[SET]' if v else '[EMPTY]') if k=='api_key' else safe_view(v) for k,v in obj.items() if k!='_search'}
    if isinstance(obj,list):return [safe_view(v) for v in obj]
    return obj

def audit(cfg):
    view=safe_view(cfg)
    if cfg.get('_search'):view['websearch_endpoint']=cfg['_search']['url']
    # Do not store a secret-dependent hash; hash the sanitized snapshot only.
    return {'values':view,'fingerprint':'sha256:'+hashlib.sha256(c.dumps(view).encode()).hexdigest()}

def payload_options(cfg):
    out=copy.deepcopy(cfg.get('extra_body',{}))
    for k in ('max_tokens','max_completion_tokens'):out.pop(k,None)
    for k in API_PARAMS:
        if k not in cfg:continue
        v=cfg[k]
        if v is None or (k in ('thinking','reasoning_effort') and v=='auto'):out.pop(k,None)
        elif k=='thinking':
            if cfg['provider']=='deepseek':out[k]={'type':v}
            else:out.pop(k,None)
        else:out[k]=v
    if cfg['max_output_tokens']:
        out['max_tokens' if cfg['provider']=='deepseek' else 'max_completion_tokens']=cfg['max_output_tokens']
    return out
