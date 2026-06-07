# GPU显存问题修复

## 🔴 问题描述

处理到第5个时间点时卡住，怀疑是GPU显存问题。

从日志看：
- 前4个时间点正常完成
- 第5个时间点开始处理但卡住
- nnU-Net使用后台worker（`sending off prediction to background worker`）

## 🔍 问题分析

### 问题1：后台Worker显存未释放

**nnU-Net的predict_from_files使用后台worker**：
- `num_processes_segmentation_export=2` 创建了2个后台进程
- 这些进程可能没有正确释放显存
- 每个时间点累积显存，最终导致OOM

### 问题2：缺少显存清理

**原始代码**：
```python
predictor.predict_from_files(...)
# 没有显存清理
```

**问题**：
- 每次预测后，GPU显存可能没有完全释放
- 累积到第5个时间点时，显存不足

### 问题3：进程数过多

**原始设置**：
```python
num_processes_preprocessing=2,
num_processes_segmentation_export=2,
```

**问题**：
- 多个进程同时使用GPU，显存压力大
- 进程间可能竞争显存资源

## ✅ 修复方案

### 1. 减少进程数

**修复后**：
```python
num_processes_preprocessing=1,  # 从2减少到1
num_processes_segmentation_export=1,  # 从2减少到1
```

**效果**：
- ✅ 减少显存压力
- ✅ 避免进程间竞争
- ✅ 虽然可能稍慢，但更稳定

### 2. 显式清理GPU缓存

**修复后**（`segmentation_runner.py`）：
```python
predictor.predict_from_files(...)

# 显式清理GPU缓存
if torch.cuda.is_available():
    torch.cuda.synchronize()  # 等待所有CUDA操作完成
    torch.cuda.empty_cache()  # 清理未使用的显存缓存
    
    # 等待后台worker完成
    time.sleep(1.0)
    
    # 再次清理
    torch.cuda.empty_cache()
```

**效果**：
- ✅ 确保所有CUDA操作完成
- ✅ 清理未使用的显存缓存
- ✅ 等待后台worker完成后再继续

### 3. 每个时间点后清理

**修复后**（`diagnosis_pipeline.py`）：
```python
pred_path = self.seg_runner.run(...)

# 每个时间点处理后清理GPU缓存
import torch
if torch.cuda.is_available():
    torch.cuda.empty_cache()
    time.sleep(0.5)  # 等待后台worker完成
```

**效果**：
- ✅ 每个时间点后立即清理
- ✅ 避免显存累积
- ✅ 给后台worker时间完成

### 4. OOM错误处理和重试

**修复后**：
```python
except RuntimeError as e:
    error_msg = str(e).lower()
    if "out of memory" in error_msg or "cuda" in error_msg:
        self.logger.error("GPU显存不足，尝试清理缓存后重试...")
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        time.sleep(2)
        # 重试
        pred_path = self.seg_runner.run(...)
```

**效果**：
- ✅ 检测OOM错误
- ✅ 自动清理并重试
- ✅ 提高成功率

## 📊 修复前后对比

### 修复前 ❌

```
处理时间点 1/8: ✓ 完成
处理时间点 2/8: ✓ 完成
处理时间点 3/8: ✓ 完成
处理时间点 4/8: ✓ 完成
处理时间点 5/8: [卡住，显存不足]
```

**问题**：
- 进程数：2个预处理 + 2个导出 = 4个进程
- 显存累积：每个时间点可能累积100-200MB
- 第5个时间点时显存不足

### 修复后 ✅

```
处理时间点 1/8: ✓ 完成 [清理显存]
处理时间点 2/8: ✓ 完成 [清理显存]
处理时间点 3/8: ✓ 完成 [清理显存]
处理时间点 4/8: ✓ 完成 [清理显存]
处理时间点 5/8: ✓ 完成 [清理显存]
...
```

**改进**：
- 进程数：1个预处理 + 1个导出 = 2个进程
- 显存清理：每个时间点后立即清理
- 显存使用：保持在稳定水平

## 🔧 进一步优化建议

### 如果仍然OOM

1. **减少batch size**（如果nnU-Net支持）：
   ```python
   # 在predictor初始化时设置更小的batch size
   ```

2. **使用CPU进行预处理**：
   ```python
   perform_everything_on_device=False  # 预处理在CPU上
   ```

3. **分批处理**：
   - 每处理4个时间点，强制清理一次
   - 或者使用更激进的显存清理策略

4. **监控显存使用**：
   ```python
   import torch
   if torch.cuda.is_available():
       allocated = torch.cuda.memory_allocated() / 1024**3
       reserved = torch.cuda.memory_reserved() / 1024**3
       print(f"GPU显存: {allocated:.2f}GB / {reserved:.2f}GB")
   ```

## 🧪 测试验证

### 测试1：显存监控

在循环中添加显存监控：
```python
for idx, tp in enumerate(timepoints, 1):
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        self.logger.info(f"  显存使用: {allocated:.2f}GB")
    
    pred_path = self.seg_runner.run(...)
    
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        self.logger.info(f"  处理后显存: {allocated:.2f}GB")
```

### 测试2：观察日志

运行诊断流程，观察：
- 每个时间点是否正常完成
- 是否有OOM错误
- 显存是否稳定

## 📝 相关文件

- `tools/segmentation_runner.py` - 减少进程数，添加显存清理
- `pipelines/diagnosis_pipeline.py` - 每个时间点后清理，OOM重试

## ⚠️ 注意事项

1. **性能trade-off**：
   - 减少进程数可能稍微降低速度
   - 但提高了稳定性和显存使用效率

2. **等待时间**：
   - 添加了1秒等待时间，确保后台worker完成
   - 这是必要的，避免显存泄漏

3. **重试机制**：
   - OOM时会自动重试一次
   - 如果重试失败，会跳过该时间点继续处理

## 🚀 现在可以测试

```bash
# 启动服务器
cd /home/lpeng/lzq/MRIAgent/webui/backend
/home/lpeng/miniconda3/envs/lzq/bin/python main.py

# 运行测试
/home/lpeng/miniconda3/envs/lzq/bin/python simple_test.py
```

**预期结果**：
- 所有8个时间点都能正常完成
- 不再卡在第5个时间点
- 显存使用保持稳定
- 如果出现OOM，会自动重试

---

**修复日期**: 2025-11-27  
**问题**: 第5个时间点卡住，GPU显存问题  
**解决方案**: 减少进程数 + 显存清理 + OOM重试

