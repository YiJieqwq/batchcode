# Changelog

## 0.3.2 — 2026-09-28

- Make submit_answer the normal final delivery requirement in both summary and full, including completed, abandoned and no-task replies. Still allows revisions/closing, no invented file/search work.
- Full stdout now includes the final /answer as well as visible /evt messages; same last-valid-submission and warned fallback behavior as summary. Failed runs remain failed even if they have an answer.
- Remove the answer-length configuration/CLI target, fixed numeric prompt guidance and feedback target. Follow user-provided length in task content; otherwise answer concisely. Each submit still returns its actual character count; no answer truncation.
- Install-time cleanup backs up and removes the retired field from active model/session configs and pending config transactions. Keys, other settings and raw history stay unchanged; no runtime alias remains.
- Same ctx schema and strict-reference/name policies as 0.3.1. No unrelated GC, human-renderer, help or automatic-name redesign.
- 168 offline/mock regressions passed locally; revised v0.3.2 prompt requires live validation.


## 0.3.1 — 2026-09-28

- Explicit task/session references are strict: unknown names/IDs fail, never silently create; session set conf now also requires an existing session. Omitted task reference still creates.
- Add task --name for new-session naming and existing-session rename (including rerun), without moving data or persisting name into info/config. Duplicate/new-name collisions and busy sessions fail before modification. Batch tasks use name for new labels, session only for existing refs; fork_from destinations also use name.
- Keep readable name-based output prefixes even when invoking by ID; reduce diagnostic ID repetition. Stable ID remains in status/list/info.
- Summary instructions require submit_answer in finished, unable-to-continue and no-task cases (including greetings), without unrelated tool work. Per-submission character soft target, revisions, normal closing and abnormal no-submit fallback preserved. Full mode unchanged.
- Split filesystem failures from JSON/argument failures; provide accurate file error codes, requested path and errno.
- Clarify del ctx keeps an existing session runnable/listed. Same schema as v0.3.0, no data migration.
- 149 offline/mock tests pass locally; new prompt not live-certified.


## 0.3.0 — 2026-09-27 (breaking)

- Object-first task/gconf/session CLI; remove op/sconf and old flags. No old storage migration.
- Immutable session IDs, authoritative name index, separate ctx/config/info, rename without moving artifacts.
- Shallow msgs/events context, provider compiler, located critical/warning diagnostics, pure UTC user milestones.
- User-only evt/msg editing, explicit drop-suffix, rerun, blank-message handling and tool-pair insertion guards.
- Default summary via revisable submit_answer (not an immediate stop), full visible-content option and independent stderr granularity; last-content fallback with IDs, historical submissions excluded.
- Stream assembly, complete-block persistence, partial-block discard, interrupted nonstream content not used as answer.
- Named profiles own complete runtime defaults; explicit task settings persist to session, frozen tmpconf, optional final key completion, no provider routing.
- Default model/tool/context/output quotas 0, task timeout 1800s, retained per-step guards. Startup model/search selection separate from configuration.
- Dynamic tool availability and unavailable-search notice, no transcript redaction/role duplication, no source mutation on model switch.
- Recoverable index/session transactions, lifecycle install/uninstall locks, file-spooled terminal output and local batch-failure isolation.
- 119 offline/mock tests; live new-version provider validation still required.


## 0.2.2 — 2026-09-27

- Add conservative uninstall.sh: remove only exact matching PATH launchers and private .venv; preserve all user data and source. Busy lock checks, idempotence, symlink rejection. No system package removal.

## 0.2.1 — 2026-09-27

- Add explicit read-only DNS doctor; no automatic repairs or resolver changes.
- Add optional layered sampling/thinking parameters and provider-default auto mapping.
- DS default enables thinking, effort auto, temperature/top_p 1.
- Release ZIP no longer includes runtime config.json; installer creates it only if missing. Profile files can still be overwritten by unsafe overlay extraction.
- External v0.2.0 report confirms DeepSeek/Tavily live functionality; DNS skewed latency measurements.

## 0.2.0 — 2026-09-27

- Rename subagent to batchcode; PATH-registered executable, `task` / `op` command tree.
- JSON profiles now use `.txt`; default DeepSeek filename matches deepseek-flash.
- Complete visible messages on stdout in BOTH granularities; tool summaries/errors on stderr; persistent session event IDs.
- Global and per-session configuration, field-level inheritance and unset; missing sessions created on edits.
- Fork sessions independently or as part of a batch; same-source snapshot under locks.
- Proot-compatible subprocess concurrency, input-order aggregation, per-session output directories.
- `task list` uses dedicated active locks, separate from management locking.
- Structured HTTP failure status/retries persisted; clarify fine/coarse are not confidentiality boundaries.
- MIT project, CI matrix, regression tests and clean release packaging.

## 0.1.0 — 2026-09-26 (subagent prototype)

- Single synchronous delegate, Chat Completions + Tavily, read/write/search/fetch, session persistence/deletion.
- External report states DeepSeek/Tavily live checks passed in another Ubuntu proot container.
- Legacy CLI/config names are not accepted by 0.2.0; install in a separate directory. No automated session migration.
