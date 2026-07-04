$ErrorActionPreference = 'Stop'
$python = if ($env:LOCAL_AGENT_PYTHON) { $env:LOCAL_AGENT_PYTHON } else { 'python' }
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

& $python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --name local-agent-backend `
  --distpath .build/backend-dist `
  --workpath .build/pyinstaller `
  --specpath .build `
  --paths $root `
  --collect-all uvicorn `
  --collect-all fastapi `
  backend/launcher.py

if (-not (Test-Path '.build/backend-dist/local-agent-backend/local-agent-backend.exe')) {
  throw 'Backend bundling did not produce local-agent-backend.exe'
}
