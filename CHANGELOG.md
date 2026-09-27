# Changelog

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
