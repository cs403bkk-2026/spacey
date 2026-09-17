"""Simple load/capacity test for Spacey.

Hits GET /spaces repeatedly at a given concurrency level and reports
request volume, latency, and failure rate. Run it at two different
--concurrency levels to compare, per issue #33.

Usage:
    DATABASE_URL=... python scripts/load_test.py --url http://127.0.0.1:5000 \
        --requests 200 --concurrency 5
"""
import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import requests


def make_request(url: str) -> tuple[bool, float]:
    start = time.perf_counter()
    try:
        response = requests.get(f"{url}/spaces", timeout=10)
        ok = response.status_code == 200
    except requests.RequestException:
        ok = False
    elapsed_ms = (time.perf_counter() - start) * 1000
    return ok, elapsed_ms


def run(url: str, total_requests: int, concurrency: int) -> None:
    print(f"Running {total_requests} requests at concurrency={concurrency} ...")
    start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda _: make_request(url), range(total_requests)))

    total_time = time.perf_counter() - start
    latencies = [ms for ok, ms in results if ok]
    failures = sum(1 for ok, _ in results if not ok)

    print(f"Total wall time: {total_time:.2f}s")
    print(f"Successful requests: {len(latencies)}/{total_requests}")
    print(f"Failed requests: {failures}/{total_requests} "
          f"({failures / total_requests:.1%})")
    if latencies:
        print(f"Latency (ms) - min: {min(latencies):.1f}, "
              f"median: {statistics.median(latencies):.1f}, "
              f"p95: {sorted(latencies)[int(len(latencies) * 0.95) - 1]:.1f}, "
              f"max: {max(latencies):.1f}")
    print(f"Throughput: {total_requests / total_time:.1f} req/s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5000")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    run(args.url, args.requests, args.concurrency)