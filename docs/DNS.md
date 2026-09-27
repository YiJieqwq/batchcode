# Read-only container DNS diagnosis

```bash
batchcode doctor --modelconf=deepseek-flash --websearch=tavily
batchcode doctor --samples=1 --timeout=3
batchcode doctor --json
```

Explicit invocation only. The system resolver is measured in bounded subprocesses for selected API hostnames; no API auth or paid requests, no public resolver ranking, no /etc/resolv.conf modification and no repair script. Default samples 3, per sample timeout 10s. Slow/unreliable sample warning returns 1; valid fast samples 0; bad arguments/config 2. Critical/warning header precedes stderr diagnostics.

harness networking and container networking may differ. External v0.2.0 report found unreachable resolvers first in resolv.conf, 5–8s repeated DNS delays; same prompt observed 66.7s →13.7s after separately repairing the environment. This is an observed workload comparison, not a fixed 5x speed guarantee or token-cost multiplier. Current v0.3 tests don't repair/retest your internet resolver.

Slow threshold (median at least 1s) is heuristic; >0.2s isn't automatically a fault. Fast answers are not proof of correctness (pollution/interception can be fast). hosts/NSS/cache may participate. Doctor does not test HTTPS, proxy paths, rate limits or generation latency. DNS repair remains a separate user-maintained tool. Never replace corporate/split-horizon DNS automatically.
