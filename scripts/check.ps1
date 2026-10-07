$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $env:CASEPILOT_QUIET = '1'
    python -m py_compile main.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (Get-Command node -ErrorAction SilentlyContinue) {
        node --check static/app.js
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        node --test tests/frontend.test.cjs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    python -W error::ResourceWarning -m unittest discover -s tests -v
    exit $LASTEXITCODE
} finally { Pop-Location }
