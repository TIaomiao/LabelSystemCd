$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
. (Join-Path $PSScriptRoot "set_cvi_env.ps1")

$ApiPython = Join-Path $Root ".venvs\cvi-api\Scripts\python.exe"
if (-not (Test-Path $ApiPython)) {
  throw "未找到 API 虚拟环境，请先运行 deployment\\windows\\install_runtime.ps1"
}

Set-Location $Root
& $ApiPython -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8010 --app-dir .
