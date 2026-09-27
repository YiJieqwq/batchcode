# Validation status

## v0.3.0 — 2026-09-27

Local environment: Ubuntu 26.04.1 proot, Python 3.14.4.
**119 offline/mock tests passed**. These are new-version tests, not a claim that the former 35 tests automatically validate the redesign.

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

The actual missing-package apt branch and arbitrary same-UID attacker races remain untested/out of scope. GitHub Actions passed on Python 3.10/3.12/3.14 at initial v0.3 commit 4233b67 (115 tests). The final follow-up adds four regression tests (119 local passes); consult final Actions status for that revision.

## Reproduce

```bash
python3 -m unittest discover -s tests -v
python3 scripts/package.py
```

Release ZIP is checked separately by extraction into a fresh directory, local install, CLI/schema smoke, uninstall and reinstall. Package builder refuses nonempty keys in public profiles and excludes session data/venv/private test reports/DNS repair. Runtime startup/selection.json is generated only if absent. Current 0.2.x data is not converted or removed.


## v0.3.1 — 2026-09-28

149 offline/mock tests passed locally, including 30 additions around strict references/no hidden creation, omitted-ref creation, --name for creation/continuation/rerun, conflict and busy refusal, name-only output prefixes, per-task batch names, maintained ID/history/artifact paths, explicit fork destinations, and typed filesystem error feedback to both model and caller.

Prompt assertions verify summary's finished/abandoned/no-task submission instructions, per-submission character counts, soft length behavior and full-mode direct replies. A mock greeting submission proves normal submit/closing/result routing; it does NOT certify a real model's compliance. Fallback tests deliberately simulate missing submissions so the safety net remains covered.

The user supplied an independent-container v0.3.0 report (119 offline tests, real DeepSeek/Tavily scenarios). It reports three hello runs without unrelated exploration and working submit/feedback/soft-length cases. This is external observational evidence for v0.3.0, not a guarantee of consistent submissions; indeed its greeting cases intentionally did not submit under the old prompt. The new v0.3.1 prompt still needs live validation. OpenAI live integration, adversarial streaming interruption and hard-kill behavior were not certified by that report. Private report and session contents are not included in the public repository.

`session del ctx` leaving a listed, runnable session is intentional, not a defect; tested by clearing history then submitting a new task under the same ID. Only explicit `session del all` removes the identity.

Before release: run the CI matrix and clean ZIP install/uninstall/reinstall checks on this exact revision. No actual provider credentials or paid calls are used in this suite.


## v0.3.2 — 2026-09-28

168 offline/mock tests passed locally (same proot/Python 3.14 environment). Additional coverage includes full-mode final answer delivery with visible closing, revisions/invalid re-submits, no-content submissions, failure after submission, warned fallback and no stale-history reuse. Shared prompt assertions require submission in BOTH modes for no-task/greeting cases. Tool feedback is checked for actual per-submission character count including Unicode/punctuation/space/newline and for absence of numeric target fields.

Config tests verify the removed answer-length option is no longer accepted by task/gconf/session schemas or shown in help/defaults. Installation cleanup is idempotent, backs up exact originals, preserves keys/other settings/ctx/info, handles pending transactions without resurrecting the retired setting, and refuses unsafe symlinks or invalid JSON before mutation. Fresh ZIP install/uninstall/reinstall validation is separate from mocks. Follow the actual GitHub Actions result for this revision before treating all Python versions as verified.

A user-supplied independent v0.3.1 brief reports successful real DeepSeek/Tavily use and 149 offline tests. It observed greeting submissions, strict names and full-mode submissions whose bodies were not displayed—consistent with the output defect fixed here. This is external evidence for v0.3.1, not a guarantee that every v0.3.2 model call follows the new shared prompt. No v0.3.2 real API calls are performed by the offline suite; no new OpenAI live certification. The private report is not committed or packaged.


## v0.3.3 — 2026-09-28

Regression suite expanded to 208 offline/mock tests. New tests cover:

- Successful deletion of both per-ID lock files without touching artifacts, same-ID locks on del ctx/conf/rename, unknown-ID no-op, and global lock inode preservation.
- Non-creating session list/active probes, delayed subprocess openers using previously resolved IDs, stale list snapshots, and parent/child inherited management descriptors.
- Busy management/running guards before destructive work, independent active sessions continuing while an idle session is deleted, and resumable delete transactions at directory/index/lock cleanup boundaries.
- Installer-only orphan cleanup/idempotence; preservation of registered sessions, unindexed session directories/symlinks, busy locks, nonempty files, hardlinks, symlinks and non-generated filenames. Corrupt indexes fail closed instead of purging files; inode replacement checks refuse the replacement.
- The answer-body-only rule appears once in the shared system prompt in both modes, with the user-requested markup/code exception. Mocks intentionally return XML/HTML and protocol-like suffix text to verify that raw parameters, output and character counts are not rewritten by a tag-stripping heuristic.

Prompt assertions/mocks do not prove real-model suppression of unwanted suffixes. No v0.3.3 real provider calls or new OpenAI live certification. Run the full local suite, final ZIP install/cleanup/uninstall/reinstall checks and actual CI results before publishing this revision.
