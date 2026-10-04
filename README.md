# batchcode

**English** | [中文](README.zh-CN.md)

**One call, many agents.** A lightweight task CLI for terminal users and AI agents: session branching and concurrency, editable context, provider request compilation, and explicit final-answer submission.

**Current version: v0.3.3** (keeps v0.3.x session storage; the install step cleans up deprecated configuration and is not compatible with the 0.2.x CLI/session format). Python 3.10+ standard library only, with no third-party pip dependencies; supports Debian/Ubuntu (including proot), and does not support native Termux or Windows.

## Installation

Download the ZIP from [Releases](https://github.com/YiJieqwq/batchcode/releases):

```bash
unzip batchcode-v0.3.3.zip
cd batchcode
bash install.sh
```

Or clone the repository and run the install script. The installer prepares a local `.venv`, registers the PATH command, and runs an offline self-check; you never activate the venv by hand. It installs only the necessary system dependencies, never runs an upgrade, and refuses package transactions that involve coreutils. Registering the PATH entry requires a writable `/usr/local/bin` or `~/.local/bin` that is already on PATH; without permission it fails explicitly rather than waiting for a password. Embedded or test use can run `bash install.sh --local`.

Fill in `api_key` in two **JSON-format `.txt` files**:

```text
model/deepseek-flash.txt
websearch/tavily.txt
```

A missing search key does not stop the model from running: when the search tool is unavailable its schema is not injected, but sub-agents receive the dynamic hint `web_search is temporarily unavailable`. The model must have a key in the **merged effective configuration**; the model or provider is never switched automatically. This only checks local call conditions — a non-empty key does not guarantee that remote authentication will succeed.

> Do not unzip the ZIP over a directory whose keys are already filled in. The install script preserves keys and custom settings, but an unzip tool may overwrite same-named `.txt` files. This version does not migrate 0.2.x sessions and does not delete old data. Install into a new directory; the default profile is a public sample with an empty key, so do not commit to Git after filling in your key.

### Updating from an older v0.3.x

No ctx conversion is needed. Prepare the new code, keep or migrate your own model and session configuration, then run `bash install.sh`: while holding the lifecycle lock, the installer **backs up first and then removes the deprecated answer-length configuration fields**, leaving keys, other fields, the original ctx, and the historical audit untouched. Backups live in the private `state/config-backup-*/` and contain the original configuration — do not upload them. Re-running the installer will not repeatedly rewrite an already cleaned file. If you migrate an old configuration after installing, run the install script once more.

This deletes the old field rather than continuing to offer a compatibility parameter; answer-length targets are no longer exposed in the CLI, the current configuration view, request prompts, or new submission feedback. Existing historical tool feedback stays as it is — old conversations are not rewritten for the sake of an upgrade.

During the exclusive lifecycle lock the installer also cleans up **orphan session locks** left by older versions: it only deletes empty regular lock files whose ID is no longer in the index and for which `session/<id>` does not exist either. Only generated ID filenames are handled; the global lock, locks of existing sessions, and artifact directories are preserved. Busy locks, symlinks, hard links, and non-empty or otherwise unusual files are skipped with a notice rather than force-deleted as garbage. Re-running the installer is safe.

## Finishing a Task in One Call

```bash
batchcode task --name=research --content="Summarise /workspace/inbox/doc.md"
batchcode task research --content="Verify the conclusion and cite sources"

batchcode task --parallel=2 \
  --task='{"name":"tech","content":"Analyse technical feasibility"}' \
  --task='{"name":"cost","content":"Analyse cost and risk"}'

batchcode task --tasks-stdin <<'JSON'
[
  {"name":"supporting-evidence","fork_from":"research","content":"Check the supporting evidence"},
  {"name":"counter-check","fork_from":"research","content":"Check the counter-evidence"}
]
JSON
```

**A positional argument only references an existing session; a wrong name or ID reports `NOT_FOUND` directly and never auto-creates or fuzzy-matches.** A new session is created only when no reference is given: use `--name=<name>` to name it synchronously, or omit `name` to have a display name generated automatically.

```bash
# Create and name (a duplicate name is an error — it will not silently continue another session)
batchcode task --name=research --content="First-round task"
# Reference an existing session and continue the task
batchcode task research --content="Continue verifying"
# Reference an existing session and rename it at the same time
batchcode task research --name=literature-review --content="Continue verifying"
# An ID also works as a reference; output still uses the mapped name
batchcode task s_0123456789abcdef0123456789abcdef --name=new-name --content="Continue"
```

`--name` is not a configuration item and does not enter sconf or info.json. A rename only updates the index; the ID, history, and artifact paths stay as they are. On a duplicate name, a busy session, or a failed run pre-check, the rename does not happen. Once the pre-check passes, the rename happens before the run; a remote API failure does not roll back a rename that already succeeded. Renaming a session to its own current name is a no-op. `task rerun REF --name=<new-name> --msg_id=N` follows the same rules.

In batch objects, `session` is only for referencing an existing session while `name` is for naming a new one or renaming while continuing. Do not put a batch-wide `--name` on the command; write `name` inside each object. `fork_from` is an explicit new branch: omit `session` and use `name` to give the new branch its name — the session is no longer treated as the target name.

Every existing reference accepts either a **name or a generated sessionid** (for example `s_` followed by a 32-hex-digit UUID). Explicit `session add NAME` and `session fork ... NEWNAME` can still create sessions, but a target cannot specify its own ID.

Batch forks from the same source take a single snapshot; different sessions run concurrently while the same session must run serially. A name and an ID pointing at the same session also count as a duplicate. A local configuration or execution failure inside a batch does not cancel other independent tasks; input-structure errors or duplicate batch IDs are rejected before execution.

## Output: Answers and Traces Are Two Axes

```bash
batchcode task research --answer=summary --granularity=fine --content="Review the material"
```

**`submit_answer` is always available in both answer modes, with the same delivery requirement**: when the task is done, can no longer be completed with no further action, or there is no task and no further action, it must be submitted at least once — greetings and tests included; unrelated file or search operations must not be performed merely to submit. Repeated revision is allowed, and the last valid submission in the run is the one that counts; after submitting, the run wraps up normally.

The shared system instruction requires that the **`answer` field contain only the answer body itself**, without extra wrapper tags, XML wrapping, function-call-style markers, or end-of-call markers. XML/HTML/code explicitly requested by the user is part of the answer body and is still allowed. The program does not strip tags from the answer with regular expressions or rewrite it, so raw-text queries and character counts stay truthful; prompt constraints cannot guarantee that a model never violates them.

- **`--answer=summary` (default)**: stdout shows only the final `/answer` plus program status/artifacts, and does not echo intermediate visible statements back.
- **`--answer=full`**: stdout shows every visible `assistant_content` from the run, **and then shows the final `/answer` as well**. It is not "show only the process while hiding the submitted answer". Reasoning and tool-feedback bodies are not printed; an explicit ctx query can inspect the raw events.
- **Answer length is specified in the task body**: for example `--content="Summarise in three sentences ..."`. When the user does not mention a word or length target, sub-agents are left to answer briefly on their own while keeping the necessary information. The program has no separate answer-length target parameter, does not hard-truncate, and does not cap cumulative submission length.
- Every submission feedback includes the actual `chars` (Python character count, including punctuation, English, spaces, and newlines), **with no target-length field**. The model decides whether to revise based on the user's body text; the program does not parse the user's text to manufacture a second hidden limit.
- **`--granularity=coarse` (default)**: stderr shows no tool-call summaries and reports `Tool call records are hidden`.
- **`--granularity=fine`**: stderr shows call summaries (submit argument bodies are still hidden); tool-feedback bodies are not shown.
- If the run has no valid submission, both modes fall back to the **last complete content of the run**, marked with `/answer` (in `full` its original `/evt` is kept too), and stderr reports `NO_SUBMISSION` along with the run's evt start/end IDs. This is an exceptional fallback for when the model forgets to submit, and greetings are no longer designed as a routine fallback path; the program does not semantically classify and declare failure. Prompts cannot guarantee that a model never forgets to submit, so the warning remains. Submissions inherited from history/forks do not count for the current run.
- Errors and warnings are always printed. An existing answer cannot mask a timeout or failure; status and exit codes are returned as they are.

Example stdout:

```text
[task 2/2 done, max_elapsed 7.3s]

research/status: completed, sessionid=s_..., elapsed 7.3s, submitted=true
research/input: msg_id=7, evt_id=19
research/answer: Conclusion ... necessary limits and sources ...
research/artifact: /install-dir/sub_workspace/s_.../report.md

verify/status: completed, sessionid=s_..., elapsed 6.2s, submitted=false
verify/input: msg_id=1, evt_id=1
verify/answer: A direct reply ...
```

`full` also keeps the process and the closing remarks before `/answer`, for example:

```text
research/evt/20: I will read the specified material first.
research/evt/26: Verification complete.
research/answer: The final submitted conclusion ...
```

Even when the last visible statement is just "done", `/answer` still comes from the last valid submission rather than treating the closing remark as the answer. If a timeout or failure happens after submission, the existing answer can still be returned, but the status will not be dressed up as success.

Example stderr:

```text
[critical 0, warning 1]
warning/NO_SUBMISSION: session=verify Returned last complete content; evt_start=1, evt_end=2
[tool feedbacks are hidden in stderr]
research/evt/21: read_file: {"path":"/workspace/inbox/doc.md"}
```

**Output prefixes use the session name, not the long ID**: even when the input uses an ID, answers and tool traces are still located by the current name. Session location in diagnostics also shows the name; the status line keeps one stable sessionid, and IDs remain visible in list and info.

**You must collect stdout, stderr, and the exit code; `2>/dev/null` is forbidden.** Model text can imitate status headers, so do not judge success by keywords across the whole output. `done` is a completion count, not a success count; `max_elapsed` is the longest single-task duration and does not include queue waiting. The factual accuracy of the model is not guaranteed by `completed`.

Results are summarised in submission order after the tasks finish, not as a live terminal stream. Full output is delivered through a local temporary file, so parent and child processes do not copy all bodies through pipes. API streaming and terminal output granularity are independent of each other.

## Configuration: gconf Defaults + Session Overrides

```bash
batchcode gconf get deepseek-flash
batchcode gconf get deepseek-flash --temperature --top-p
batchcode gconf set deepseek-flash --temperature=0.8
batchcode gconf add research --heredoc <<'JSON'
{
  "url":"https://api.deepseek.com/v1/chat/completions",
  "model":"deepseek-flash",
  "api_key":""
}
JSON
batchcode gconf del research

batchcode session set conf research --modelconf=deepseek-flash --temperature=0.6
batchcode session set conf research --unset=temperature
batchcode session get conf research --temperature --modelconf
```

- `modelconf` is always the configuration name; `model` is always the server-side model ID.
- Each `model/*.txt` provides connection, sampling, and runtime defaults at the same time; `add --heredoc` reads complete JSON, fills in optional defaults, and refuses to overwrite an existing entry. The url/model/api_key fields are required, but api_key may be empty.
- **Explicit `task` parameters are written back to that session's conf** and are no longer one-off temporary settings. Only explicit overrides are stored; inherited values are not frozen in. Batch-wide settings are written to each session, with per-task settings taking precedence; `parallel` is a batch-only parameter and is not written to individual sessions.
- Run flow: explicit parameters override sconf → gconf is copied into an in-memory tmpconf based on modelconf → fields present in sconf override item by item → the final tmpconf is checked → this run's snapshot is fixed. Changing gconf afterwards does not affect a running task.
- If the base gconf lacks a key but a session override supplies it, the task can still run; stderr reports the missing key in the base. If the final configuration still lacks a key, the task fails, with no automatic routing.
- Normal configuration views hide api_key, while **ctx, tool arguments, feedback, and artifact bodies are not redacted with regular expressions**; auth headers are never injected into the conversation.
- `get --temperature` is a field filter and does not accept an assignment such as `--temperature=...`.
- Deleting a gconf that is still directly referenced by the startup selector or a session is refused; remove the reference first.

The default selection file is a separate `startup/selection.json`, generated from `selection.default.json` on first install:

```json
{"default_modelconf":"deepseek-flash","default_websearch":"tavily"}
```

It only stores "who is selected by default", not another set of runtime parameters. You can edit the file directly. An explicit or session-level selection takes precedence; a model configuration inherits from here only when it does not specify websearch; `--websearch=none` or JSON `null` turns it off explicitly. The tool set and unavailable-tool notes are injected dynamically per run snapshot and are not permanently written into history.

The full parameter table is in [CONFIG.md](docs/CONFIG.md). The four default quotas are **0 = no proactive limit**, the total task timeout defaults to **1800 seconds**, and per-step network/size protections remain. A shorter outer `exec` still interrupts earlier. DeepSeek defaults to thinking enabled, effort=auto (the API field is omitted), and temperature/top_p=1; whether a parameter is adopted depends on the model mode.

## Session Management: Explicit Targets

```bash
batchcode session add research
batchcode session add review --heredoc <<'JSON'
{"modelconf":"deepseek-flash","temperature":0.6}
JSON
batchcode session list
batchcode session get info research
batchcode session get conf research
batchcode session get ctx research --evt_start=5 --evt_end=10
batchcode session get ctx research --msg_start=2 --msg_end=5
batchcode session get ctx research --evt_id=5
batchcode session get ctx research --msg_id=2
batchcode session export ctx research /workspace/outbox/research.ctx.json
batchcode session rename research literature-review
batchcode session fork ctx literature-review branch-a
batchcode session fork conf literature-review branch-b
batchcode session fork all literature-review branch-c
batchcode session del ctx branch-a
batchcode session del conf branch-b
batchcode session del all branch-c
```

Query ranges are **IDs, not array positions**. Queries by evt return the raw on-disk text of the events; queries by msg return the organisational record plus the raw text of the events it references. A display that would exceed 24,000 characters **is refused as a whole** (stdout emits no partial data), with a hint to narrow the range or export. An unfiltered `get ctx` returns the original file; even if compilation fails, the ctx can still be queried and exported. `export` refuses to overwrite an existing file by default.

An explicit reference must already exist: `task REF`, `session set conf REF`, get/export, and so on report an error on a bad reference and never create anything. Creation uses a reference-less task (optionally with `--name`), `session add`, or an explicit fork. `session del ctx/conf/all` on a non-existent session is still an idempotent no-op. A fork source must exist and the fork target must be new.

`info.json` **has no name**; the single source of truth for names is `session_index.json`. Actual paths, locks, and parent_id all use immutable IDs. A rename only updates the index — it does not move directories or change history; deleting and re-creating a session with the same name yields a new ID, and old artifacts are not overwritten. `list` shows names along with IDs; `Active` is based on run locks and does not count configuration-management locks as running.

**Deleting ctx only clears history; it does not remove the session's identity or make it unrunnable**: the session still appears in `session list` and can accept new tasks under the same name/ID. Deleting ctx keeps the configuration and the numbering high-water mark; deleting conf clears overrides; deleting all removes the session record and run audit but keeps artifacts. A fork does not copy old logs or artifacts. Deletion is not a provider-side retraction or a secure disk erase.

After a successful `session del all`, `locks/<sessionid>.lock` and `running/<sessionid>.lock` are removed as well, so two empty files are no longer left behind forever. Deletion only refuses when the **target session** is running or held by a management operation; it does not require other sessions to stop. `del ctx/conf` and rename do not clean up those two locks.

Lock-file creation/checking and deletion are coordinated through the same index lock: during deletion the target lock is held, the ID is deregistered, and then the corresponding lock files are removed; a stale ID does not re-create a lock. `session list`'s run-state probe does not create files. An interrupted deletion is recovered on the next index operation; if a filesystem error causes a partial deletion, success is not reported and you must troubleshoot and retry. The global `index.lock`, `lifecycle.lock`, and `profiles.lock` are never deleted.

## History Editing and rerun

```bash
batchcode session evt edit research --evt_id=19 --content="Edited input"
batchcode session evt del research --evt_id=19
batchcode session evt add research --after_evt=19 --content="Additional condition"
batchcode session evt add research --after_msg=7 --content="Append to this user msg"
batchcode session msg add research --after_msg=0 --content="Insert at the beginning"
batchcode session msg add research --after_msg=7
batchcode session msg del research --msg_id=7 --drop-suffix

batchcode task rerun research --evt_id=19
batchcode task rerun research --msg_id=7
batchcode session evt edit research --evt_id=19 --content="Edit, then run" --rerun --drop-suffix
```

- Local edits are only allowed on user messages; msg offers no edit. An edit changes only the content it points at and that evt's timestamp; it does not guess semantic coherence and does not patch old answers.
- `add` does not accept drop-suffix. `evt edit` with drop-suffix keeps the edited target and discards the logical content after it (including later evts in the same msg); `evt del` deletes the target and everything after it; `msg del` deletes the target msg and everything after it.
- `edit --rerun` **requires an explicit `--drop-suffix`** and errors before modifying anything if it is missing. `--drop-suffix` on its own only edits/truncates and does not call the model automatically.
- `rerun` targets an existing user message, keeps the entire input and everything before it, permanently discards the following context, and then hands it to the provider. It **cannot change the timestamp**; the time at which the rerun happened is recorded separately in the run information. A failed check does not truncate; once execution has begun, a later API failure does not restore the old tail.
- File and other tool side effects are not rolled back. Fork first if you need to keep the original branch.
- New evt/msg IDs always increase and are never renumbered; logical order is determined by the msgs array and evt_ids, so a history insertion can produce `[10,81,11]` and must not be compiled by numeric sort.
- The `0` in `msg add --after_msg=0` only means "at the very beginning" and is not a real ID. Omitting content creates an empty msg, which can still be queried by ID or filled in later. Compilation ignores empty msgs and reports it once on stderr. Deleting every last evt is likewise allowed.
- A non-user evt can only be used as an insertion anchor at the end of the msg it belongs to; if the next valid msg is a user msg, the insertion goes to its beginning, otherwise a user msg is created; the tail can be appended to. `evt add --after_msg`, by contrast, always appends to the end of the selected user/empty msg.
- **Nothing can be inserted between an assistant tool request and all of its tool feedbacks**, nor between multiple feedbacks. Skipping empty msgs in logical order, call-ID pairing is checked and illegal positions are rejected before writing. Empty `tool_calls` (null/`[]`) do not count as an outstanding request.

## Compilation, Diagnostics, and Boundaries

The ctx structure and compilation rules are in [CONTEXT.md](docs/CONTEXT.md). The stderr task header is `[critical m, warning n]`; the same repeated compilation problem is counted once. `critical` blocks the corresponding operation, while `warning` means "can continue but something was ignored or degraded" and does not verify facts on the model's behalf. Raw text is preserved and compilation happens in memory; time prefixes are not written back.

Tools: read_file, list_directory, write_file, submit_answer, plus Tavily web_search/fetch_url when available. Writes are confined to `sub_workspace/<sessionid>/`; there is no shell, and `exec_command` is in the TODO. Only UTF-8 text is supported, with no PDF/Word parsing and no general multimodal/Responses API.

**This is not an OS-level sandbox** and cannot defend against any process with the same UID modifying files; files allowed for reading will be sent to the model service. Do not widen read_roots to an entire private workspace, and credential directories and program state are always forbidden to the tools. File-operation failures are distinguished as FILE_NOT_FOUND / PERMISSION_DENIED / IS_A_DIRECTORY / NOT_A_DIRECTORY and so on, with the requested path and errno included in the feedback; only JSON parse/type errors are reported as argument problems.

## Diagnostics and Uninstall

```bash
batchcode self-check
batchcode doctor --websearch=tavily --samples=1 --timeout=3
batchcode doctor --json
bash uninstall.sh
```

`self-check` is offline; `doctor` explicitly tests DNS inside the container and never sends keys or model requests and never fixes DNS. With a normal query and no diagnostics, stderr is empty. Uninstall removes only this installation's PATH entry and private venv, keeping configuration, keys, history, artifacts, and source; it refuses while commands are active and never touches system Python, coreutils, or DNS. Re-running `install.sh` reinstalls.

## Development and Verification

```bash
python3 -m unittest discover -s tests -v
python3 scripts/package.py
```

[Test scope and limitations](docs/TESTING.md) · [Changelog](CHANGELOG.md) · [AGENT.md](AGENT.md) · [TODO](docs/TODO.md)

MIT License. Release packages are built from a whitelist and refuse a non-empty key in the default profile; they contain no run history, run configuration, venv, DNS-fixing scripts, or private test reports.
