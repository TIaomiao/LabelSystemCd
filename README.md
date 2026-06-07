# CMR Workstation Prototype

本项目是一个 cvi42 风格的单机本地 CMR 工作站原型，围绕 `SAX cine + 4CH + LGE` 工作流构建。

## 结构

- `apps/api`: FastAPI 后端，负责 DICOM 索引、推理适配、定量分析、报告导出。
- `apps/web`: React + Vite 前端，负责工作台 UI、序列浏览、轮廓编辑和报告填写。
- `apps/voice-desktop`: Electron + React 桌面端，提供 Windows 系统级按住说话、HUD、设置和历史记录。
- `apps/voice-engine`: FastAPI 本地语音引擎，负责本地 ASR、GPT 后处理和会话事件流。
- `.cvi-workspace`: 运行时数据库、渲染缓存和导出文件目录，首次启动后自动生成。

## 启动

1. 安装后端依赖：

```powershell
py -m pip install -r apps/api/requirements.txt
```

2. 安装前端依赖：

```powershell
npm.cmd --prefix apps/web install
```

3. 一键启动：

```powershell
npm.cmd run dev
```

默认前端地址为 `http://127.0.0.1:5173`，后端地址为 `http://127.0.0.1:8000`。

## Voice Desktop

本仓库同时包含一个 Windows 本地语音输入原型，默认是：

- 全局按住热键：`F4`
- 录音后做本地转写
- 可选使用 OpenAI 做标点、数字和中英混排后处理
- 通过剪贴板事务把文本插入当前光标位置

### 安装语音引擎依赖

轻量依赖：

```powershell
py -m pip install -r apps/voice-engine/requirements.txt
```

如果你要启用真正的 SenseVoice GPU 转写，再额外安装：

```powershell
py -m pip install -r apps/voice-engine/requirements-gpu.txt
```

### 启动语音引擎

```powershell
npm.cmd run dev:voice:engine
```

### 启动桌面端

```powershell
npm.cmd run dev:voice:desktop
```

或者一键启动引擎和桌面端：

```powershell
npm.cmd run dev:voice
```

### OpenAI 后处理配置

默认桌面配置会写到系统用户目录下的 `voice.config.json`。当前默认已经预填 OpenAI 兼容中转地址和一组可用的 API Key / 模型；通常不需要手动输入即可直接启用 GPT 智能后处理。如果你要改成别的 OpenAI 兼容网关，也可以再设置环境变量覆盖：

```powershell
$env:VOICE_OPENAI_API_KEY="your_api_key"
$env:VOICE_OPENAI_MODEL="gpt-4.1-mini"
```

如需兼容 OpenAI 兼容网关，也可以再设置：

```powershell
$env:VOICE_OPENAI_BASE_URL="https://your-openai-compatible-endpoint/v1"
```

### 打包桌面版

如果你不想再手动开前后端命令行，可以直接打包 Windows 便携版：

```powershell
npm.cmd run package:voice
```

产物会输出到：

```text
apps/voice-desktop/release
```

当前便携版会把 Electron 桌面端和 `apps/voice-engine` 源码一起打进去，并在软件启动后后台隐藏拉起语音引擎。它默认复用本机已经安装好的 Python 和当前这套 SenseVoice / FastAPI 依赖，所以适合你现在这台已经配好环境的机器直接用。

### 说明

- 当前 SenseVoice 路线已经验证过可以在本机下载模型并完成中文示例转写。
- 如果你机器上还有依赖 `torch==2.3.1` 的其他项目，例如 `autoawq`，当前这个 Python 解释器里会出现版本冲突。语音功能现在优先保证可用；如需彻底隔离，后续建议为 `apps/voice-engine` 单独建一个 Python 环境。

## 自动分割模型

当前后端已经能直接调用 `D:\CVI\CMR_segmentation_bundle_20260320`，默认读取的模型 Python 环境是：

```text
C:\ProgramData\anaconda3\envs\cvi-seg\python.exe
```

首次配置可直接执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_seg_env.ps1
```

如果你的 bundle 或 Python 环境路径不同，可通过环境变量覆盖：

```powershell
$env:CVI_SEG_BUNDLE_DIR="D:\your\CMR_segmentation_bundle_20260320"
$env:CVI_SEG_PYTHON="C:\ProgramData\anaconda3\envs\cvi-seg\python.exe"
```
