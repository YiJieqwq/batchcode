# Configuration and security

## Sources

startup/selection.json selects defaults only (deepseek-flash / tavily). Model JSON .txt contains API and runtime defaults. Per-session config.json contains explicit overrides only, info.json contains non-secret audit and counters, no name. Input overrides persist first, snapshot then merges from chosen modelconf; validation uses final snapshot, so session key may complete base profile's empty key. No automatic model routing.

`gconf add/set/get/del NAME`; add reads complete JSON via --heredoc; set accepts any declared field as `--field-name=value` (underscore alias supported), get uses valueless field filters. No arbitrary dict accepted as API params beyond extra_body; unknown config fields fail. Set/unset conflict fails before change. gconf del refuses currently selected or directly session-referenced profile.

`session set conf REF` requires an existing name/ID (no typo-triggered creation) and allows the same fields except parallel, plus modelconf. `task` supports these and batch parallel. Explicit task fields persist to sconf, including API overrides; passing secrets through CLI may appear in shell history/process arguments, prefer a private profile or session add --heredoc. Config get masks api_key; ctx get/export preserves raw.

Unset removes a stored override so it inherits. Missing optional field = inherit; optional API null = omit; reasoning_effort/thinking auto = omit field (not literal provider value); numeric 0 remains real. Other runtime fields require valid typed values. False is not missing. No global defaults copied into sconf.

## Defaults and CLI fields

| Field | Default | Meaning |
|---|---|---|
| url/model/api_key | DS endpoint / deepseek-flash / empty | connection credentials; no key included in release |
| provider | auto (bundled DS profile explicitly deepseek) | deepseek/openai/auto; auto identifies official DS host, else Chat Completions OpenAI adapter |
| thinking/reasoning_effort | enabled/auto | provider-dependent; auto omits API field |
| temperature/top_p | 1/1 | optional; ranges 0–2 / 0–1 |
| presence_penalty/frequency_penalty | absent | optional -2–2; DS may ignore/not support |
| answer/granularity | summary/coarse | independent stdout policy / stderr trace |
| summary_chars | 200 | suggestion and submitted feedback only, 0=no length suggestion |
| stream | true | SSE API response processing (terminal still buffered) |
| parallel | 2 | per invocation pool limit, 1–32, not per-session |
| task_timeout_seconds | 1800 | task-level deadline; external exec deadline may be earlier |
| request_timeout_seconds | 90 | socket request timeout |
| max_model_calls/max_tool_calls/max_context_chars/max_output_tokens | 0 | positive opt-in budgets; 0 bypasses local check/omits API token limit |
| max_read_bytes | 65536 | file page ceiling; actual text also bounded by result budget, valid UTF-8 boundary |
| max_tool_result_chars | 24000 | data feedback budget, explicit excerpts for oversized web data |
| max_write_bytes | 262144 | one file write safety cap |
| max_http_response_bytes | 16777216 | whole single response/stream byte cap, explicit failure not summary truncation |
| max_directory_entries | 200 | listing page |
| http_retries | 1 | connection/429/5xx; no midstream replay |
| read_roots | ../inbox, ./sub_workspace | approved source trees, relative to installation |
| deny_read_paths | [] | extra deny paths |
| extract_depth/fetch_timeout_seconds | basic/30 | Tavily depth/1–60s service extraction timeout |
| allow_http_endpoints | false | controlled local test only; HTTPS default |
| extra_body | {} | vendor fields, cannot override model/messages/tools/stream/auth/n; token caps normalized from max_output_tokens |
| websearch | absent | inherit startup choice; explicit null/none disables |

parallel's default is taken from the batch's first explicit modelconf if provided, otherwise startup's default modelconf. A missing batch-default file falls back to scheduling size 2 only; task model resolution still errors rather than routes to another model. Per-task model choices cannot create separate worker pools.

`max_tool_calls` counts ordinary tool execution, not submit_answer; successful submissions have no separate number/token limit. No imposed input budget piggybacked on a 0 context budget. Large stdin is read as text; RAM still finite, so use approved files and artifacts rather than giant command arguments. No local quota means no guarantee of unlimited provider context/output or memory.

The default profile uses actual explicit values; editing DEFAULTS in code is not configuration management. Full gconf may intentionally fix its own defaults. task scalar overrides are persisted even if final validation/API fails; destructive rerun/edit+rerun waits for valid target/config/compile preflight before cutting history.

## OpenAI profile

```bash
batchcode gconf add openai --heredoc <<'JSON'
{"url":"https://api.openai.com/v1/chat/completions","provider":"openai","model":"gpt-4.1-mini","api_key":""}
JSON
```

Requires a tool-capable API model/account, not ChatGPT website subscription. Only text Chat Completions is currently compiled. Tool calls, reasoning replay, nulls and fragments tested with mocks, actual provider behavior requires live integration. No Responses/Anthropic/multimodal compiler in this release.

## Boundaries

No shell tool; exec_command deferred. write_file uses anchored directory descriptors/O_NOFOLLOW/atomic replace, can write only sub_workspace/<ID>. Relative names, no traversal or directory symlinks. Replacing a hardlink doesn't modify external target. Absolute artifact paths are program-generated. Session rename never moves them. Fork copies references, not files; del/rerun doesn't undo filesystem effects.

File reads resolve/check approved paths and use no-follow traversal. model, websearch, session, state, startup, source, logs/locks, virtualenv, index and common credentials paths forbidden. Do not put secret copies/hardlinks in approved input trees. This is tool confinement, NOT protection from arbitrary same-UID OS processes renaming directories or modifying code. Cross-session outputs can be read if under approved shared output root; writes are isolated.

HTTP redirects rejected to protect Authorization headers. HTTP error response bodies not printed. API auth never enters messages. Bodies and stored content are NOT regex-redacted; user-pasted secrets stay raw and may already have left the device. Config/info views do not intentionally print api_key. Signed/private URLs must not be sent to Tavily. Fetch checks public addresses locally but the actual crawl is remote; cannot guarantee third-party redirect/DNS behavior. Not an internal network security gateway.

JSON/profile write defaults mode 600, private directories 700. Logs contain diagnostic metadata and references, not another authoritative full transcript. Atomic replacement and journals improve interruption recovery, not disk secure erase. state/output-* spools are ephemeral; SIGKILL/host termination may leave them behind. No total disk quota or OS sandbox is provided.

Lifecycle locks serialize installation/uninstallation against commands; installer-generated self-check runs under installer lock. One shared installation may be used by multiple CLI invocations, each with its own concurrency limit. Cooperative SIGINT/SIGTERM cancels active workers/queued tasks; hard kill cannot guarantee cleanup. Don't blindly retry a tool with an unknown interrupted side effect—inspect artifacts or rerun explicitly.


## v0.3.1 naming is not configuration

`task --name=NEW --content=...` creates; `task REF --name=NEW --content=...` renames an existing ID after successful preflight. `name` does not enter gconf/sconf/tmpconf or info.json. Batch objects distinguish `session` (existing ref) and `name` (desired label). All position/name/ID lookups are strict; only omitted task refs or explicit session add/fork create. The current display name is looked up from the index for output, even if the caller supplied an ID. Storage remains schema 1; v0.3.0 data needs no conversion.
