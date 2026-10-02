param([Parameter(Mandatory=$true)][string]$PublicHost)
$ErrorActionPreference = 'Stop'
if ($PublicHost -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.-]+[a-zA-Z0-9]$' -or $PublicHost -notmatch '\.') { throw 'Supply a public DNS hostname, without a URL or port.' }
$root = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $root '.env.production'
if (Test-Path -LiteralPath $destination) { throw '.env.production already exists. Preserve its secrets; edit it directly.' }
function New-PrivateSecret { $bytes = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '') }
$databasePassword = New-PrivateSecret
$webhookSecret = New-PrivateSecret
$oauthBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($oauthBytes)
$oauthKey = [Convert]::ToBase64String($oauthBytes).Replace('+', '-').Replace('/', '_')
$content = @"
PUBLIC_HOST=$PublicHost
PUBLIC_URL=https://$PublicHost
SECURE_COOKIES=true
REGISTRATION_ENABLED=true
POSTGRES_PASSWORD=$databasePassword
GITHUB_WEBHOOK_SECRET=$webhookSecret
OAUTH_SECRET_KEY=$oauthKey
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GITHUB_TOKEN=
"@
[System.IO.File]::WriteAllText($destination, $content, (New-Object System.Text.UTF8Encoding($false)))
Write-Host 'Created private .env.production. Keep it on the deployment host. Secret values were not printed.'
