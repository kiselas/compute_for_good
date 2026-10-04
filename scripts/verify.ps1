$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    uv run --with-editable backend python scripts/prepare-local-smoke.py
    if ($LASTEXITCODE -ne 0) { throw 'Local smoke configuration failed.' }
    docker compose -p cfg-qa -f compose.yaml -f deploy/qa.override.yaml up --build -d --wait postgres redis backend worker integration_worker frontend
    if ($LASTEXITCODE -ne 0) { throw 'Isolated QA services failed to start.' }
    docker compose -p cfg-production-smoke --env-file .env.production-smoke -f compose.production.yaml -f deploy/production-smoke.override.yaml up --build -d --wait --wait-timeout 240
    if ($LASTEXITCODE -ne 0) { throw 'Production transport smoke services failed to start.' }
    $env:CFG_TEST_BASE_URL = 'http://127.0.0.1:8110'
    $env:DATABASE_URL = 'postgresql+psycopg://cfg:cfg-local@127.0.0.1:55472/cfg'
    $env:REDIS_URL = 'redis://127.0.0.1:56382/0'
    $env:CFG_TEST_REDIS_URL = $env:REDIS_URL
    $env:DEMO_MODE = 'true'
    $env:CFG_TEST_WEBHOOK_SECRET = 'local-demo-webhook-secret'
    $env:CFG_PRODUCTION_BASE_URL = 'http://127.0.0.1:5380'
    uv run --with-editable backend --with-requirements tests/requirements.txt python -m pytest tests -v --junitxml=tests/artifacts/verification.xml
    if ($LASTEXITCODE -ne 0) { throw 'Integration verification failed.' }
    uv run --with-editable backend --with-requirements tests/requirements.txt python scripts/check-test-evidence.py tests/artifacts/verification.xml
    if ($LASTEXITCODE -ne 0) { throw 'Production checks were skipped or failed.' }
    uv run --with-editable backend --with-requirements tests/requirements.txt python scripts/verify-proxy-dns.py --project cfg-qa
    if ($LASTEXITCODE -ne 0) { throw 'Dynamic proxy DNS verification failed.' }
    uv run --with-editable backend --with-requirements tests/requirements.txt python scripts/verify-auth.py
    if ($LASTEXITCODE -ne 0) { throw 'Authentication verification failed.' }
} finally {
    Pop-Location
}
