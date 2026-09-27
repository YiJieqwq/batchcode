# Test status

## v0.2.0 local author validation — 2026-09-27

Environment: Ubuntu 26.04.1 proot, Python 3.14.4.
24 offline/mock HTTP unittest cases passed. Includes actual subprocess overlap (both sessions visible Active simultaneously), batch mixed failures, fork snapshots, configuration overrides/unset/model switch, active-vs-management lock distinction, full visible message retention, fine/coarse separation, source/write isolation, HTTP error detail persistence, timeout/resume and incomplete tool-history repair.
Install/register through PATH and local repeat/move installation verified. ZIP fresh-install validation is performed by release packaging checks.
No real API calls were made for v0.2.0. No real keys used or distributed.

The default ProcessPoolExecutor was unsuitable in the current proot due to unavailable system semaphore support. Final implementation uses bounded parent threads to supervise independent Python subprocesses, with JSON pipes and no shared-memory semaphore requirement.

## Earlier external validation (v0.1.0)

The user supplied an independent-container report: 18 offline tests and 12 real DeepSeek/Tavily scenarios passed (conversation, continuation, file read/write, search/extract, delete, errors, timeout/resume, locks). This report is evidence for the older protocol foundation, **not a live-service certification of the new v0.2 CLI or OpenAI service**. Raw session logs and credentials are deliberately not committed.

## Remaining coverage

- Real v0.2 DeepSeek/Tavily and OpenAI API integration.
- apt branch on a system actually missing Python/venv/CA.
- Python 3.10/3.12 on CI (configured; consult actual Actions result).
- Cost/rate-limit variability, minutes-long provider stalls and hard host termination.
- Dedicated prompt-injection adversarial tests and OS-level isolation (not provided).
- Shared-directory local attacker races are outside the tool-only threat model.

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

Mock credentials are fixed fake strings. No live test in CI; never add API secrets to fixtures.
