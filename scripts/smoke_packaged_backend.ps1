param(
  [string]$BackendPath = (Join-Path $PSScriptRoot '..\.build\backend-dist\local-agent-backend\local-agent-backend.exe')
)

$ErrorActionPreference = 'Stop'
$port = Get-Random -Minimum 20000 -Maximum 40000
$token = [Guid]::NewGuid().ToString('N')
$dataDir = Join-Path ([IO.Path]::GetTempPath()) ("local-agent-studio-smoke-" + [Guid]::NewGuid().ToString('N'))
$headers = @{ 'x-studio-token' = $token }
$process = $null

function Invoke-StudioJson {
  param([string]$Method, [string]$Path, $Body)
  $arguments = @{ Method = $Method; Uri = "http://127.0.0.1:$port$Path"; Headers = $headers }
  if ($null -ne $Body) {
    $arguments.ContentType = 'application/json'
    $arguments.Body = $Body | ConvertTo-Json -Depth 20 -Compress
  }
  Invoke-RestMethod @arguments
}

try {
  New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
  $smokeDirectory = Join-Path $dataDir 'backend'
  Copy-Item -LiteralPath (Split-Path (Resolve-Path $BackendPath)) -Destination $smokeDirectory -Recurse
  $smokeExecutable = Join-Path $smokeDirectory 'local-agent-backend.exe'
  $process = Start-Process -FilePath $smokeExecutable -ArgumentList @(
    '--host', '127.0.0.1', '--port', "$port", '--data-dir', $dataDir, '--auth-token', $token
  ) -PassThru -WindowStyle Hidden

  $healthy = $false
  for ($attempt = 0; $attempt -lt 80; $attempt++) {
    try {
      $health = Invoke-StudioJson -Method GET -Path '/health'
      if ($health.status -eq 'ok') { $healthy = $true; break }
    } catch { Start-Sleep -Milliseconds 100 }
  }
  if (-not $healthy) { throw 'The packaged backend did not become healthy.' }

  $providers = Invoke-StudioJson -Method GET -Path '/api/providers'
  foreach ($requiredProvider in @('gemini', 'llama_cpp', 'ollama', 'lm_studio')) {
    if ($requiredProvider -notin $providers.id) { throw "Packaged provider missing: $requiredProvider" }
  }
  $models = Invoke-StudioJson -Method GET -Path '/api/models'
  $ollama = $providers | Where-Object id -eq 'ollama'
  $lmStudio = $providers | Where-Object id -eq 'lm_studio'

  $tools = Invoke-StudioJson -Method GET -Path '/api/tools'
  foreach ($required in @('read_file', 'create_word', 'create_excel', 'send_email')) {
    if ($required -notin $tools.id) { throw "Packaged tool missing: $required" }
  }

  $workflow = Invoke-StudioJson -Method POST -Path '/api/workflows' -Body @{
    name = 'Packaged document smoke test'
    description = 'Exercises approval-gated Word and Excel creation.'
    spec = @{
      version = '1.0'; limits = @{ max_iterations = 2; timeout_seconds = 30 }
      nodes = @(
        @{ id = 'input'; type = 'input'; label = 'Input'; position = @{}; config = @{} },
        @{ id = 'word'; type = 'function'; label = 'Word'; position = @{}; config = @{ tool_id = 'create_word'; arguments = @{ path = 'smoke/report.docx'; title = 'Smoke test'; content = '$input' } } },
        @{ id = 'excel'; type = 'function'; label = 'Excel'; position = @{}; config = @{ tool_id = 'create_excel'; arguments = @{ path = 'smoke/report.xlsx'; sheet_name = 'Results'; data = '[{"status":"ok"}]' } } },
        @{ id = 'output'; type = 'output'; label = 'Output'; position = @{}; config = @{} }
      )
      edges = @(
        @{ id = 'e1'; source = 'input'; target = 'word' },
        @{ id = 'e2'; source = 'word'; target = 'excel' },
        @{ id = 'e3'; source = 'excel'; target = 'output' }
      )
    }
  }
  $run = Invoke-StudioJson -Method POST -Path "/api/workflows/$($workflow.id)/run" -Body @{ input = 'Created by the packaged backend.' }

  foreach ($expectedTool in @('create_word', 'create_excel')) {
    $waiting = $null
    for ($attempt = 0; $attempt -lt 100; $attempt++) {
      $waiting = Invoke-StudioJson -Method GET -Path "/api/runs/$($run.id)"
      if ($waiting.status -eq 'waiting_approval') { break }
      if ($waiting.status -eq 'failed') { throw $waiting.error }
      Start-Sleep -Milliseconds 50
    }
    if ($waiting.state.pending_approval.tool_id -ne $expectedTool) {
      throw "Expected approval for $expectedTool."
    }
    Invoke-StudioJson -Method POST -Path "/api/runs/$($run.id)/approval" -Body @{ approved = $true; response = '' } | Out-Null
  }

  for ($attempt = 0; $attempt -lt 100; $attempt++) {
    $completed = Invoke-StudioJson -Method GET -Path "/api/runs/$($run.id)"
    if ($completed.status -in @('completed', 'failed')) { break }
    Start-Sleep -Milliseconds 50
  }
  if ($completed.status -ne 'completed') { throw $completed.error }

  $word = Join-Path $dataDir 'workspace\smoke\report.docx'
  $excel = Join-Path $dataDir 'workspace\smoke\report.xlsx'
  if (-not (Test-Path $word) -or -not (Test-Path $excel)) { throw 'Packaged document files were not created.' }
  Invoke-StudioJson -Method DELETE -Path "/api/workflows/$($workflow.id)" | Out-Null
  Write-Output ([PSCustomObject]@{
    version = $health.version
    providers = $providers.Count
    ollama_available = $ollama.available
    ollama_models = @($models | Where-Object provider_id -eq 'ollama').Count
    lm_studio_available = $lmStudio.available
    lm_studio_detail = $lmStudio.detail
    tools = $tools.Count
    workflow_status = $completed.status
    word_bytes = (Get-Item $word).Length
    excel_bytes = (Get-Item $excel).Length
  })
} finally {
  if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
  Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($dataDir, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
  $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
  $resolvedData = [IO.Path]::GetFullPath($dataDir)
  if ($resolvedData.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path $resolvedData)) {
    try { Remove-Item -LiteralPath $resolvedData -Recurse -Force } catch {
      Write-Warning "Smoke-test files remain in the temporary folder and can be removed after the child process exits."
    }
  }
}
