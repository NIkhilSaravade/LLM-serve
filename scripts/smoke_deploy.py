"""Post-deploy check against a running service. Standard library only, so it runs anywhere.

Verifies the thing a release must guarantee: the build that is serving is the build that was deployed,
it is ready, it answers concurrent requests, and it counted them. It deliberately does not assert latency:
shared CI runners are too noisy for that, and a flaky gate gets ignored. Performance is gated by the
benchmark suite, not here.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def get(url: str, timeout: float = 10) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode()


def generate(base: str, i: int) -> int:
    body = json.dumps({"prompt": f"Request number {i}: the capital of France is", "max_new_tokens": 12}).encode()
    req = urllib.request.Request(base + "/generate", data=body, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return len(r.read()) if r.status == 200 else -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--expect-sha", required=True)
    ap.add_argument("--requests", type=int, default=24)
    a = ap.parse_args()

    status, _ = get(a.base + "/ready")
    assert status == 200, f"/ready returned {status}"

    version = json.loads(get(a.base + "/version")[1])
    assert version["git_sha"] == a.expect_sha, f"serving {version['git_sha']}, expected {a.expect_sha}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        sizes = list(pool.map(lambda i: generate(a.base, i), range(a.requests)))
    assert all(s > 0 for s in sizes), f"some requests failed: {sizes}"

    metrics = get(a.base + "/metrics")[1]
    ok = [ln for ln in metrics.splitlines() if ln.startswith('llm_requests_total{status="ok"}')]
    assert ok and float(ok[0].split()[-1]) >= a.requests, f"request counter did not advance: {ok}"

    print(f"ok: serving {version['git_sha']}, {a.requests} concurrent requests, counter {ok[0].split()[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
