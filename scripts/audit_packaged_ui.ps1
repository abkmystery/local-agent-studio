param(
  [string]$AppPath = (Join-Path $PSScriptRoot '..\release\win-unpacked\Local Agent Studio.exe'),
  [string]$BackendPath = (Join-Path $PSScriptRoot '..\.build\backend-dist\local-agent-backend\local-agent-backend.exe'),
  [string]$Screenshot = (Join-Path ([IO.Path]::GetTempPath()) 'local-agent-studio-ui-audit.png')
)

$ErrorActionPreference = 'Stop'
$apiPort = Get-Random -Minimum 20000 -Maximum 30000
$debugPort = Get-Random -Minimum 30001 -Maximum 40000
$token = [Guid]::NewGuid().ToString('N')
$dataDir = Join-Path ([IO.Path]::GetTempPath()) ("local-agent-studio-ui-" + [Guid]::NewGuid().ToString('N'))
$headers = @{ 'x-studio-token' = $token }
$backend = $null
$desktop = $null
$socket = $null
$script:cdpId = 0
$checks = [Collections.Generic.List[string]]::new()
$started = Get-Date
$resolvedAppDirectory = Split-Path ([IO.Path]::GetFullPath($AppPath))

function Invoke-StudioJson {
  param([string]$Method, [string]$Path, $Body)
  $arguments = @{ Method = $Method; Uri = "http://127.0.0.1:$apiPort$Path"; Headers = $headers }
  if ($null -ne $Body) {
    $arguments.ContentType = 'application/json'
    $arguments.Body = $Body | ConvertTo-Json -Depth 20 -Compress
  }
  Invoke-RestMethod @arguments
}

function Invoke-Cdp {
  param([string]$Method, [hashtable]$Params = @{})
  $script:cdpId++
  $id = $script:cdpId
  $payload = [Text.Encoding]::UTF8.GetBytes((@{ id = $id; method = $Method; params = $Params } | ConvertTo-Json -Compress -Depth 12))
  $socket.SendAsync([ArraySegment[byte]]::new($payload), [Net.WebSockets.WebSocketMessageType]::Text, $true, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
  while ($true) {
    $stream = [IO.MemoryStream]::new()
    do {
      $buffer = New-Object byte[] 65536
      $timeout = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(15))
      try {
        $received = $socket.ReceiveAsync([ArraySegment[byte]]::new($buffer), $timeout.Token).GetAwaiter().GetResult()
      } finally { $timeout.Dispose() }
      $stream.Write($buffer, 0, $received.Count)
    } until ($received.EndOfMessage)
    $message = [Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
    if ($message.id -eq $id) {
      if ($message.error) { throw $message.error.message }
      return $message.result
    }
  }
}

function Invoke-Page {
  param([string]$Expression)
  $result = Invoke-Cdp 'Runtime.evaluate' @{ expression = $Expression; returnByValue = $true; awaitPromise = $true }
  if ($result.exceptionDetails) { throw $result.exceptionDetails.text }
  $result.result.value
}

function Wait-PageText {
  param([string]$Text, [int]$Seconds = 12)
  $escaped = $Text | ConvertTo-Json -Compress
  $limit = [DateTime]::UtcNow.AddSeconds($Seconds)
  do {
    if (Invoke-Page "document.body.innerText.includes($escaped)") { return }
    Start-Sleep -Milliseconds 100
  } while ([DateTime]::UtcNow -lt $limit)
  throw "Timed out waiting for visible text: $Text"
}

function Click-Button {
  param([string]$Text)
  $escaped = $Text | ConvertTo-Json -Compress
  $clicked = Invoke-Page "(() => { const item = Array.from(document.querySelectorAll('button')).find((button) => button.textContent.trim() === $escaped || button.textContent.includes($escaped)); if (!item) return false; item.click(); return true; })()"
  if (-not $clicked) { throw "Button not found: $Text" }
}

function Check-Screen {
  param([string]$Navigation, [string]$Heading)
  Click-Button $Navigation
  Wait-PageText $Heading
  $checks.Add($Navigation) | Out-Null
}

try {
  New-Item -ItemType Directory -Force -Path (Join-Path $dataDir 'models') | Out-Null
  [IO.File]::WriteAllBytes((Join-Path $dataDir 'models\qa.gguf'), [byte[]]@())
  $seedBackendDirectory = Join-Path $dataDir 'seed-backend'
  Copy-Item -LiteralPath (Split-Path (Resolve-Path $BackendPath)) -Destination $seedBackendDirectory -Recurse
  $seedBackendExecutable = Join-Path $seedBackendDirectory 'local-agent-backend.exe'
  $backend = Start-Process -FilePath $seedBackendExecutable -ArgumentList @(
    '--host', '127.0.0.1', '--port', "$apiPort", '--data-dir', $dataDir, '--auth-token', $token
  ) -PassThru -WindowStyle Hidden
  for ($attempt = 0; $attempt -lt 80; $attempt++) {
    try { if ((Invoke-StudioJson GET '/health').status -eq 'ok') { break } } catch { Start-Sleep -Milliseconds 100 }
  }
  Invoke-StudioJson PUT '/api/settings' @{ onboarding_complete = $true } | Out-Null
  $agent = Invoke-StudioJson POST '/api/agents' @{
    name = 'QA Writer'; description = 'UI audit agent'; provider_id = 'llama_cpp'; model_id = 'qa.gguf'
    instructions = 'Write concise test output.'; config = @{ temperature = 0.2; num_ctx = 4096; num_predict = 64 }
  }
  $runWorkflow = Invoke-StudioJson POST '/api/workflows' @{
    name = 'Run visibility'; description = 'Completed run for the Runs screen.'
    spec = @{ version = '1.0'; limits = @{ max_iterations = 2; timeout_seconds = 30 }; nodes = @(
      @{ id = 'input'; type = 'input'; label = 'Input'; position = @{ x = 80; y = 160 }; config = @{} },
      @{ id = 'output'; type = 'output'; label = 'Output'; position = @{ x = 430; y = 160 }; config = @{} }
    ); edges = @(@{ id = 'e1'; source = 'input'; target = 'output' }) }
  }
  $run = Invoke-StudioJson POST "/api/workflows/$($runWorkflow.id)/run" @{ input = 'Visible completed run' }
  for ($attempt = 0; $attempt -lt 50; $attempt++) {
    $runState = Invoke-StudioJson GET "/api/runs/$($run.id)"
    if ($runState.status -eq 'completed') { break }
    Start-Sleep -Milliseconds 50
  }
  Invoke-StudioJson POST '/api/workflows' @{
    name = 'Delete me'; description = 'Used to verify deletion.'
    spec = @{ version = '1.0'; limits = @{ max_iterations = 2; timeout_seconds = 30 }; nodes = @(
      @{ id = 'input'; type = 'input'; label = 'Input'; position = @{ x = 80; y = 160 }; config = @{} },
      @{ id = 'output'; type = 'output'; label = 'Output'; position = @{ x = 430; y = 160 }; config = @{} }
    ); edges = @(@{ id = 'e1'; source = 'input'; target = 'output' }) }
  } | Out-Null
  Stop-Process -Id $backend.Id -Force
  Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($seedBackendDirectory, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
  $backend = $null

  $desktop = Start-Process -FilePath (Resolve-Path $AppPath) -ArgumentList @(
    "--user-data-dir=$dataDir", "--remote-debugging-port=$debugPort"
  ) -PassThru -WindowStyle Hidden
  $target = $null
  # Electron waits for the one-file backend to extract before creating the renderer.
  # Slower disks can legitimately need more than the first-run 12 seconds.
  for ($attempt = 0; $attempt -lt 450; $attempt++) {
    try { $target = Invoke-RestMethod "http://127.0.0.1:$debugPort/json/list" | Where-Object type -eq 'page' | Select-Object -First 1 } catch {}
    if ($target) { break }
    Start-Sleep -Milliseconds 100
  }
  if (-not $target) { throw 'Electron renderer debugging target did not appear.' }
  $socket = [Net.WebSockets.ClientWebSocket]::new()
  $socket.ConnectAsync([Uri]$target.webSocketDebuggerUrl, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
  Invoke-Cdp 'Page.enable' | Out-Null
  Wait-PageText 'Build useful local workflows' 15
  Invoke-Page "window.__qaErrors=[]; window.addEventListener('error', event => window.__qaErrors.push(event.message)); true" | Out-Null
  $checks.Add('Home') | Out-Null

  Check-Screen 'Models' 'Models'
  Check-Screen 'Agents' 'Agents'
  Click-Button 'New agent'
  Wait-PageText 'Skill files'
  Wait-PageText 'Agent permissions'
  if (-not (Invoke-Page "Boolean(document.querySelector('input[type=file][accept*=\".md\"]'))")) { throw 'Agent skill-file picker is missing.' }
  Invoke-Page "document.querySelector('button[aria-label=\"Close\"]').click(); true" | Out-Null
  $checks.Add('Agent modal and skill picker') | Out-Null

  Check-Screen 'Workflows' 'Workflows'
  Wait-PageText 'Delete me'
  Click-Button 'Router'
  Invoke-Page "document.querySelector('.react-flow__node.type-router').click(); true" | Out-Null
  Wait-PageText 'Text rules'
  Click-Button 'Add text rule'
  if (-not (Invoke-Page "Boolean(document.querySelector('.router-rule input'))")) { throw 'Router rule editor did not add a rule.' }
  Click-Button 'Function'
  Invoke-Page "document.querySelector('.react-flow__node.type-function').click(); true" | Out-Null
  Wait-PageText 'Create Word document'
  $functionOptions = Invoke-Page "Array.from(document.querySelectorAll('.inspector select option')).map(item => item.textContent).join('|')"
  foreach ($tool in @('Create Word document', 'Create Excel workbook', 'Send email')) {
    if (-not $functionOptions.Contains($tool)) { throw "Function picker is missing $tool" }
  }
  foreach ($developerTool in @('Python code — setup required', 'MCP server tool — setup required')) {
    if (-not $functionOptions.Contains($developerTool)) { throw "Function picker is missing gated option: $developerTool" }
  }
  if (-not (Invoke-Page "Boolean(document.querySelector('.run-composer input[type=file][accept*=\".png\"]'))")) { throw 'Workflow attachment picker is missing.' }
  if (-not (Invoke-Page "Boolean(document.querySelector('.local-path-row textarea'))")) { throw 'Approved local-path input is missing.' }
  Invoke-Page "window.confirm=()=>true; true" | Out-Null
  Click-Button 'Delete'
  Wait-PageText 'Workflow deleted.'
  Wait-PageText 'Run visibility'
  $checks.Add('Workflow editor, router, tools, and delete') | Out-Null

  Check-Screen 'Runs' 'Runs'
  Wait-PageText 'Visible completed run'
  Wait-PageText '2/2 complete'
  $checks.Add('Completed run inspector') | Out-Null
  Check-Screen 'Resources' 'Resource dashboard'
  Check-Screen 'Settings' 'Email for workflows'
  Wait-PageText 'Studio capabilities'
  Wait-PageText 'Python functions'
  Wait-PageText 'Local MCP servers'
  $providerOptions = Invoke-Page "Array.from(document.querySelectorAll('.email-settings select option')).map(item => item.value).join('|')"
  if ($providerOptions -ne 'gmail|outlook|yahoo|custom') { throw 'Email provider choices are incomplete.' }
  Invoke-Page "(() => { const select=document.querySelector('.email-settings select'); select.value='custom'; select.dispatchEvent(new Event('change',{bubbles:true})); return true; })()" | Out-Null
  Wait-PageText 'SMTP server'
  $checks.Add('Email settings and custom SMTP') | Out-Null

  Click-Button 'Restart guide'
  Wait-PageText 'Your agent studio, without the setup maze' 15
  Click-Button 'Choose how your agents think'
  Wait-PageText 'Pick an AI provider'
  $providerCards = Invoke-Page "document.querySelectorAll('.provider-choice-grid > button').length"
  if ($providerCards -ne 4) { throw "Expected four provider choices, found $providerCards" }
  $chooseDisabled = Invoke-Page "Array.from(document.querySelectorAll('button')).find(button => button.textContent.includes('Choose a model')).disabled"
  if (-not $chooseDisabled) { throw 'Provider setup continued without a required selection.' }
  $checks.Add('Restart guide and provider gate') | Out-Null

  $capture = Invoke-Cdp 'Page.captureScreenshot' @{ format = 'png'; fromSurface = $true; captureBeyondViewport = $false }
  [IO.File]::WriteAllBytes($Screenshot, [Convert]::FromBase64String($capture.data))
  $errors = Invoke-Page "window.__qaErrors"
  if ($errors.Count -gt 0) { throw ("Renderer errors: " + ($errors -join '; ')) }
  if (Invoke-Page "document.body.innerText.includes('â')") { throw 'Mojibake was detected in visible text.' }

  Write-Output ([PSCustomObject]@{
    checks = $checks.Count
    screens = ($checks -join ', ')
    duration_seconds = [Math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    screenshot = $Screenshot
  })
} finally {
  if ($socket) { $socket.Dispose() }
  if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
  if ($desktop -and -not $desktop.HasExited) { Stop-Process -Id $desktop.Id -Force }
  Get-Process 'Local Agent Studio','local-agent-backend' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and ([IO.Path]::GetFullPath($_.Path).StartsWith($resolvedAppDirectory, [StringComparison]::OrdinalIgnoreCase) -or $_.Path -like "$dataDir*") } |
    Stop-Process -Force -ErrorAction SilentlyContinue
  $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
  $resolvedData = [IO.Path]::GetFullPath($dataDir)
  if ($resolvedData.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path $resolvedData)) {
    Start-Sleep -Milliseconds 500
    try { Remove-Item -LiteralPath $resolvedData -Recurse -Force } catch {
      Write-Warning "UI-audit files remain in the temporary folder and can be removed after Electron releases them."
    }
  }
}
