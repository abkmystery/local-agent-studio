$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = if ($env:LOCAL_AGENT_PYTHON) { $env:LOCAL_AGENT_PYTHON } else { 'python' }

& $python -m pip list --format json | Out-File -Encoding utf8 sbom-python.json
& pnpm licenses list --json | Out-File -Encoding utf8 sbom-javascript.json
