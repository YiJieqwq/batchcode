# Configuration, providers and security

Installation `config.default.json` is a public template. install.sh copies it to runtime `config.json` only when absent. Runtime config is gitignored. Paths resolve relative to the installation, not current directory.

| Setting | Default | Meaning |
|---|---|---|
| default_model | deepseek-flash | profile filename without .txt |
| websearch | null | no network tools by default |
| granularity | coarse | tool summaries hidden; all visible model messages retained |
| parallel | 2 | workers per invocation, 1–32 |
| read_roots | ../inbox, ./sub_workspace | permitted read trees |
| deny_read_paths | [] | additional deny paths |
| task_timeout_seconds | 240 | worker model/tool deadline |
| request_timeout_seconds | 90 | HTTP socket timeout |
| max_model_calls | 16 | model rounds/task |
| max_tool_calls | 40 | tool calls/task |
| max_output_tokens | 4096 | per model response |
| max_context_chars | 180000 | serialized message character budget, not tokens |
| max_read_bytes | 65536 | read page limit, also constrained by tool result budget |
| max_tool_result_chars | 24000 | oversized results explicitly excerpted |
| max_write_bytes | 262144 | one UTF-8 file write |
| max_http_response_bytes | 4194304 | HTTP response body cap |
| max_directory_entries | 200 | listing page size |
| http_retries | 1 | additional attempts for network/429/5xx |
| extract_depth | basic | Tavily basic/advanced |
| fetch_timeout_seconds | 30 | Tavily server extraction timeout, 1–60 |
| allow_http_endpoints | false | mock-only opt-in; production use HTTPS |

Task timeout is best effort, not a strict wall-clock bound: process startup, cleanup and OS I/O may add latency. Batch queue wait is outside an individual worker's timeout. No cross-process total concurrency quota, disk quota or automatic history compaction.

## Providers

Model JSON requires `url`, `model`, `api_key`; optional `extra_body` adds provider parameters. URLs are full Chat Completions endpoints; no automatic suffix guessing. JSON duplicate keys are rejected. DeepSeek profile disables thinking by default. If enabled, reasoning fields are persisted/replayed as required by that provider but never terminal-printed. Changing config names strips provider reasoning fields; changing the contents of an existing profile is an administrator operation, not tracked as a model migration.

OpenAI profile example (requires API account access to the chosen model; not ChatGPT web subscription):

```json
{"url":"https://api.openai.com/v1/chat/completions","model":"gpt-4.1-mini","api_key":""}
```

Official DeepSeek endpoints use `max_tokens`, others `max_completion_tokens`. Other compatible services may need adaptation; no Responses API or MCP support. Additional parameters may override output budget if explicitly configured by the administrator; no arbitrary messages/tools/model/auth overrides permitted.

Tavily uses Search + Extract with separate bodies and Bearer authorization. The configured search flags do not leak into Extract calls. Both successful results and failed_results are passed to the model. Search excerpts are not equivalent to having read a full page.

## Boundary

write_file is code-enforced, not prompt-enforced: directory FDs + O_NOFOLLOW, no `..`/absolute path, atomic replace prevents changing a preexisting external hardlink target. All tool writes stay under `sub_workspace/<session>`. Program-owned config/session/log writes are separate. No shell tools.

Reads resolve real paths and enforce allowed roots plus fixed deny areas, with no-follow component opens. Profiles, logs, sessions, source, virtualenv, hidden paths and common key extensions are denied. Keep approved input trees free of secret copies/hardlinks: no filename filter can identify every secret. Avoid widening read_roots to `/` or an entire personal workspace.

This is **not OS-level sandboxing** against other same-UID processes or an administrator replacing program files/directories. Session branches isolate history and writes, not read access to all shared outputs. Malicious local processes racing filesystem topology are outside the threat model.

API calls use HTTPS by default and reject redirects to avoid moving Authorization credentials to another host. HTTP status/retry counts are stored on failures; raw error responses are deliberately not printed. Tool API failures preserve structured detail in tool history/events. Logs and history may contain private task content; protect them even though keys are redacted.

fetch_url rejects obvious nonpublic hosts/IPs, credentials and nonstandard ports before sending a URL to Tavily. Actual crawling occurs at Tavily: local checks cannot guarantee third-party redirect or DNS-rebinding behavior. Not an internal-network gateway. Never send sensitive signed URLs.

Instructional defenses mark source content untrusted, but do not constitute proof against prompt injection. No dedicated adversarial benchmark has been passed.

## References

- https://api-docs.deepseek.com/quick_start/pricing
- https://api-docs.deepseek.com/guides/thinking_mode
- https://platform.openai.com/docs/api-reference/chat/create
- https://docs.tavily.com/documentation/api-reference/endpoint/search
- https://docs.tavily.com/documentation/api-reference/endpoint/extract
