$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    docker compose -p cfg-qa -f compose.yaml -f deploy/qa.override.yaml up --build -d --wait postgres redis backend worker integration_worker
    if ($LASTEXITCODE -ne 0) { throw 'Isolated QA services failed to start.' }
    $env:CFG_TEST_BASE_URL = 'http://127.0.0.1:8110'
    $env:DATABASE_URL = 'postgresql+psycopg://cfg:cfg-local@127.0.0.1:55472/cfg'
    $env:REDIS_URL = 'redis://127.0.0.1:56382/0'
    $env:CFG_TEST_REDIS_URL = $env:REDIS_URL
    $env:DEMO_MODE = 'true'
    $env:CFG_TEST_WEBHOOK_SECRET = 'local-demo-webhook-secret'
    uv run --with-editable backend --with-requirements tests/requirements.txt python -m pytest tests -v --junitxml=tests/artifacts/verification.xml
    if ($LASTEXITCODE -ne 0) { throw 'Integration verification failed.' }
    uv run --with-editable backend --with-requirements tests/requirements.txt python scripts/verify-auth.py
    if ($LASTEXITCODE -ne 0) { throw 'Authentication verification failed.' }
} finally {
    Pop-Location
}
