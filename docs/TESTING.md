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

## v0.2.1 — 2026-09-27

31 offline/mock tests passed on current Python 3.14 proot, including bounded DNS-probe timeout, DNS summary, profile host-only selection without keys, parameter validation/auto omission and layered request-body overrides.
Explicit real DNS diagnostic (2 samples/host) observed DeepSeek 5.9481/5.2657 seconds and Tavily 5.4713/5.3203 seconds; warning exit 1 as designed, no resolver changes or paid API calls. This establishes slow system name resolution here, not the precise underlying network cause.
No v0.2.1 live model API integration. Enabling DS thinking changes runtime behavior relative to the previously live-tested non-thinking profile. Release fresh install verified separately.
The user-supplied v0.2.0 external report describes 24 offline tests plus successful real DeepSeek/Tavily scenarios (not OpenAI); report scenario-count headings are inconsistent, so no exact live-test count is asserted here.
