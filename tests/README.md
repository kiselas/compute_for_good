# Local alpha HTTP integration tests

## Choose the smallest useful run

```powershell
./scripts/verify.ps1                                      # default: quick, no Docker
./scripts/verify.ps1 -Mode frontend                       # frontend checks + production bundle
./scripts/verify.ps1 -Mode backend -Tests tests/test_review_workflow.py
./scripts/verify.ps1 -Mode backend -Tests 'tests/test_transports.py::test_polling_fallback_survives_more_than_sixteen_persisted_events'
./scripts/verify.ps1 -Mode full                           # complete release verification
```

Quick runs all frontend regressions, i18n and TypeScript alongside Python tests that do not need a live service. The `integration` selection label follows transitive `api`/`database` fixtures and the production transport cases; it does not skip anything in a full run. New tests that contact services directly must use that marker. Frontend mode also builds the Vite bundle. Backend mode builds current images and runs the selected real-storage tests; without selectors it runs the complete backend suite and authentication. Full additionally runs frontend checks and the proxy DNS regression. Full rejects selectors so a narrowed run cannot pass as a release gate.

For an even narrower frontend loop use `npm --prefix frontend run test:requests`, or `npm --prefix frontend test -- scripts/test-session-cache.mjs`. `npm --prefix frontend run check` runs all frontend checks in bounded parallel processes. `npm --prefix frontend run verify` adds the bundle. `npm --prefix frontend run build` only typechecks and packages: Docker does not repeat the state/render tests already required by CI.

Each local run writes stage logs, XML and timings under its own ignored `artifacts/verification-<profile>-<run-id>/`, plus `artifacts/verification-<profile>-latest.json`. Partial reports explicitly have `full_verification: false`; successful test results are not reused as a cache. A checkout lock prevents overlapping runs from racing shared images, QA services or TypeScript output. Environment settings stay in subprocesses. Images are built once and reused by both isolated realms and all three backend roles. Existing services/volumes are preserved; unchanged Docker layers stay cached.

Tests stop at the first failure. Stages have deadlines; a hung stage stops its owned process tree, records failure and releases the checkout lock. Infrastructure commands only target the named QA/smoke stacks. CI also caches Docker layers across runners and runs once per PR update, then again on a main push for the exact release revision; feature-branch push duplicates are removed. Use workflow dispatch for a branch without a PR.

The full local run and both CI jobs remain mandatory before a release: all integration cases, six production transports, demo-free authentication, no failures/errors/skips, and proxy recovery. No path filter or successful quick run bypasses these gates.

## Run integration tests directly

Run the actual backend, PostgreSQL and Redis before running this suite. Integration checks never substitute SQLite for PostgreSQL. Launch-operation unit checks mock GitHub responses to exercise fail-closed policy; live GitHub integration remains an external launch check.

Install from the repository root; the test requirements include the editable backend package so launch-operation tests use exactly the application's pinned dependencies.

```powershell
python -m pip install -r tests/requirements.txt
$env:CFG_TEST_BASE_URL = 'http://127.0.0.1:8110'
$env:DATABASE_URL = 'postgresql+psycopg://cfg:cfg-local@127.0.0.1:55472/cfg'
$env:CFG_TEST_REDIS_URL = 'redis://127.0.0.1:56382/0'
$env:CFG_PRODUCTION_BASE_URL = 'http://127.0.0.1:5380'
python -m pytest tests -v
```

QA fixture tests refuse to run against a backend with demo mode disabled. Each run creates a separate demo project and unique QA accounts/tasks. Existing application data is not deleted or modified. Direct database access creates and adjusts isolated QA fixtures; behavior assertions use HTTP, the real MCP transport, or Socket.IO. Separate production smoke checks use the optional local-only production URL to verify registration, CSRF, scoped credentials, OAuth PKCE and WebSocket proxying with fresh accounts.

The examples above target the separate QA Compose profile (`-p cfg-qa -f compose.yaml -f deploy/qa.override.yaml`), keeping generated fixtures out of the showcase database. Standard local development ports remain 8010/55471/56381; select them explicitly only when testing that development catalog is intended.

Local webhook signing uses `CFG_TEST_WEBHOOK_SECRET` or the documented demo secret. Configure that test variable if the server uses another local value; never put production credentials in this repository.

Tests intentionally leave their isolated QA fixtures available for inspecting a failed scenario. The fixture prefix is `qa-` followed by a unique run ID. Passing this suite verifies the local demo alpha, not production GitHub OAuth, a live repository's provenance, two real MCP hosts, public deployment, or external maintainer approval.

Socket.IO checks cover polling with the standard 16-packet decoder limit, a forty-event persisted burst delivered as metadata batches, and WebSocket through the production Caddy/nginx proxy. Payload assertions reject fields beyond public event IDs, kinds and entity IDs.

## Improvement and stabilization cycle

Before changing behavior, record the failure mechanism, the expected observable result and the rejection criterion. Reproduce the failure with the cheapest meaningful check, then run the focused regressions and the frontend build. Use the real-storage suite when backend or transport behavior is affected; deployment needs its own release checks. Keep evidence from an unchanged component instead of repeating its full suite without a new reason.

Browser request and session regressions run with `npm --prefix frontend run test:requests`. They exercise delayed responses, response-body timeouts, cancellation and account transitions using the actual API adapter and QueryClient. `npm --prefix frontend run verify` also checks private sprint cache isolation, route rendering, translations, TypeScript and the production bundle.

Record decisions in the existing audit documents: hypothesis, evidence, implementation status, decision, limits and what should not be repeated without new evidence. Keep source revision or hashes and logs in ignored `artifacts/`; never record cookies, credentials, environment secrets or private response payloads. Separate local verification from production verification. Passing checks establishes the tested behavior, not a measured increase in contribution acceptance or host capacity.

For performance or product experiments, define the metric and cohorts in advance, estimate baseline variability, and compare candidate and control under matching conditions. A single latency sample or model verdict cannot establish an improvement. Feature flags are useful for uncertain behavioral experiments; deterministic correctness fixes do not need an optional broken mode.
