$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    docker compose up --build -d --wait --wait-timeout 180
    if ($LASTEXITCODE -ne 0) { throw 'Local alpha failed to start. Run docker compose logs --tail 100.' }
    Write-Host 'ComputeForGood: http://127.0.0.1:5180'
    Write-Host 'API health: http://127.0.0.1:8010/api/health'
    Write-Host 'MCP: http://127.0.0.1:8010/mcp'
} finally {
    Pop-Location
}
