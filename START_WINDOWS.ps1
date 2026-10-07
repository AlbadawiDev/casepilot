param([ValidateRange(1,65535)][int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot '.runtime'
$statePath = Join-Path $runtimeRoot "server-$Port.json"
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonPath = (& $pythonCommand.Source -3 -c 'import sys; print(sys.executable)')
} else {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}
& $pythonPath -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 o superior es necesario.' }
if (-not $env:CASEPILOT_DB) { $env:CASEPILOT_DB = Join-Path $projectRoot 'data\demo.sqlite3' }
$env:CASEPILOT_HOST = '127.0.0.1'
$env:PORT = [string]$Port
$url = "http://127.0.0.1:$Port"
try {
    $existingHealth = Invoke-RestMethod "$url/api/health" -TimeoutSec 2
    if ($existingHealth.service -ne 'CasePilot') { throw 'El puerto pertenece a otra aplicacion.' }
    Write-Host "CasePilot ya esta disponible: $url"
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
} catch {
    if ($_.Exception.Message -eq 'El puerto pertenece a otra aplicacion.') { throw }
}
$process = Start-Process -FilePath $pythonPath -ArgumentList @('-u', 'main.py') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot "server-$Port.stdout.log") -RedirectStandardError (Join-Path $runtimeRoot "server-$Port.stderr.log")
[pscustomobject]@{id=$process.Id; startedTicks=[string]$process.StartTime.ToUniversalTime().Ticks; executable=$pythonPath; project=$projectRoot; port=$Port} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if ($process.HasExited) { throw "No se pudo iniciar CasePilot. Revisa $runtimeRoot\server-$Port.stderr.log" }
    try {
        $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 1
        if ($health.service -eq 'CasePilot') {
            Write-Host "CasePilot disponible: $url"
            Write-Host "Para detenerlo: .\STOP_WINDOWS.ps1 -Port $Port"
            if (-not $NoBrowser) { Start-Process $url }
            exit 0
        }
    } catch { Start-Sleep -Milliseconds 250 }
}
throw "No se confirmo el inicio. Revisa $runtimeRoot\server-$Port.stderr.log"
