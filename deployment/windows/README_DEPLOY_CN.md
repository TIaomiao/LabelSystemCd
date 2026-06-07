# CVI42 风格 CMR 工作站 Windows 迁移包说明

这个迁移包面向 Windows 服务器，目标是把当前 `CVI` 原型以最少依赖迁移过去。

## 包内内容

- `apps/api`
  轻量 FastAPI 后端源码
- `apps/web/dist`
  已构建好的前端静态页面，可直接部署
- `CMR_segmentation_bundle_20260320`
  当前使用的分割 bundle
- `third_party/EdgeTAM`
  当前使用的时相传播模型仓库
- `deployment/windows`
  安装、环境配置、启动脚本

## 推荐服务器环境

- Windows Server 2019/2022 或 Windows 10/11 x64
- NVIDIA GPU
  推荐显存 `>= 12GB`，当前 4090 路线已经验证可用
- Python 3.11 x64
- 可选：Node.js LTS
  仅当你要重新构建前端时需要；运行静态前端不需要

## 依赖下载

建议优先用 `winget`：

```powershell
winget install Python.Python.3.11
winget install Microsoft.VCRedist.2015+.x64
```

如果服务器没有 `winget`，使用官方页面：

- Python 3.11:
  [https://www.python.org/downloads/windows/](https://www.python.org/downloads/windows/)
- VC++ Runtime:
  [https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist)
- Node.js LTS:
  [https://nodejs.org/en/download](https://nodejs.org/en/download)

## 推荐部署方式

1. 解压迁移包到目标目录，比如 `D:\CVI`
2. 打开 PowerShell
3. 执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\deployment\windows\install_runtime.ps1
```

4. 启动 API：

```powershell
powershell -ExecutionPolicy Bypass -File .\deployment\windows\start_api.ps1
```

5. 启动前端静态服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\deployment\windows\start_web.ps1
```

如果只是在测试环境快速跑起来，也可以：

```powershell
powershell -ExecutionPolicy Bypass -File .\deployment\windows\start_all.ps1
```

## 默认端口

- API: `8010`
- Web: `5174`

## 环境变量

默认环境变量在：

- `deployment/windows/set_cvi_env.ps1`

你通常只需要检查这几个值：

- `CVI_SEG_BUNDLE_DIR`
- `CVI_SEG_PYTHON`
- `CVI_EDGETAM_REPO_DIR`
- `CVI_EDGETAM_CHECKPOINT`
- `CVI_EDGETAM_CONFIG`
- `CVI_SEG_GPU_ID`

## 运行方式说明

- 前端使用 `apps/web/dist` 静态页面运行，服务器运行时不依赖 Node
- 后端使用独立 Python 环境 `.venvs/cvi-api`
- 分割/传播模型使用独立 Python 环境 `.venvs/cvi-seg`

## 注意事项

- 首次运行会自动生成 `.cvi-workspace`
- 当前默认样例目录不会打进迁移包；迁移后请通过前端导入你服务器上的 DICOM 目录
- `4CH` 当前支持手工勾画、时相传播补全和保存；`SAX` 仍保留完整的 AI 分割、传播补全和量化流程
