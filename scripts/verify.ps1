param(
    [ValidateSet('quick', 'frontend', 'backend', 'full')]
    [string]$Mode = 'quick',
    [string[]]$Tests = @()
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $verifyArguments = @('--mode', $Mode)
    if ($Tests.Count) { $verifyArguments += @('--tests') + $Tests }
    uv run --with-editable backend --with-requirements tests/requirements.txt python scripts/verify.py @verifyArguments
    if ($LASTEXITCODE -ne 0) { throw 'Verification failed; see the reported stage log.' }
} finally {
    Pop-Location
}
