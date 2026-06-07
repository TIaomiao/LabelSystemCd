# GPU设备配置说明

## ✅ 已配置为使用GPU 4

系统检测到8个GPU，GPU 4显存使用最少（4 MiB），已配置为默认使用GPU 4。

## 📊 GPU状态

```
GPU 0: NVIDIA L40, 17432 MiB / 46068 MiB (使用中)
GPU 1: NVIDIA L40, 16919 MiB / 46068 MiB (使用中)
GPU 2: NVIDIA L40, 16927 MiB / 46068 MiB (使用中)
GPU 3: NVIDIA L40, 17087 MiB / 46068 MiB (使用中)
GPU 4: NVIDIA L40, 4 MiB / 46068 MiB (空闲) ← 已配置使用
GPU 5: NVIDIA L40, 4 MiB / 46068 MiB (空闲)
GPU 6: NVIDIA L40, 4 MiB / 46068 MiB (空闲)
GPU 7: NVIDIA L40, 16987 MiB / 46068 MiB (使用中)
```

## 🔧 配置方式

### 方法1：使用配置文件（默认）

在 `config/settings.py` 中：
```python
CUDA_DEVICE_ID = os.getenv("CUDA_DEVICE_ID", "4")  # 默认GPU 4
```

### 方法2：使用环境变量

```bash
# 临时设置（当前会话）
export CUDA_DEVICE_ID=4

# 或在启动服务器时设置
CUDA_DEVICE_ID=4 python main.py
```

### 方法3：修改配置文件

直接修改 `config/settings.py`：
```python
CUDA_DEVICE_ID = "4"  # 改为其他GPU ID（0-7）
```

## 🧪 验证配置

### 测试1：检查配置

```python
from config.settings import CUDA_DEVICE_ID
print(f"配置的GPU: {CUDA_DEVICE_ID}")
```

### 测试2：检查GPU可用性

```bash
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv
```

### 测试3：运行时验证

启动服务器时，会看到：
```
[SegmentationRunner] 使用GPU 4: NVIDIA L40 (44.4GB)
```

## 📝 相关文件

- `config/settings.py` - GPU设备配置
- `tools/segmentation_runner.py` - GPU设备选择逻辑

## ⚠️ 注意事项

1. **设备一致性**：
   - 确保所有CUDA操作都在同一设备上
   - 显存清理也要在正确的设备上

2. **设备切换**：
   - 如果切换GPU，需要重启服务器
   - 模型缓存会保留，但会使用新设备

3. **多GPU环境**：
   - 当前只支持单GPU
   - 如果需要多GPU，需要进一步修改代码

## 🚀 现在可以测试

```bash
# 启动服务器（会自动使用GPU 4）
cd /home/lpeng/lzq/MRIAgent/webui/backend
/home/lpeng/miniconda3/envs/lzq/bin/python main.py

# 运行测试
/home/lpeng/miniconda3/envs/lzq/bin/python simple_test.py
```

**预期结果**：
- 服务器启动时显示：`[SegmentationRunner] 使用GPU 4: NVIDIA L40 (44.4GB)`
- 所有时间点都能正常处理
- 不再卡住
- 显存使用稳定

---

**配置日期**: 2025-11-27  
**默认GPU**: 4号（NVIDIA L40, 44.4GB，当前空闲）

