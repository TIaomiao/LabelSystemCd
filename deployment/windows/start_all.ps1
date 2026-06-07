$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

$apiArgs = @(
  "-NoExit",
  "-Command",
  "Set-Location '$Root'; powershell -ExecutionPolicy Bypass -File '$Root\deployment\windows\start_api.ps1'"
)

$webArgs = @(
  "-NoExit",
  "-Command",
  "Set-Location '$Root'; powershell -ExecutionPolicy Bypass -File '$Root\deployment\windows\start_web.ps1'"
)

$api = Start-Process powershell -ArgumentList $apiArgs -PassThru
$web = Start-Process powershell -ArgumentList $webArgs -PassThru

Write-Host "API PID: $($api.Id)"
Write-Host "WEB PID: $($web.Id)"
Write-Host "API  : http://127.0.0.1:8010"
Write-Host "WEB  : http://127.0.0.1:5174"
