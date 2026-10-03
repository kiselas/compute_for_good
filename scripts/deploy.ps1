$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath '.env.production')) { throw 'Run scripts/prepare-production.ps1 -PublicHost YOUR_DOMAIN first.' }
docker compose --env-file .env.production -f compose.production.yaml config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Production configuration is invalid.' }
docker compose --env-file .env.production -f compose.production.yaml up --build -d --wait --wait-timeout 180
if ($LASTEXITCODE -ne 0) { throw 'Deployment did not pass health checks. Inspect docker compose logs before launch.' }
docker compose --env-file .env.production -f compose.production.yaml exec -T backend python -c "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=5).status == 200"
if ($LASTEXITCODE -ne 0) { throw 'Storage or worker readiness failed. Inspect worker health before launch.' }
Write-Host 'Services are healthy. Complete the external HTTPS/MCP smoke checks in docs/production-runbook.md before sending advertising traffic.'
