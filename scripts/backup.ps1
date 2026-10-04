param([switch]$Production, [string]$Project)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$composeArgs = @('-f', 'compose.yaml')
if ($Production) { $composeArgs = @('--env-file', '.env.production', '-f', 'compose.production.yaml') }
if ($Project) { $composeArgs = @('-p', $Project) + $composeArgs }
$backupDirectory = Join-Path $root 'artifacts/backups'
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$backupId = [guid]::NewGuid().ToString('N')
$filename = 'cfg-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $backupId + '.dump'
$containerPath = '/tmp/cfg-backup-' + $backupId + '.dump'
# Write binary inside the container, then docker cp: PowerShell text redirection can corrupt pg_dump -Fc.
try {
    docker compose @composeArgs exec -T postgres pg_dump -U cfg -d cfg -Fc -f $containerPath
    if ($LASTEXITCODE -ne 0) { throw 'Database backup failed.' }
    docker compose @composeArgs exec -T postgres pg_restore --list $containerPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Invalid database backup archive.' }
    $expectedHash = docker compose @composeArgs exec -T postgres sha256sum $containerPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not hash database backup.' }
    $containerId = docker compose @composeArgs ps -q postgres
    if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw 'Postgres container not found.' }
    $destination = Join-Path $backupDirectory $filename
    docker cp "${containerId}:$containerPath" $destination
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy database backup.' }
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne ($expectedHash -split '\s+')[0]) {
        throw 'Copied database backup checksum differs.'
    }
    Write-Host "Validated database backup saved to $destination. Keep an encrypted off-host copy."
} finally {
    docker compose @composeArgs exec -T postgres rm -f $containerPath
}
