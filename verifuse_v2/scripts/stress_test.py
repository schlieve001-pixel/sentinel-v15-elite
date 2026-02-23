#!/usr/bin/env python3
"""
stress_test.py — Concurrency stress test for VeriFuse API.

Usage:
  export VF_TOKEN="<valid JWT from /api/auth/login>"
  export API_BASE="http://localhost:8000"
  python3 verifuse_v2/scripts/stress_test.py
"""
import asyncio
import os
import time

import httpx

BASE  = os.environ["API_BASE"]
TOKEN = os.environ["VF_TOKEN"]
# Exact headers from frontend (matches localStorage vf_token usage)
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


async def run_stress():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        # 10 anonymous + 10 authenticated concurrent requests
        tasks = (
            [client.get("/api/preview/leads") for _ in range(10)] +
            [client.get("/api/leads", headers=HEADERS) for _ in range(10)]
        )
        t0 = time.perf_counter()
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.perf_counter() - t0

    latencies, status_counts, errors = [], {}, []
    for r in responses:
        if isinstance(r, Exception):
            errors.append(str(r))
        else:
            latencies.append(r.elapsed.total_seconds())
            status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1

    latencies.sort()
    n = len(latencies)
    p50 = latencies[n // 2]
    p90 = latencies[int(n * 0.90)]
    p99 = latencies[int(n * 0.99)]

    print(f"Total elapsed: {elapsed:.2f}s | Requests: {n} | Errors: {len(errors)}")
    print(f"Status counts: {status_counts}")
    print(f"Latency — p50={p50:.3f}s  p90={p90:.3f}s  p99={p99:.3f}s")
    db_lock_errors = sum(1 for e in errors if "database is locked" in e)
    server_errors  = status_counts.get(500, 0) + status_counts.get(503, 0)
    print(f"DB lock errors: {db_lock_errors}")
    print(f"5xx errors: {server_errors}")

    assert db_lock_errors == 0, f"FAIL: {db_lock_errors} 'database is locked' errors"
    assert server_errors  == 0, f"FAIL: {server_errors} 5xx errors"
    print("PASS: 0 database lock errors, 0 5xx errors")


asyncio.run(run_stress())
