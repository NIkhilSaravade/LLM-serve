"""Steady in-cluster traffic, so a canary is judged on real requests instead of silence. Standard library only.

Closed loop: CONCURRENCY workers, each sends a request, waits for the answer, and repeats. Failures (429,
timeouts) are expected when the release under test is bad, so they are counted and never stop the loop.
"""
from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request

TARGET = os.environ.get("TARGET", "http://llm-serve")
CONCURRENCY = int(os.environ.get("CONCURRENCY", "12"))
NEW_TOKENS = int(os.environ.get("NEW_TOKENS", "16"))
counts = {"ok": 0, "rejected": 0, "error": 0}
lock = threading.Lock()


def worker(i: int) -> None:
    n = 0
    while True:
        n += 1
        body = ('{"prompt":"Worker %d request %d: the capital of France is","max_new_tokens":%d}'
                % (i, n, NEW_TOKENS)).encode()
        req = urllib.request.Request(TARGET + "/generate", data=body, headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                r.read()
            key = "ok"
        except urllib.error.HTTPError as e:
            key = "rejected" if e.code == 429 else "error"
        except Exception:
            key = "error"
            time.sleep(1)
        with lock:
            counts[key] += 1


for i in range(CONCURRENCY):
    threading.Thread(target=worker, args=(i,), daemon=True).start()
while True:
    time.sleep(15)
    with lock:
        print(counts, flush=True)
