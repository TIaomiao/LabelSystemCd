# MRIAgent - 心脏MRI多智能体诊断系统

## 项目结构

```
MRIAgent/
├── src/                          # 主要源代码目录
│   ├── config/                   # 配置文件
│   │   └── settings.py          # 全局配置（所有路径均使用相对路径）
│   ├── agents/                   # Agent 模块
│   │   └── main_agent.py        # 主诊断 Agent
│   ├── core/                     # 核心功能
│   │   └── data_loader.py       # 数据加载器
│   ├── pipelines/                # 处理流程
│   │   └── diagnosis_pipeline.py # 诊断流程
│   ├── tools/                    # 工具模块
│   │   ├── dicom_utils.py       # DICOM 处理工具
│   │   ├── sequence_classifier.py # 序列分类器
│   │   ├── segmentation_runner.py # 分割运行器
│   │   ├── phase_selector.py    # 时相选择器
│   │   ├── measurement_tools.py # 测量工具
│   │   └── measurements/        # 测量子模块
│   ├── utils/                    # 通用工具
│   │   └── logging_utils.py     # 日志工具
│   ├── main.py                   # 主入口程序
│   ├── test_pipeline.py          # 测试脚本
│   ├── logs/                     # 日志输出目录
│   ├── output/                   # 处理结果输出目录
│   └── data/                     # 临时数据目录
├── nnUNet_data/                  # nnU-Net 数据和模型
│   ├── nnUNet_raw_data/         # 原始数据
│   ├── nnUNet_preprocessed/     # 预处理数据
│   └── nnUNet_results/          # 训练好的模型
│       ├── Dataset301_ACDC/     # SAX 分割模型
│       └── Dataset303_MMWHS/    # 4CH 分割模型
├── medical_models/               # 医学模型
│   └── medical_multimodal_classifier/ # 序列分类模型
└── models.py                     # 模型定义

```

## 路径配置说明

### 相对路径设计

所有路径配置都使用相对路径，基于 `config/settings.py` 中的 `BASE_DIR` 自动计算：

```python
# settings.py 中的路径配置
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # 指向 MRIAgent 根目录
SRC_DIR = BASE_DIR / "src"
DATA_DIR = BASE_DIR.parent / "data" / "dataset_cut_mri"  # 数据目录在 MRIAgent 的父目录下
```

### 主要路径变量

- `BASE_DIR`: MRIAgent 项目根目录
- `SRC_DIR`: src 源码目录（原 src2）
- `DATA_DIR`: 患者数据目录
- `OUTPUT_DIR`: 处理结果输出目录
- `LOG_DIR`: 日志目录
- `TEMP_DIR`: 临时文件目录
- `SEQUENCE_CLASSIFIER_DIR`: 序列分类模型目录
- `FOUR_CH_SEG_MODEL_DIR`: 4CH 分割模型目录
- `SAX_SEG_MODEL_DIR`: SAX 分割模型目录
- `NNUNET_ENV`: nnU-Net 环境变量字典

## 使用方法

### 基本使用

```bash
# 进入 src 目录
cd /path/to/MRIAgent/src

# 运行主程序
python main.py --patient-id 0004335617

# 运行测试脚本
python test_pipeline.py 0004335617
```

### 作为模块导入

```python
from pipelines.diagnosis_pipeline import DiagnosisPipeline

# 创建诊断流程实例
pipeline = DiagnosisPipeline()

# 处理患者数据
result = pipeline.run(patient_id="0004335617")

# 查看结果
print(result)
```

## 项目可移植性

### 为什么使用相对路径？

1. **跨环境部署**: 项目可以在不同机器上运行，无需修改代码
2. **团队协作**: 不同开发者可以将项目放在不同位置
3. **容器化支持**: 便于 Docker 等容器化部署
4. **避免路径泄露**: 不会在代码中暴露本地文件系统结构

### 打包和分发

整个 `MRIAgent` 目录可以直接打包分发：

```bash
# 打包项目
cd /path/to
tar -czf MRIAgent.tar.gz MRIAgent/

# 在新机器上解压
tar -xzf MRIAgent.tar.gz
cd MRIAgent/src
python main.py --patient-id YOUR_PATIENT_ID
```

### 注意事项

1. **数据目录**: 默认数据目录 `DATA_DIR` 指向 `../data/dataset_cut_mri`（MRIAgent 父目录下）
   - 如果数据在其他位置，可以在 `config/settings.py` 中修改 `DATA_DIR` 的相对路径
   - 或者通过环境变量设置

2. **模型文件**: 确保以下目录存在并包含相应的模型：
   - `medical_models/medical_multimodal_classifier/`
   - `nnUNet_data/nnUNet_results/Dataset301_ACDC/`
   - `nnUNet_data/nnUNet_results/Dataset303_MMWHS/`

3. **Python 依赖**: 运行前需要安装必要的依赖包

## 输出结果

处理结果保存在 `src/output/{patient_id}/` 目录下：

```
output/{patient_id}/
├── metrics.json              # 量化测量结果
├── report.json               # 诊断报告
├── workflow.log              # 工作流程日志
├── previews/                 # 序列预览图
│   ├── 4CH.png
│   ├── SAX.png
│   └── LGE.png
├── segmentations/            # 所有时间帧的分割结果
│   ├── SAX/
│   └── 4CH/
├── key_frames/               # ED/ES 关键帧
│   ├── SAX/
│   │   ├── ED_tt....nii.gz
│   │   ├── ES_tt....nii.gz
│   │   └── README.txt
│   └── 4CH/
│       ├── ED_tt....nii.gz
│       └── README.txt
└── measurements/             # 测量可视化
    └── SAX_ED/
        └── *.png
```

## 更新日志

### 2024-11-26
- ✅ 将 `src2` 重命名为 `src`
- ✅ 将 `nnUNet_data` 移动到 `MRIAgent` 根目录下
- ✅ 修改所有绝对路径为相对路径
- ✅ 更新所有模块导入路径
- ✅ 确保项目可移植性

## 技术支持

如有问题，请检查：
1. 路径配置是否正确（`config/settings.py`）
2. 模型文件是否完整
3. Python 依赖是否安装
4. 日志文件（`logs/diagnosis.log`）





