param([string]$Destination = (Join-Path $env:LOCALAPPDATA 'gripeline'))
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $Destination | Out-Null
'gripeline.py','gripeline.cmd','gripeline.ps1' | ForEach-Object {
    Copy-Item (Join-Path $PSScriptRoot $_) (Join-Path $Destination $_) -Force
}
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($Destination -notin ($userPath -split ';')) {
    [Environment]::SetEnvironmentVariable('Path', "$Destination;$userPath", 'User')
}
Write-Host "Installed gripeline in $Destination. Open a new terminal to use it. Requires Python and Git Bash."
