$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (Test-Path 'pnpm-lock.yaml') {
  pnpm install --frozen-lockfile
} else {
  Write-Warning 'pnpm-lock.yaml is missing; resolving dependencies once. Commit the generated lockfile before a production release.'
  pnpm install
}
python -m pip install -r backend/requirements.txt
pnpm typecheck
pnpm test
pnpm backend:test
& "$PSScriptRoot/generate_sbom.ps1"
pnpm package:win
