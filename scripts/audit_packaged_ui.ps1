param(
  [string]$PythonPath = $env:LOCAL_AGENT_PYTHON
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) { $PythonPath = Join-Path $root '.venv\Scripts\python.exe' }
if (-not (Test-Path $PythonPath)) {
  throw 'Create the project virtual environment or set LOCAL_AGENT_PYTHON before running the packaged UI audit.'
}

& $PythonPath (Join-Path $PSScriptRoot 'audit_packaged_ui.py')
exit $LASTEXITCODE
