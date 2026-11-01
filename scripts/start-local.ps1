$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$env:PYTHONPATH = Join-Path $root "src"
Start-Process -FilePath (Join-Path $root ".venv\Scripts\python.exe") -ArgumentList "-m","ark_hr.api" -WorkingDirectory $root
Set-Location (Join-Path $root "web")
npm run dev
