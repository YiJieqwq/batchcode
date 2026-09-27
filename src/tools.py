"""Restricted file and Tavily tools. No shell or transcript rewriting."""
import codecs
import ipaddress
import os
from pathlib import Path
import socket
import stat
import urllib.parse
import uuid
import common as c
from common import Failure, dumps
ROOT = c.ROOT

def under(path,base):return path==base or base in path.parents

def local_path(value):
    p=Path(value).expanduser()
    return (p if p.is_absolute() else ROOT/p).resolve()

def safe_id(value):
    from storage import ID_RE
    if not ID_RE.fullmatch(value):raise Failure('INVALID_ID','Invalid ID',2)
    return value

# All tool-controlled writes are rooted by directory FDs; no symlink traversal.
def sandbox_write(relative, content, limit, session=None):
    if not isinstance(relative, str) or not relative or '\\' in relative or '\x00' in relative:
        raise Failure('INVALID_PATH', '无效文件名')
    parts = relative.split('/')
    if any(p in ('', '.', '..') for p in parts):
        raise Failure('WRITE_DENIED', '使用相对文件名，不可越界')
    if not isinstance(content, str):
        raise Failure('INVALID_ARGUMENT', 'content 必须为文本')
    data = content.encode('utf-8')
    if len(data) > limit:
        raise Failure('WRITE_TOO_LARGE', '文件超过写入大小上限')
    if session:
        parts = [safe_id(session)] + parts
    base = ROOT / 'sub_workspace'
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(base, flags)
    temp = '.tmp-' + uuid.uuid4().hex
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            newfd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = newfd
        try:
            existing = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(existing.st_mode):
                raise Failure('WRITE_DENIED', '目标不是普通文件')
        except FileNotFoundError:
            pass
        out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(out, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, parts[-1], src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        try:
            os.unlink(temp, dir_fd=fd)
        except FileNotFoundError:
            pass
        os.close(fd)
    return {'saved': relative, 'bytes': len(data)}

class Tools:
    def __init__(self, cfg, search, http, session=None):
        self.session = session
        self.cfg, self.search, self.http = cfg, search, http
        self.writes = []
        self.read_roots = [local_path(p) for p in cfg['read_roots']]
        self.denied = [ROOT / p for p in ('model', 'websearch', 'session', 'sessions', 'logs', 'locks', 'running', '.venv', 'src', 'state', 'startup')]
        self.denied += [ROOT / 'config.json', ROOT / 'session_index.json'] + [local_path(p) for p in cfg['deny_read_paths']]
        self.denied += [ROOT.parent / 'config', Path.home() / '.ssh', Path.home() / '.aws']
    def allowed(self, p):
        if not any(under(p, r) for r in self.read_roots):
            return False
        if any(under(p, d.resolve()) for d in self.denied):
            return False
        if any(s.startswith('.') for s in p.parts if s not in ('/', '.', '..')):
            return False
        return p.suffix.lower() not in ('.model', '.search', '.pem', '.key')
    def read_path(self, raw):
        if not isinstance(raw, str) or '\x00' in raw:
            raise Failure('INVALID_PATH', '无效路径')
        p = local_path(raw)
        if not self.allowed(p):
            raise Failure('READ_DENIED', '该路径不在可读范围内')
        return p
    def definitions(self):
        def definition(name, description, props, required):
            return {'type': 'function', 'function': {'name': name, 'description': description,
                'parameters': {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False}}}
        string = {'type': 'string'}
        definitions = [
            definition('read_file', '读取 UTF-8 文本文件。支持字节 offset 分段；结果会说明截断。', {'path': string, 'offset': {'type': 'integer', 'minimum': 0}}, ['path']),
            definition('list_directory', '列出允许访问的目录；可用 offset 分页。', {'path': string, 'offset': {'type': 'integer', 'minimum': 0}}, ['path']),
            definition('write_file', '保存文本成果。path 使用相对文件名，如 report.md；同名文件会被替换。', {'path': string, 'content': string}, ['path', 'content'])]
        if self.search:
            definitions += [definition('web_search', '搜索公开网页，返回来源及摘要。', {'query': string}, ['query']),
                            definition('fetch_url', '提取公开网页正文，不用于内部或私密链接。', {'url': string}, ['url'])]
        return definitions
    def execute(self, name, args):
        allowed = {d['function']['name']: d['function']['parameters'] for d in self.definitions()}
        if name not in allowed or not isinstance(args, dict):
            raise Failure('INVALID_TOOL', '未知工具或参数格式错误')
        spec = allowed[name]
        if set(args) - set(spec['properties']) or not set(spec['required']) <= set(args):
            raise Failure('INVALID_ARGUMENT', '工具参数缺失或存在未知字段')
        for k, v in args.items():
            if spec['properties'][k]['type'] == 'string' and not isinstance(v, str):
                raise Failure('INVALID_ARGUMENT', f'{k} 必须为文本')
            if k == 'offset' and (type(v) is not int or v < 0):
                raise Failure('INVALID_ARGUMENT', 'offset 必须为非负整数')
        if name == 'write_file':
            result = sandbox_write(args['path'], args['content'], self.cfg['max_write_bytes'], self.session)
            self.writes.append(str(ROOT / 'sub_workspace' / (self.session or '') / args['path']))
            return result
        if name in ('read_file', 'list_directory'):
            p = self.read_path(args['path'])
            # O_NOFOLLOW on every path component prevents symlink replacement races.
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
            try:
                for i, component in enumerate(p.parts[1:]):
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                    if i < len(p.parts[1:]) - 1 or name == 'list_directory':
                        flags |= os.O_DIRECTORY
                    nextfd = os.open(component, flags, dir_fd=fd)
                    os.close(fd)
                    fd = nextfd
                info = os.fstat(fd)
                offset = args.get('offset', 0)
                if name == 'list_directory':
                    names = sorted(n for n in os.listdir(fd) if self.allowed((p / n).resolve()))
                    entries = names[offset:offset + self.cfg['max_directory_entries']]
                    return {'entries': entries, 'next_offset': offset + len(entries), 'truncated': offset + len(entries) < len(names)}
                if not stat.S_ISREG(info.st_mode):
                    raise Failure('READ_DENIED', '只允许读取普通文本文件')
                os.lseek(fd, offset, os.SEEK_SET)
                # Keep each page below tool-result budget, even for ASCII text.
                count = self.cfg['max_read_bytes']
                data = os.read(fd, count)
                if b'\x00' in data:
                    raise Failure('UNSUPPORTED_FILE', '只支持 UTF-8 文本，不解析二进制文档')
                decoder = codecs.getincrementaldecoder('utf-8')(errors='strict')
                try:
                    text = decoder.decode(data, final=offset + len(data) >= info.st_size)
                    rest = decoder.getstate()[0]
                    if rest: data = data[:-len(rest)]
                except UnicodeError:
                    raise Failure('UNSUPPORTED_FILE', 'Invalid UTF-8 or offset inside a UTF-8 character')
                # Keep pagination accurate when the returned text needs a smaller budget.
                room = max(1, self.cfg['max_tool_result_chars'] - 256)
                while len(dumps(text)) > room:
                    text = text[:max(0, len(text)//2)]
                    if not text: break
                data = text.encode('utf-8')
                if not data and offset < info.st_size:
                    raise Failure('READ_PAGE_TOO_SMALL', 'Read/result budget cannot hold the next UTF-8 character; increase page limits')
                return {'content': text, 'offset': offset,
                        'next_offset': offset + len(data), 'truncated': offset + len(data) < info.st_size}
            finally:
                os.close(fd)
        if name == 'web_search':
            if not args['query'].strip():
                raise Failure('INVALID_ARGUMENT', 'query 不能为空')
            body = {k: v for k, v in self.search.items() if k in ('search_depth', 'max_results', 'topic', 'include_answer', 'include_raw_content', 'include_images')}
            body['query'] = args['query']
            result = self.http.post(self.search['url'], self.search['api_key'], body)
            return {k: result[k] for k in ('answer', 'results', 'images') if k in result}
        if name == 'fetch_url':
            public_url(args['url'])
            result = self.http.post(self.search['extract_url'], self.search['api_key'], {
                'urls': [args['url']], 'extract_depth': self.cfg['extract_depth'],
                'format': 'markdown', 'include_images': False, 'timeout': self.cfg['fetch_timeout_seconds']})
            return {'results': result.get('results', []), 'failed_results': result.get('failed_results', [])}

def public_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        if parsed.port not in (None, 80, 443):
            raise ValueError()
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
        if not addresses or any(not ipaddress.ip_address(a[4][0].split('%')[0]).is_global for a in addresses):
            raise ValueError()
    except (ValueError, OSError):
        raise Failure('URL_DENIED', '仅支持可解析的公开 HTTP/HTTPS 网页地址')

def bounded_result(result, limit):
    text = dumps(result)
    if len(text) <= limit:
        return text
    # Explicitly wrap excerpt instead of emitting invalid, silently cut JSON.
    return dumps({'truncated': True, 'original_chars': len(text), 'excerpt': text[:max(0, limit // 2)]})

