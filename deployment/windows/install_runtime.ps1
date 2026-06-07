param(
  [switch]$SkipPrereqInstall
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ApiPythonVersion = "3.11"
$ApiVenv = Join-Path $Root ".venvs\cvi-api"
$SegVenv = Join-Path $Root ".venvs\cvi-seg"

function Ensure-WingetPackage {
  param(
    [Parameter(Mandatory = $true)][string]$Id
  )
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "winget 不存在，跳过自动安装 $Id"
    return
  }
  Write-Host "安装/确认依赖: $Id"
  winget install --id $Id --accept-package-agreements --accept-source-agreements --silent | Out-Host
}

if (-not $SkipPrereqInstall) {
  Ensure-WingetPackage -Id "Python.Python.3.11"
  Ensure-WingetPackage -Id "Microsoft.VCRedist.2015+.x64"
}

$Python311 = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $Python311) {
  throw "未找到 py launcher。请先安装 Python 3.11。"
}

Write-Host "创建 API 虚拟环境: $ApiVenv"
py -3.11 -m venv $ApiVenv
& (Join-Path $ApiVenv "Scripts\python.exe") -m pip install --upgrade pip setuptools wheel
& (Join-Path $ApiVenv "Scripts\python.exe") -m pip install -r (Join-Path $Root "apps\api\requirements.txt")

Write-Host "创建分割虚拟环境: $SegVenv"
py -3.11 -m venv $SegVenv
& (Join-Path $SegVenv "Scripts\python.exe") -m pip install --upgrade pip setuptools wheel
& (Join-Path $SegVenv "Scripts\python.exe") -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu126
& (Join-Path $SegVenv "Scripts\python.exe") -m pip install -r (Join-Path $Root "deployment\windows\requirements-cvi-seg.txt")
& (Join-Path $SegVenv "Scripts\python.exe") -m pip install -e (Join-Path $Root "third_party\EdgeTAM")

Write-Host ""
Write-Host "环境安装完成。"
Write-Host "API Python : $(Join-Path $ApiVenv 'Scripts\python.exe')"
Write-Host "SEG Python : $(Join-Path $SegVenv 'Scripts\python.exe')"
