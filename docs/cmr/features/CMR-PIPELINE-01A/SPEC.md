# CMR-PIPELINE-01A：DICOM 上传与 Intake

## 任务定位

- Task ID：`CMR-PIPELINE-01A`
- 功能：大体积 DICOM 上传、暂存、校验和 Intake
- 产品边界：CMR 产品能力建设
- 目标代码边界：`apps/api/`、`contracts/cmr/`、`tests/cmr/`、`docs/cmr/`
- 初始状态：`planned`

本任务解决“DICOM 如何可靠进入 CMR 处理流水线”。上传完成后才进入 DICOM 头索引、Series manifest 和后续算法任务。

## 目标

建立一个可恢复的上传任务入口，使用户能够：

1. 创建一次上传任务；
2. 上传文件夹或归档文件；
3. 看到文件数、总字节数、已完成字节数和阶段状态；
4. 在网络中断后继续上传；
5. 上传完成后得到可追溯的 Intake 结果；
6. 由后续任务读取 manifest，继续序列分类、分割、测量和报告。

## 目标流程

```text
创建 UploadSession
  → 预检文件清单
  → 分片/可恢复上传
  → 安全暂存与完整性校验
  → DICOM 头索引
  → SeriesInstanceUID 归组
  → 生成 series-manifest
  → 状态 ready_for_processing
```

上传请求不得同步等待完整临床算法处理。处理状态和上传状态必须分开保存。

## 输入

候选输入方式：

- 浏览器文件夹选择；
- 浏览器选择 ZIP 或其他受支持归档；
- 后续可扩展到桌面上传器、DICOMweb 或受控共享目录。

Codex 必须先核验仓库实际支持哪一种输入，不得根据术析页面直接假设 `apps/api` 已支持文件夹上传。

预检至少记录：文件数量、总字节数、相对路径、文件大小和客户端摘要。预检清单不包含患者姓名、病例号或原始 DICOM UID。

## 输出

### UploadSession

至少表达：

- opaque `upload_id`；
- `created_at`；
- `total_files`、`total_bytes`；
- `uploaded_files`、`uploaded_bytes`；
- `state`；
- `error_code` 和可读错误原因；
- 暂存内容的完整性摘要；
- 关联的 `job_id`。

### Intake manifest

上传完成后生成版本化 manifest。Series 级字段沿用 `contracts/cmr/` 的单一规范来源，至少包含：

- opaque `case_id`、`series_id`；
- 脱敏后的 Series UID 哈希或等价引用；
- instance 数量；
- 头读取状态和像素可读性状态；
- 来源文件摘要；
- 后续分类候选和人工复核状态；
- manifest schema 版本。

原始 DICOM UID、患者标识、服务器路径和凭据不得进入浏览器响应、Issue、PR 或公共日志。

## 状态

上传状态至少区分：

```text
created
preflight
uploading
paused
verifying
indexing
ready_for_processing
failed
cancelled
expired
```

`ready_for_processing` 只表示上传和 Intake 完成，不表示序列分类、分割、测量或报告完成。

## 失败行为

- 单个分片失败：保留可重试信息，不重复上传已确认分片；
- 校验和不一致：拒绝该分片或该上传任务，并给出明确原因；
- ZIP 路径穿越、ZIP bomb、超大文件或超出数量限制：在解压/落盘前拒绝；
- 非 DICOM 文件：按明确策略忽略、隔离或失败，不能静默混入 manifest；
- DICOM 头读取失败：记录到 manifest 的质量字段，不把整例伪装成完成；
- 用户取消或任务过期：清理临时内容，保留脱敏失败记录；
- 服务重启：上传任务状态和已确认分片不能只保存在进程内存。

## 非目标

- 不在本任务实现序列分类模型；
- 不在本任务实现 Mapping、灌注或 4D Flow 算法；
- 不在上传请求中运行分割、测量或报告；
- 不修改生产数据库、生产 checkout 或部署配置；
- 不读取真实病例、DICOM 像素、日志正文、凭据或模型权重。

## 依赖

- CMR-01 结果契约及其后续 series-manifest 扩展；
- `apps/api` 实际入口和认证边界；
- 服务器可用的暂存/持久化位置；
- 后续 `CMR-PIPELINE-01B` 任务编排。

## 唯一下一步

在服务器最新 reviewed main 的独立 worktree 中完成 intake gate：核验 `apps/api` 现有路由、前端调用、文件落盘、任务状态和测试入口，然后提出最小实现路径。若实际代码与本 SPEC 冲突，先回写 Issue/STATUS，不静默扩大范围。
