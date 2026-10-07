param([ValidateRange(1,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$statePath = Join-Path $PSScriptRoot ".runtime\server-$Port.json"
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'No hay un servidor iniciado por este lanzador.'; exit 0 }
$serverState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$serverProcess = Get-Process -Id $serverState.id -ErrorAction SilentlyContinue
if (-not $serverProcess) { Write-Host 'El servidor ya esta detenido.'; exit 0 }
$serverCommand = Get-CimInstance Win32_Process -Filter "ProcessId = $($serverState.id)"
if ($serverProcess.Path -ne $serverState.executable -or $serverProcess.StartTime.ToUniversalTime().Ticks -ne [long]$serverState.startedTicks -or $serverCommand.CommandLine -notmatch 'main\.py' -or $serverState.project -ne $PSScriptRoot) {
    throw 'La identidad del proceso cambio; no se detendra un proceso ajeno.'
}
Stop-Process -Id $serverProcess.Id
Write-Host 'CasePilot detenido. Los datos y registros se conservaron.'
