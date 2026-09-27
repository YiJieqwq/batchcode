# Validation status

## v0.3.0 — 2026-09-27

Local environment: Ubuntu 26.04.1 proot, Python 3.14.4.
**115 offline/mock tests passed**. These are new-version tests, not a claim that the former 35 tests automatically validate the redesign.

Coverage:
- ctx schema/reference ownership, kind inference, field order, null/empty/missing, repeated/interleaved text, pure milestone compilation, provider field projection without mutating stored content.
- tool pairing and insertion rejection through both evt/msg paths, including multi-tool feedbacks; raw query despite broken references; oversize display refusal and export.
- user edit, empty-msg fill/ignore, prepend sentinel, granular drop-suffix, rerun identity/time preservation, failed preflight leaving context intact.
- stable name/ID mapping, same-object batch detection, rename, fork modes/shared snapshots, recreate new ID with old artifacts retained, transaction redo and high-water gaps.
- actual subprocess concurrent overlap and Active listing; mixed task failures isolated; parent termination; frozen config; explicit task parameters persisted; global empty key completed by session; no automatic routing.
- summary revisions, invalid resubmit preserving valid answer, no hard summary length policy, no historical submit reuse, failure after submission, full visible content, final fallback and numbered diagnostics.
- SSE fragmentation, complete text vs partial tool args, stream disconnect, nonstream truncation not fallback; no per-token events.
- key-shaped strings preserved; path/symlink/hardlink/FIFO/UTF-8 page boundaries; tool availability enforcement; lifecycle busy uninstall and repeat/move install.
- localhost DNS diagnostic executes without key/API calls or changing resolv.conf; no external network needed for regression tests.

No real API credentials were used for v0.3.0. In particular, mocks cannot prove that an actual model obeys the new hello/no-exploration prompt, submits well-formed answers consistently, or has exactly the tested SSE behavior. Those require live validation. Older external reports attest prior DeepSeek/Tavily integration, not new-version OpenAI or streaming certification.

The actual missing-package apt branch and arbitrary same-UID attacker races remain untested/out of scope. CI matrix Python 3.10/3.12/3.14 should be read from actual Actions results; do not assume a configured workflow has passed.

## Reproduce

```bash
python3 -m unittest discover -s tests -v
python3 scripts/package.py
```

Release ZIP is checked separately by extraction into a fresh directory, local install, CLI/schema smoke, uninstall and reinstall. Package builder refuses nonempty keys in public profiles and excludes session data/venv/private test reports/DNS repair. Runtime startup/selection.json is generated only if absent. Current 0.2.x data is not converted or removed.
