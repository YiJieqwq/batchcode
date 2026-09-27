from http.server import BaseHTTPRequestHandler
import json,time
class MockHandler(BaseHTTPRequestHandler):
    requests = []
    def log_message(self, *args):
        pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((self.path, body, self.headers.get('Authorization')))
        if self.path == '/fail':
            self.send_response(401); self.end_headers(); self.wfile.write(b'sk-secret-do-not-echo'); return
        if self.path == '/bad':
            self.send_response(200); self.end_headers(); self.wfile.write(b'bad json'); return
        if self.path == '/redirect':
            self.send_response(307); self.send_header('Location', '/chat'); self.end_headers(); return
        if self.path == '/slow':
            time.sleep(2)
        if self.path == '/slow' and 'messages' not in body:
            result = {'results': []}
        elif self.path == '/search':
            result = {'answer': '摘要', 'results': [{'url': 'https://93.184.216.34/article', 'content': '摘要正文'}]}
        elif self.path == '/extract':
            result = {'results': [{'url': body['urls'][0], 'raw_content': '网页完整正文'}], 'failed_results': []}
        else:
            msg = body['messages']
            task = next(x['content'] for x in reversed(msg) if x['role'] == 'user')
            start = max(i for i, x in enumerate(msg) if x['role'] == 'user')
            tools = [x for x in msg[start:] if x['role'] == 'tool']
            calls = []
            content = 'FINAL_OK'
            if task == 'readwrite' and not tools:
                calls = [('read_file', {'path': str(self.server.root / 'input/doc.md')})]
                content = 'VISIBLE_PROGRESS'
            elif task == 'readwrite' and len(tools) == 1:
                calls = [('write_file', {'path': 'report.md', 'content': '报告内容'})]
            elif task == 'web' and not tools:
                calls = [('web_search', {'query': 'test query'})]
            elif task == 'web' and len(tools) == 1:
                calls = [('fetch_url', {'url': 'https://93.184.216.34/article'})]
            elif task == 'loop':
                calls = [('list_directory', {'path': str(self.server.root / 'input')})]
            elif task == 'deny' and not tools:
                calls = [('write_file', {'path': '../outside.md', 'content': 'bad'})]
            elif task == 'secret':
                content = 'sk-mock-secret'
            elif task == 'history':
                content = 'HISTORY_OK' if any(x.get('content') == 'FINAL_OK' for x in msg) else 'NO_HISTORY'
            message = {'role': 'assistant', 'content': content}
            if calls:
                message['tool_calls'] = [{'id': 'call_' + str(len(msg)) + '_' + str(i), 'type': 'function',
                    'function': {'name': n, 'arguments': json.dumps(a)}} for i, (n, a) in enumerate(calls)]
                message['reasoning_content'] = 'private-reasoning-not-for-stdout'
            result = {'choices': [{'message': message, 'finish_reason': 'length' if task == 'length' else ('tool_calls' if calls else 'stop')}],
                      'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
        data = json.dumps(result).encode()
        try:
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

