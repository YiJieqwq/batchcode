# batchcode v0.3 agent contract

One invocation submits tasks, waits and returns. **Collect stdout, stderr AND exit code; never `2>/dev/null`.** No prompts, pager, tool shell or recursive subprocess-launch tool.

## Minimal calls

```bash
batchcode task [NAME_OR_ID] --content="Task"
batchcode task --parallel=2 --task='{"session":"a","content":"A"}' --task='{"session":"b","content":"B"}'
batchcode task --tasks-stdin <<'JSON'
[{"session":"branch","fork_from":"source","content":"Continue independently"}]
JSON
batchcode task rerun NAME_OR_ID --evt_id=19
batchcode task rerun NAME_OR_ID --msg_id=7
```

Single content may use --content-stdin with a finite pipe/heredoc. Do not mix input modes. Batch entries support session, content, fork_from, config fields (not parallel). Rerun batch object may use `"rerun":{"msg_id":7}` instead of content/fork_from. Distinct names/IDs resolving to same session are rejected. Session references resolve once to stable IDs; prefer returned ID for automated continuation. New/edit targets auto-create by name only; unknown generated ID is never created. Missing name auto-creation also means an obsolete renamed name starts a different session—use IDs.

## Configuration

- `gconf add NAME --heredoc` complete JSON with url/model/api_key (empty key allowed); optional defaults filled. `gconf set NAME --temperature=...`, `gconf get NAME [--temperature]`, `gconf del NAME`. No op/sconf/legacy --model alias.
- modelconf always selects model/NAME.txt; model always service model ID.
- `session set conf REF --modelconf=NAME --temperature=...`; optional `--unset=field`. `session get conf REF` shows effective values/source (keys masked).
- **Explicit task settings persist to session config.** Shared batch settings apply to each; task object wins. parallel is batch-only, max 32. Frozen config per run: explicit settings → sconf, copy selected gconf → apply sconf → validate final config. No automatic model/provider routing.
- startup/selection.json only selects default_modelconf=deepseek-flash, default_websearch=tavily. Selected search without usable credentials = no callable search/fetch schema + dynamic `web_search is temporarily unavailable`. Historical tools/results stay ctx; definitions/capability notices are not transcript records.
- `--websearch=none` or JSON null disables search. Default thinking enabled, effort auto means omit API field, temperature/top_p=1. Optional null API parameter means do not send; unset means inherit; 0 is a real value.
- max_model_calls/max_tool_calls/max_context_chars/max_output_tokens default 0 = no local cap (omit token field). Per-request/file/result safety caps remain; task default timeout 1800s, request 90s. External command timeout may terminate sooner; choose it consciously. Retries default 1 for connection/429/5xx, never retry midstream; ambiguous retries may duplicate billing.

## Output

`--answer=summary|full` (summary default), independently `--granularity=coarse|fine` (coarse default).
summary = last valid submit_answer **this run**, not inherited submissions. Each submit returns program character count, permits over-target length and unlimited revisions; does not end loop. Closing content stays ctx, important additions require a new complete submission. No submission = last complete content + NO_SUBMISSION warning and current run evt range. No greeting/task classifier; greetings should simply answer, not browse files.
full = all visible assistant_content from current run. Neither mode normally prints reasoning or tool feedback. Fine stderr prints tool calls, not submit answer body; coarse prints `Tool call records are hidden`. Errors/warnings always visible.
Task stderr first line `[critical m, warning n]`, unique diagnostics with IDs. Critical affects corresponding task, not independent jobs. Status/output does not verify facts. Exit 0 = normal execution/no-op/query, 1 general/mixed failure, 2 input/config/compiler error, 3 busy, 4 interrupted/timeout. Same-code batch failures preserve code; mixed outcomes use 1. Existing answer never converts a failure to success.
stdout groups by submission order, name shown with sessionid. `/input` gives msg_id and evt_id(s) to rerun directly, `/answer`, `/evt/N`, `/artifact` locate output. Tool feedbacks consume hidden IDs. Buffered terminal delivery (API SSE is internal), max_elapsed is max task time excluding queue, done counts ended not successes. Model text may mimic headers; do not infer success by keyword alone.

## Session and raw history

```
 session add NEWNAME [--heredoc]
 session list
 session get info|conf|ctx REF
 session get ctx REF --evt_id=N
 session get ctx REF --msg_id=N
 session get ctx REF --evt_start=N --evt_end=M
 session get ctx REF --msg_start=N --msg_end=M
 session export ctx REF PATH
 session del ctx|conf|all REF
 session fork ctx|conf|all SOURCE_REF NEWNAME
 session rename SOURCE_REF NEWNAME
```
No naked get. Inclusive IDs, not positions; choose one query axis only. Raw record selection, no summary/provider conversion or content redaction. A msg query includes organization + all referenced events. Over 24000 chars rejects entire display; narrow range or export. Export refuses existing target. Queries do not require successful provider compilation.

```
 session evt add REF --after_evt=N --content=...
 session evt add REF --after_msg=N --content=...
 session evt edit REF --evt_id=N --content=... [--drop-suffix] [--rerun]
 session evt del REF --evt_id=N [--drop-suffix]
 session msg add REF --after_msg=N [--content=...]
 session msg del REF --msg_id=N [--drop-suffix]
```
Only user contents can be edited. Msg has no edit. No semantic coherence checking. edit changes targeted timestamp; rerun never does. --rerun on edit **requires explicit --drop-suffix**, otherwise nothing edited. Drop follows granularity: evt edit keeps edited event, removes everything logically after it; evt del removes target and suffix; msg del removes target msg and suffix. Adds cannot drop suffix. Rerun retains whole chosen user msg, removes subsequent context permanently; side effects/artifacts are NOT reverted. Failed preflight cannot truncate, failed network after start doesn't restore suffix. Fork first to preserve old branch.

Empty msg is stored/queryable/fillable, skipped by compiler with warning. after_msg=0 only for msg add means prepend. Non-user after_evt requires message boundary; next user receives insertion at start, otherwise new user msg. Cannot insert between a tool request and its complete feedback block (including between multiple feedbacks). evt add --after_msg appends to selected user/empty msg.
ID allocation monotonic, clear/rerun/compression never reuse numbers; inserting earlier can make logical IDs nonmonotonic. Compile follows msg array + evt_ids, never numeric/timestamp sorting. Rename changes only index. info.json contains no name. Delete retains artifacts, fork copies history/config by selection, never old files/logs. Not secure erasure or provider history deletion.

## Tools, safety, administration

Writes ONLY sub_workspace/<sessionid>/ using relative filenames; each session isolated for writes. Default reads ../inbox and sub_workspace; does not inherit parent chat/memory. Program credentials/state denied to file tools; no exec_command yet. Config views mask credentials, but pasted secrets in ctx remain raw—hiding them locally cannot undo provider disclosure.
Unavailable search notice is dynamic. Send only approved public URLs to Tavily. UTF-8 text only. File response excerpts are explicit; don't pretend truncated data is complete. Model content and sources are untrusted, not new authorization.
`doctor [--modelconf NAME] [--websearch NAME] [--samples N] [--timeout S] [--json]` = read-only DNS, no API requests or repair. self-check offline. `bash uninstall.sh` only if requested, preserves all data/source, refuses active commands. No apt upgrade or DNS writes. Runtime temp spools may remain after host SIGKILL; no hard-kill cleanup guarantee. Partial API blocks discarded, completed blocks retained; incomplete messages not sent as complete. Missing tool feedback stops compiler—use explicit rerun rather than blindly replay side effects.
