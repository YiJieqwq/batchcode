# Changelog

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
