"""Run a bounded concurrent HTTP smoke test against an authorized CampusHire API."""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from collections import Counter
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Result:
    status_code: int | None
    elapsed_seconds: float
    error: str | None = None


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


async def send_request(client: httpx.AsyncClient, url: str, start: asyncio.Event) -> Result:
    await start.wait()
    began = time.perf_counter()
    try:
        response = await client.get(url)
        return Result(response.status_code, time.perf_counter() - began)
    except httpx.HTTPError as error:
        return Result(None, time.perf_counter() - began, type(error).__name__)


async def run(url: str, requests: int, concurrency: int, timeout_seconds: float) -> int:
    limits = httpx.Limits(
        max_connections=concurrency,
        max_keepalive_connections=min(concurrency, 100),
    )
    start = asyncio.Event()
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(limits=limits, timeout=timeout_seconds) as client:

        async def bounded_request() -> Result:
            async with semaphore:
                return await send_request(client, url, start)

        tasks = [asyncio.create_task(bounded_request()) for _ in range(requests)]
        began = time.perf_counter()
        start.set()
        results = await asyncio.gather(*tasks)
        wall_seconds = time.perf_counter() - began

    statuses = Counter(result.status_code for result in results)
    errors = Counter(result.error for result in results if result.error is not None)
    latencies = [result.elapsed_seconds for result in results]
    successful = sum(
        count
        for status_code, count in statuses.items()
        if status_code is not None and status_code < 400
    )

    print(f"requests={requests} concurrency={concurrency} successful={successful}")
    print(f"wall_seconds={wall_seconds:.3f} requests_per_second={requests / wall_seconds:.1f}")
    print(
        "latency_ms "
        f"p50={percentile(latencies, 0.50) * 1000:.1f} "
        f"p95={percentile(latencies, 0.95) * 1000:.1f} "
        f"p99={percentile(latencies, 0.99) * 1000:.1f}"
    )
    print(f"status_counts={dict(statuses)}")
    if errors:
        print(f"error_counts={dict(errors)}")
    return 0 if successful == requests else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/v1/health/live")
    parser.add_argument("--requests", type=int, default=1_000)
    parser.add_argument("--concurrency", type=int, default=1_000)
    parser.add_argument("--timeout", type=float, default=30.0)
    arguments = parser.parse_args()
    if arguments.requests < 1 or arguments.concurrency < 1:
        parser.error("requests and concurrency must be positive")
    if arguments.concurrency > arguments.requests:
        parser.error("concurrency cannot exceed requests")
    return arguments


def main() -> int:
    arguments = parse_args()
    return asyncio.run(
        run(arguments.url, arguments.requests, arguments.concurrency, arguments.timeout)
    )


if __name__ == "__main__":
    raise SystemExit(main())
