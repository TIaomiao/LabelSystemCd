# CMR Segmentation Bundle

这个目录是从 `MRIAgent` 中单独整理出来的分割迁移包，目标是让另一个项目可以直接加载并调用心脏 MRI 分割能力，而不必依赖整个原仓库。

当前整理出的可用分割能力如下：

- `SAX`：短轴分割，输出 `RV/MYO/LV`
- `LGE`：当前复用 `SAX` 的 nnU-Net 模型做心肌结构分割
- `4CH`：四腔心分割，输出 `LA/LV/RA/RV`

## 目录结构

```text
CMR_segmentation_bundle_20260320/
├── README.md
├── requirements.txt
├── env.example.sh
├── scripts/
│   ├── run_segmentation.py
│   └── smoke_test.py
├── src/
│   └── cmr_segmentation_bundle/
│       ├── __init__.py
│       ├── config.py
│       ├── common.py
│       ├── nnunet_runner.py
│       └── fourch_runner.py
└── models/
    ├── sax_lge/
    └── 4ch/
```

## 已打包模型

- `models/sax_lge/nnUNetTrainer__nnUNetPlans__3d_fullres/`
  - 来自原仓库 `nnUNet_data/nnUNet_results/Dataset301_ACDC/...`
  - 用于 `SAX` 和 `LGE`
- `models/4ch/best_model.pth`
  - 来自原仓库 `medical_models/4CH_segmentation_model/best_model.pth`
  - 用于 `4CH`

说明：

- 原仓库里还保留了一套 `Dataset303_MMWHS` 的 `4CH nnU-Net` 结果目录，但主推理流程实际调用的是自定义 `U-Net + best_model.pth`。
- 为了避免重复拷贝近 500MB 的冗余模型，本迁移包默认只带“当前主流程真正使用”的 `4CH` 模型。

## 标签定义

### SAX / LGE

- `0`: Background
- `1`: RV
- `2`: MYO
- `3`: LV

### 4CH

- `0`: Background
- `420`: LA
- `500`: LV
- `550`: RA
- `600`: RV

说明：

- 当前打包的 `4CH` 自定义模型不输出单独的心肌标签。
- 如果你的另一个项目强依赖 `4CH` 心肌标签，需要额外改造模型或改回另一套 `nnU-Net 4CH` 方案。

## 环境要求

建议环境：

- Python `3.10` / `3.11` / `3.12`
- Linux
- CUDA 可选

本包在当前机器上已完成的轻量验证：

- Python `3.12.2`
- `4CH` 分割脚本可正常跑通
- `SAX` 分割脚本可正常跑通
- `LGE` 与 `SAX` 共用同一套 nnU-Net 模型入口

安装示例：

```bash
cd CMR_segmentation_bundle_20260320
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
source env.example.sh
```

## 运行方式

脚本已经会自动把本目录下的 `src/` 加到导入路径里，所以直接运行即可。

如果你想在自己的 Python 代码里直接 `import cmr_segmentation_bundle`，再手动设置一次 `PYTHONPATH` 即可：

```bash
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
```

### 1. SAX 分割

```bash
python scripts/run_segmentation.py \
  --sequence sax \
  --input /path/to/input.nii.gz \
  --output-dir /path/to/output
```

### 2. LGE 分割

```bash
python scripts/run_segmentation.py \
  --sequence lge \
  --input /path/to/input.nii.gz \
  --output-dir /path/to/output
```

### 3. 4CH 分割

```bash
python scripts/run_segmentation.py \
  --sequence 4ch \
  --input /path/to/input.nii.gz \
  --output-dir /path/to/output
```

### 4. 指定 GPU

```bash
python scripts/run_segmentation.py \
  --sequence sax \
  --input /path/to/input.nii.gz \
  --output-dir /path/to/output \
  --gpu-id 0
```

### 5. 只做导入级自检

```bash
python scripts/smoke_test.py
```

## 输出说明

脚本默认会输出：

- 分割 NIfTI 文件
- 同名 `_pngs/` 文件夹，里面是每个切片导出的 PNG，便于快速查看

## 与原仓库关系

对应关系如下：

- `SAX/LGE` runner 来源于原仓库 `src/tools/segmentation_runner.py`
- `4CH` runner 来源于原仓库 `src/agents/four_ch_segmentation_agent.py`

但这里已经改成了相对路径、自包含结构，不再依赖原仓库的 `config.settings`。

## 迁移建议

如果你要把这套内容搬到另一个项目：

1. 整个复制本目录
2. 在目标项目里保留本目录原样
3. 通过 `PYTHONPATH=/path/to/this_bundle/src` 导入
4. 从你的主项目里直接调用：

```python
from pathlib import Path
from cmr_segmentation_bundle import (
    FourChSegmentationRunner,
    NnUNetSegmentationRunner,
    get_default_paths,
)

paths = get_default_paths()

sax_runner = NnUNetSegmentationRunner()
sax_seg = sax_runner.run(
    image_path=Path("/path/to/sax.nii.gz"),
    model_dir=paths.sax_lge_model_dir,
    output_dir=Path("/tmp/sax_out"),
)

four_ch_runner = FourChSegmentationRunner()
four_ch_seg = four_ch_runner.run(
    input_path=Path("/path/to/4ch.nii.gz"),
    output_dir=Path("/tmp/4ch_out"),
)
```

## 当前边界

本迁移包只处理“已经是单个 NIfTI 体数据”的分割推理，不负责完整的 DICOM 时相分组流程。

也就是说：

- 如果你的另一个项目已经能得到单个时间点的 `.nii.gz`，这个包可以直接用
- 如果你的另一个项目输入还是一整套 DICOM cine，需要你在上游先完成 DICOM -> 单时间点 NIfTI 的转换

## 版本

- 打包日期：`2026-03-20`
- 来源仓库：`MRIAgent`
