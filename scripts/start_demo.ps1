param(
    [ValidateSet("Web", "Webcam", "Check")]
    [string]$Mode = "Web",
    [int]$Camera = 0
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
# Store Python can redirect Local AppData. Ask the interpreter for its actual directory.
$runtime = & py -3.11 -c "import os; from pathlib import Path; print((Path(os.environ['LOCALAPPDATA']) / 'FaceID-SmartDoorRuntime').resolve())"
if ($LASTEXITCODE -ne 0 -or -not $runtime) { throw "Install Python 3.11 and its Windows launcher." }
$python = Join-Path $runtime "venv/Scripts/python.exe"
$stamp = Join-Path $runtime "requirements.sha256"

function Run-Python {
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "Python exited with code $LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath $python)) {
    & py -3.11 -m venv (Join-Path $runtime "venv")
    if ($LASTEXITCODE -ne 0) { throw "Install Python 3.11 and its Windows launcher." }
}
$expected = (Get-FileHash -LiteralPath "requirements-smartdoor.txt" -Algorithm SHA256).Hash
if (-not (Test-Path -LiteralPath $stamp) -or (Get-Content -Raw -LiteralPath $stamp).Trim() -ne $expected) {
    Run-Python -m pip install -r requirements-smartdoor.txt
    Set-Content -LiteralPath $stamp -Value $expected
}
$env:PYTHONUTF8 = "1"
& $python -c "from smartdoor.storage import data_directory; from smartdoor.vision import Vision; Vision(data_directory() / 'models').load()" 2>$null
if ($LASTEXITCODE -ne 0) { Run-Python -m smartdoor.models }
if ($Mode -eq "Check") {
    Run-Python -c "from smartdoor.server import app; from smartdoor.storage import data_directory; from smartdoor.vision import Vision; Vision(data_directory() / 'models').load(); print(app.title, 'OK', data_directory())"
    exit 0
}
& $python -c "from smartdoor.storage import Store,data_directory; s=Store(data_directory()); c=s.engine.raw_connection(); print(s.folder); raise SystemExit(0 if c.driver_connection.execute('select 1 from accounts limit 1').fetchone() else 1)"
if ($LASTEXITCODE -ne 0) { Run-Python -m smartdoor.setup }
if ($Mode -eq "Webcam") {
    Run-Python -m smartdoor.simulator --camera $Camera
} else {
    Write-Host "Smart Door: http://127.0.0.1:8000"
    Run-Python scripts/run_web.py
}
