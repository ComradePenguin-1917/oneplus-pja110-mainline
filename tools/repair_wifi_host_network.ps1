$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$logPath = Join-Path $taskRoot 'out/wifi-bringup-20261017/host-network-repair.log'
try {
    & (Join-Path $PSScriptRoot 'configure_windows_ncm.ps1') -Persistent *> $logPath
} catch {
    $_ | Out-String | Add-Content -LiteralPath $logPath
    exit 1
}
