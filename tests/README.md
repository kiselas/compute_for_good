# Local alpha HTTP integration tests

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
