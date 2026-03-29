param(
  [string]$ApiHost = "api.stockai-pro.in",
  [string]$OriginHost = "stockai-pro.onrender.com",
  [string]$HealthPath = "/health"
)

$ErrorActionPreference = "Stop"

function Write-Section {
  param([string]$Title)
  Write-Host ""
  Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Resolve-DnsSnapshot {
  param(
    [string]$QueryHost,
    [string]$Server,
    [string]$Type = "A"
  )

  try {
    if ([string]::IsNullOrWhiteSpace($Server)) {
      $records = Resolve-DnsName -Name $QueryHost -Type $Type -ErrorAction Stop
      $serverLabel = "system-default"
    }
    else {
      $records = Resolve-DnsName -Name $QueryHost -Server $Server -Type $Type -ErrorAction Stop
      $serverLabel = $Server
    }

    $answer = $records |
      Where-Object { $_.Type -eq $Type -or $_.Type -eq "CNAME" } |
      Select-Object Name, Type, TTL, IPAddress, NameHost

    if (-not $answer) {
      Write-Host "[$serverLabel][$Type] No records returned"
      return
    }

    $answer | Format-Table -AutoSize | Out-String | Write-Host
  }
  catch {
    Write-Host "[$Server][$Type] lookup failed: $($_.Exception.Message)" -ForegroundColor Yellow
  }
}

function Measure-Http {
  param([string]$Url)

  try {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-WebRequest -Uri $Url -Method GET -TimeoutSec 20 -UseBasicParsing
    $sw.Stop()

    $preview = ""
    if ($response.Content) {
      $preview = $response.Content.Substring(0, [Math]::Min(140, $response.Content.Length))
    }

    [PSCustomObject]@{
      Url = $Url
      Status = [int]$response.StatusCode
      DurationMs = [int]$sw.ElapsedMilliseconds
      Preview = $preview
    }
  }
  catch {
    $statusCode = $null
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
      $statusCode = [int]$_.Exception.Response.StatusCode
    }

    [PSCustomObject]@{
      Url = $Url
      Status = if ($null -ne $statusCode) { $statusCode } else { 0 }
      DurationMs = 0
      Preview = $_.Exception.Message
    }
  }
}

Write-Section "DNS: API host"
Resolve-DnsSnapshot -QueryHost $ApiHost -Type "A"
Resolve-DnsSnapshot -QueryHost $ApiHost -Type "AAAA"
Resolve-DnsSnapshot -QueryHost $ApiHost -Server "1.1.1.1" -Type "A"
Resolve-DnsSnapshot -QueryHost $ApiHost -Server "8.8.8.8" -Type "A"

Write-Section "DNS: Origin host"
Resolve-DnsSnapshot -QueryHost $OriginHost -Type "A"
Resolve-DnsSnapshot -QueryHost $OriginHost -Server "1.1.1.1" -Type "A"
Resolve-DnsSnapshot -QueryHost $OriginHost -Server "8.8.8.8" -Type "A"

$apiHealth = "https://$ApiHost$HealthPath"
$originHealth = "https://$OriginHost$HealthPath"
$apiHttp = "http://$ApiHost$HealthPath"

Write-Section "HTTP reachability"
$results = @(
  Measure-Http -Url $apiHealth
  Measure-Http -Url $originHealth
  Measure-Http -Url $apiHttp
)
$results | Format-Table -AutoSize | Out-String | Write-Host

Write-Section "Quick verdict"
$apiOk = $results | Where-Object { $_.Url -eq $apiHealth -and $_.Status -ge 200 -and $_.Status -lt 400 }
$originOk = $results | Where-Object { $_.Url -eq $originHealth -and $_.Status -ge 200 -and $_.Status -lt 400 }

if ($apiOk -and $originOk) {
  Write-Host "API and origin are both reachable from this network." -ForegroundColor Green
}
elseif (-not $apiOk -and $originOk) {
  Write-Host "Custom API domain failed but origin is healthy: likely DNS/edge/proxy path issue." -ForegroundColor Yellow
}
elseif ($apiOk -and -not $originOk) {
  Write-Host "Custom API domain works but origin endpoint failed from this network." -ForegroundColor Yellow
}
else {
  Write-Host "Both custom API and origin failed from this network." -ForegroundColor Red
}
