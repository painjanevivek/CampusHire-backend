# Scaling the CampusHire API

CampusHire has no ten-user global limit. The two ten-request values protect
account sign-in and semantic matching; they are per identity and must not be
raised to simulate more concurrent users.

## Code-level concurrency controls

- A warm API process reuses a small, bounded SQLAlchemy connection pool. The
  normal application `DATABASE_URL` must be Neon's pooled (`-pooler`) URL.
- The Redis rate limiter reuses one bounded client pool per API process instead
  of opening a client for every protected request.
- Argon2 hashing and verification run in worker threads so a sign-in cannot
  block unrelated async requests on the FastAPI event loop.
- Authenticated session, user, and active membership data load in one joined
  query instead of separate relationship round trips on every protected route.
- Resume scanning, parsing, cleanup, and delivery remain durable worker jobs.
  Do not execute those CPU-heavy workloads in the request process.

The safe starting values are:

```dotenv
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=5
DATABASE_POOL_TIMEOUT_SECONDS=10
DATABASE_POOL_RECYCLE_SECONDS=300
REDIS_MAX_CONNECTIONS=64
REDIS_POOL_TIMEOUT_SECONDS=1
```

Do not set a database pool size of 1,000. The process pool is backpressure; Neon
pooling and the application platform multiplex concurrency across instances.
Increasing these values without measured database headroom can reduce capacity.

## Local concurrency smoke test

Start the API without `--reload`, because the development file watcher adds
noise, then run:

```text
python scripts/load_smoke.py --url http://127.0.0.1:8000/api/v1/health/live --requests 1000 --concurrency 1000
```

The command exits non-zero if a response fails and reports throughput plus
p50/p95/p99 latency. It tests whether 1,000 simultaneous lightweight requests
can traverse the local HTTP stack. It does not prove that 1,000 users can all
sign in, query Neon, upload resumes, or request AI matching at once.

Before a production launch, create a representative test dataset and test a
mix of read, write, authentication, and queued-job endpoints in an isolated
environment. Infrastructure quotas, database compute, network latency, and the
durable worker rate remain hard ceilings that source code cannot remove.
