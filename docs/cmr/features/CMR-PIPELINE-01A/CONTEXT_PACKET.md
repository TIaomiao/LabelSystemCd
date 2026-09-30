# CMR-PIPELINE-01A 执行上下文包

## 使用方式

这是给云端 Codex、服务器 Codex 和审查 agent 的可恢复上下文入口。它是截至 2026-09-30 的规划快照，不替代仓库代码、GitHub Issue、PR、测试和服务器实时核验。

进入执行前必须重新读取根 `AGENTS.md`、目标路径 `AGENTS.md`、本目录文件、相关 ADR 和 Issue，并记录实际 HEAD。

## 任务结论

目标是在 `apps/api` 方向建立 DICOM 上传与 Intake，为后续序列分类、分割、测量和报告提供稳定的 manifest 和任务状态。首期不实现临床算法。

## 已确认规划事实

这些事实来自本地规划材料和 DeepSeek 2026-09-29 的代码审计摘要；执行 agent 必须回到仓库复核：

1. 现有系统存在多条上传/处理链路，旧 showcase 链路有文件夹或 ZIP 上传及历史产物，但不等于目标 `apps/api` 已完成 Intake；
2. `/api/cardiac/upload` 的上传目录和处理目录曾存在不一致风险；
3. 旧链路存在内存任务状态、报告兜底状态、GPU 分配和跨病例输出等工程风险；
4. 序列分类结果曾只写入 metrics，没有稳定参与后续路由；
5. 术析页面观察到的上传入口是隐藏的 `multiple + webkitdirectory` 文件夹选择器，默认有“数据脱敏”开关，界面未显示分片、断点、字节进度或重试契约；
6. 术析页面观察结果只用于产品交互参考，不能证明其服务端上传协议或算法实现；
7. `SERIES_MANIFEST_INPUT_SPEC.md` 和 r37 classifier 文档提供了序列 manifest 的候选字段和审计规则，但还没有证明它们已经接入 `apps/api`；
8. CMR-01 result envelope 是共享结果基础；series manifest、upload state 和 stage state 是否进入公共 contract，必须由架构评审确认。

## 需要 Codex 验证的内容

- `apps/api` 当前真实上传路由、认证、中间件和文件落盘方式；
- 前端当前是否已有上传调用或仅有查看/报告功能；
- 服务器允许的暂存目录、权限、容量和清理机制；
- 当前是否存在队列、数据库任务表或可复用的状态持久化；
- ZIP/文件夹输入是否已有安全检查；
- DICOM 头读取和 SeriesInstanceUID 归组能否复用现有 indexer；
- 现有测试框架和最小可运行测试命令；
- zian worktree 对目标代码路径的写权限；
- 旧 showcase/MRIAgent 是否只能作为适配器，还是需要独立迁移计划。

## 本轮允许修改路径

执行前必须以仓库实际 AGENTS 为准。规划目标路径为：

- `apps/api/**` 的上传、Intake 和任务边界；
- `apps/web/src/**` 的上传进度和状态展示；
- `contracts/cmr/**` 的经批准 manifest/status contract；
- `tests/cmr/**`；
- `docs/cmr/features/CMR-PIPELINE-01A/**`。

禁止把旧生产 checkout、真实病例、DICOM、数据库、日志、凭据或模型权重带入提交。

## 交付顺序

```text
intake gate
  → UploadSession/Job contract
  → secure staging and resumable transfer
  → DICOM header index
  → Series manifest
  → frontend status display
  → later orchestration adapter
```

## 完成标准

- 有独立 branch/worktree、Issue、commit 和 STATUS；
- 上传与处理状态分开；
- 断点、校验、取消、过期和失败行为有测试；
- 上传完成但索引失败不会被标记为可处理；
- manifest 使用 opaque ID，不暴露患者标识、原始 UID 或服务器路径；
- 测试只使用合成数据；
- 代码没有顺带实现 Mapping、灌注、4D Flow 或完整报告；
- 所有未验证的服务器能力和产品决定都留在 STATUS/Issue 中。

## 给执行 Codex 的启动词

```text
你是 CMR-PIPELINE-01A 执行 agent。任务入口是本功能 Issue，执行上下文是本目录的 CONTEXT_PACKET.md。
先读根和目标路径 AGENTS.md、docs/cmr/README.md、相关 ADR、SPEC、CLINICAL_CONTRACT、ACCEPTANCE、STATUS。
报告实际 HEAD、branch、worktree、允许修改路径、上传路由证据、状态存储、测试入口和回滚方式。
先核对计划事实；如果 apps/api 与旧 showcase 的实际边界不同，停止并报告差异。
本轮只做 DICOM 上传与 Intake，不实现临床算法。只使用合成数据，不读病例/DICOM/数据库/日志/凭据，不部署、不重启、不修改生产 checkout。
完成后更新 STATUS，记录 implemented/demo_only/not_done、实际测试、反例、唯一下一步、commit 和 PR。
```
