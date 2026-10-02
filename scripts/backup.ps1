param([switch]$Production)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$composeArgs = @('-f', 'compose.yaml')
if ($Production) { $composeArgs = @('--env-file', '.env.production', '-f', 'compose.production.yaml') }
$backupDirectory = Join-Path $root 'artifacts/backups'
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$filename = 'cfg-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump'
# Write binary inside the container, then docker cp: PowerShell text redirection can corrupt pg_dump -Fc.
docker compose @composeArgs exec -T postgres pg_dump -U cfg -d cfg -Fc -f /tmp/cfg-backup.dump
if ($LASTEXITCODE -ne 0) { throw 'Database backup failed.' }
$containerId = docker compose @composeArgs ps -q postgres
if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw 'Postgres container not found.' }
$destination = Join-Path $backupDirectory $filename
docker cp "${containerId}:/tmp/cfg-backup.dump" $destination
if ($LASTEXITCODE -ne 0) { throw 'Could not copy database backup.' }
Write-Host "Database backup saved to $destination. Keep an encrypted off-host copy."
