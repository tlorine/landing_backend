# Analytics backend verification — 2026-10-24

Scope: local code and isolated PostgreSQL, no production deployment/configuration
or production dataset was accessed. APP_ENV=test skips secret .env files.

## Functional checks

- 176 pytest tests passed locally, including the existing 162 regressions.
- PostgreSQL integration covers concurrent duplicate insert + exactly one legacy
  SiteVisit projection, rollback on conflicting retry, out-of-order navigation,
  deterministic concurrent session attribution, auth/CSRF/logout/disabled/expired
  sessions, durable login throttling, forged geo headers, body/origin/media limits,
  absent outbound link, session-disabled mode, historical session availability after
  mode changes, distinct counts across days, retention and partial coverage.
- Ruff lint and format passed. Alembic check found no schema drift after upgrade.
- CI includes a populated 0002 migration fixture: request, notification outbox and
  visit must survive upgrade to head. Root integration independently exercised this
  path on a separate isolated database.
- Canonical offline OpenAPI documents both ingestion media types, event/entry
  schemas, auth, response models and error envelope. Frontend pins that artifact.

Integration/browser review is coordinated by the parent task and documented in
the frontend repository; this document does not claim independent visual QA.

## Representative load check (not a production SLO)

Environment: local macOS arm64 host, Docker PostgreSQL 16, default shared_buffers
128 MB, work_mem 4 MB, max_parallel_workers_per_gather 2. Test container has 64 MiB
shared-memory allocation. Host workload/cache was not controlled.

Separate analytics_benchmark_test database contained 1,000,000 synthetic events,
100,000 sessions over 60 days, country/source distributions, 500,000 case views
and corresponding outbound events. The measured interval was 30 days, about
496,597 events. All simulated case traffic belongs to airena; this is a volume
fixture, not a claim about real visitor behavior or every distribution.

- Overview after the realistic-fixture update: 8.78 / 6.58 / 5.21 seconds.
- Case detail after maintenance: 7.89 / 4.60 / 4.16 seconds.
- Case session conversion returned 49,660 / 49,660 = 1.0, despite 248,299 raw clicks
  and 248,298 views: repeated views/clicks did not inflate session conversion.
- EXPLAIN case aggregation: ~1.22 seconds, with ix_analytics_page correlated lookup
  (~248k index probes); no raw event loading into Python. The approach is adequate
  for this fixture, but larger scales may justify an aggregate join after measurement.
- Three measurements per response are insufficient to estimate p95. First runs
  are not guaranteed cold-cache measurements. Do not infer production latency.

Raw measurements and EXPLAIN output:
[overview](../contracts/benchmarks/overview-1m.json),
[case detail](../contracts/benchmarks/case-detail-1m.json).

One manual parallel VACUUM ANALYZE after a million-row fixture update exceeded the
container's default 64 MiB /dev/shm. Retrying VACUUM (PARALLEL 0, ANALYZE) succeeded.
This was isolated benchmark maintenance, not an application request failure. Set
appropriate container memory/shared-memory resources for production and measure
with its actual data/hardware. Production deployment/resource validation remains
a rollout gate, alongside the actual trusted proxy/client-IP/country chain.

## Limits

- Ingestion is best-effort; beacon delivery cannot be guaranteed.
- Sessions represent a browser tab, never unique people or cross-device identity.
- Geo requires a validated trusted edge; defaults ignore untrusted CF headers.
- Existing single-process lifecycle/limiter architecture must be preserved until
  singleton workers and shared limits are explicitly designed for scaling.
- Feature flags default off; administrator provisioning, same-origin proxy,
  disclosure/session mode, manifest and coverage intervals must be coordinated.
