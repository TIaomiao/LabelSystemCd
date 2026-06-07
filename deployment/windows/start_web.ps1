$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ApiPython = Join-Path $Root ".venvs\cvi-api\Scripts\python.exe"

if (-not (Test-Path $ApiPython)) {
  throw "未找到 API 虚拟环境，请先运行 deployment\\windows\\install_runtime.ps1"
}

$DistDir = Join-Path $Root "apps\web\dist"
if (-not (Test-Path $DistDir)) {
  throw "未找到 apps\\web\\dist，请确认迁移包完整。"
}

Set-Location $DistDir
& $ApiPython -m http.server 5174 --bind 0.0.0.0
