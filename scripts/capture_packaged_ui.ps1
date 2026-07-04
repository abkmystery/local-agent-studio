param(
  [int]$Port = 9333,
  [string]$Output = "$env:TEMP\local-agent-studio-qa.png",
  [switch]$Advance,
  [switch]$SelectGemini
)

$targets = Invoke-RestMethod "http://127.0.0.1:$Port/json/list"
$target = $targets | Where-Object { $_.type -eq 'page' } | Select-Object -First 1
if (-not $target) { throw 'No Electron renderer target was found.' }

$socket = [System.Net.WebSockets.ClientWebSocket]::new()
$socket.ConnectAsync([Uri]$target.webSocketDebuggerUrl, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
$script:messageId = 0

function Invoke-Cdp([string]$Method, [hashtable]$Params = @{}) {
  $script:messageId++
  $id = $script:messageId
  $json = @{ id = $id; method = $Method; params = $Params } | ConvertTo-Json -Compress -Depth 12
  $bytes = [Text.Encoding]::UTF8.GetBytes($json)
  $segment = [ArraySegment[byte]]::new($bytes)
  $socket.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
  while ($true) {
    $stream = [IO.MemoryStream]::new()
    do {
      $buffer = New-Object byte[] 65536
      $received = $socket.ReceiveAsync([ArraySegment[byte]]::new($buffer), [Threading.CancellationToken]::None).GetAwaiter().GetResult()
      $stream.Write($buffer, 0, $received.Count)
    } until ($received.EndOfMessage)
    $message = [Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
    if ($message.id -eq $id) {
      if ($message.error) { throw $message.error.message }
      return $message.result
    }
  }
}

Invoke-Cdp 'Page.enable' | Out-Null
if ($Advance) {
  Invoke-Cdp 'Runtime.evaluate' @{ expression = "Array.from(document.querySelectorAll('button')).find((button) => button.textContent.includes('Choose how your agents think'))?.click()" } | Out-Null
  Start-Sleep -Milliseconds 400
}
if ($SelectGemini) {
  Invoke-Cdp 'Runtime.evaluate' @{ expression = "Array.from(document.querySelectorAll('button')).find((button) => button.textContent.includes('Connect free-tier Gemini'))?.click()" } | Out-Null
  Start-Sleep -Milliseconds 400
}
$state = Invoke-Cdp 'Runtime.evaluate' @{ expression = 'JSON.stringify({title:document.title,text:document.body.innerText.slice(0,2500),width:innerWidth,height:innerHeight})'; returnByValue = $true }
$capture = Invoke-Cdp 'Page.captureScreenshot' @{ format = 'png'; fromSurface = $true; captureBeyondViewport = $false }
[IO.File]::WriteAllBytes($Output, [Convert]::FromBase64String($capture.data))
$socket.Dispose()

Write-Output $state.result.value
Write-Output $Output
