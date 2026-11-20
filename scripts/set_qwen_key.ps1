$ErrorActionPreference = 'Stop'
$folder = Join-Path $env:LOCALAPPDATA 'RobotSorting'
$credential = Read-Host 'Enter your Qianwen API Key' -AsSecureString
if ($credential.Length -eq 0) {
    throw 'API Key cannot be empty.'
}
New-Item -Path $folder -ItemType Directory -Force | Out-Null
ConvertFrom-SecureString $credential | Set-Content -LiteralPath (Join-Path $folder 'qwen-key.dpapi') -Encoding ASCII
$credential.Dispose()
Write-Host 'API Key saved with Windows user encryption.'
