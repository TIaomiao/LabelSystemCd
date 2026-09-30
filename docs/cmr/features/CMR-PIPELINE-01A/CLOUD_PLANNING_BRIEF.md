# CMR-PIPELINE-01A 云端 ChatGPT 规划任务书

## 任务位置

- 产品 GitHub 仓库：`https://github.com/TIaomiao/LabelSystemCd`
- 目标仓库目录：`docs/cmr/features/CMR-PIPELINE-01A/`
- 本地脱敏规划镜像：`G:/Intern/medical-ai-agent-internship-2026/07_cmr_product_program/features/CMR-PIPELINE-01A/`
- 当前执行包：`SPEC.md`、`CLINICAL_CONTRACT.md`、`ACCEPTANCE.md`、`STATUS.md`、`CONTEXT_PACKET.md`
- 本文件的作用：给云端 ChatGPT 规划，不是给服务器 Codex 直接执行的代码任务。

## 给云端 ChatGPT 的提示词

```text
你是 CMR 产品规划员，负责为私有 GitHub 仓库生成一份可执行的 Issue 计划。
你不是代码执行 agent，也不能把规划结果写成已实现、已测试或已获得医生认可。

目标仓库：
https://github.com/TIaomiao/LabelSystemCd

目标功能：
CMR-PIPELINE-01A：DICOM 上传与 Intake。
目标仓库目录：
docs/cmr/features/CMR-PIPELINE-01A/

请先读取：
1. 根 AGENTS.md；
2. docs/cmr/AGENTS.md；
3. docs/cmr/README.md；
4. docs/cmr/ARCHITECTURE.md；
5. docs/cmr/ROADMAP.md；
6. docs/cmr/HANDOFF_CONTRACT.md；
7. docs/cmr/CLOUD_PROJECT_INSTRUCTIONS.md；
8. docs/cmr/features/CMR-PIPELINE-01A/SPEC.md；
9. docs/cmr/features/CMR-PIPELINE-01A/CLINICAL_CONTRACT.md；
10. docs/cmr/features/CMR-PIPELINE-01A/ACCEPTANCE.md；
11. docs/cmr/features/CMR-PIPELINE-01A/CONTEXT_PACKET.md；
12. PIPELINE_INTEGRATION_PLAN.md；
13. SERIES_MANIFEST_INPUT_SPEC.md；
14. BENCHMARK_SHUXI_20260929.md（如果这些材料已进入仓库）。

先报告：
- GitHub 仓库访问是否已验证；
- 实际读取的文件路径；
- 读取到的仓库 HEAD 或快照日期；
- 已确认事实；
- 需要服务器 Codex 验证的假设；
- 与旧 showcase 链路有关、但不能直接继承到 apps/api 的内容。

本轮只规划“DICOM 上传与 Intake”，不规划完整临床算法实现。重点回答：

1. 浏览器文件夹上传、ZIP 上传、分片/断点上传、桌面上传器和 DICOMweb 导入的取舍；
2. 推荐的第一版上传方案，以及为什么适合大体积 DICOM；
3. UploadSession、Job、SeriesManifest 的字段和状态机；
4. 文件数、字节数、摘要、断点、重试、取消、过期和清理策略；
5. ZIP 路径穿越、ZIP bomb、非 DICOM 混入、损坏文件和重复上传的失败行为；
6. 上传、DICOM 头索引、SeriesInstanceUID 归组和后续处理之间的接口；
7. `apps/api` 需要核对的现有路由、存储、认证和任务状态实现；
8. 前端进度应该显示上传进度、索引进度和算法处理进度的哪一部分；
9. 合成测试、性能测试、断网测试和少量获准脱敏样例的验收方式；
10. 服务器 Codex 应拆成哪些有依赖关系的执行 session。

输出格式：

- 一份可直接粘贴到私有 GitHub Issue 的正文；
- 明确的目标、范围、非目标、接口、状态机、失败行为、测试、回滚和唯一下一步；
- 一个“云端规划结论 / 服务器需验证事实 / 临床或产品待决项”表格；
- 一份执行 session 依赖图，第一阶段只能从 Intake 开始；
- 建议的 PR 拆分和每个 PR 的完成标准。

硬性边界：
- 不上传、引用或要求读取患者资料、DICOM 像素、数据库、日志、凭据、模型权重或服务器私有路径；
- 不把术析页面观察到的文件夹选择器当成其服务端协议证据；
- 不把旧 showcase 已有产物当成 apps/api 已经实现；
- 不把上传成功写成序列分类、分割、测量或报告成功；
- 不创建代码、不开 PR、不声称 CI、部署或医生验收已经完成；
- 如果 GitHub 连接不可用，明确写 `repository_access_unverified=true`，只使用上传的脱敏执行包，并标明快照日期。
```

## 云端规划产出回写位置

云端 GPT 生成的计划先由构建者和 DeepSeek 审查，随后整理成私有 GitHub Issue。审查通过后，再由服务器 Codex 从最新 reviewed main 创建独立 branch/worktree 执行。

本地执行包的 `STATUS.md` 在创建 Issue 前保持 `planned`；Issue 编号、branch、commit 和 PR 由执行 session 开始后回写。

## 规划完成后给服务器 Codex 的长任务提示

```text
你是 CMR-PIPELINE-01A 的长期执行 agent。

任务入口：GitHub Issue <编号/链接>
代码仓库：https://github.com/TIaomiao/LabelSystemCd
目标执行包：docs/cmr/features/CMR-PIPELINE-01A/

请在一个连续任务窗口内完成本 Issue 的完整安全范围：
1. 读取根 AGENTS.md、目标路径 AGENTS.md、Issue、SPEC、CLINICAL_CONTRACT、ACCEPTANCE、STATUS、CONTEXT_PACKET；
2. 核验 reviewed main、branch、worktree、允许修改路径和实际 apps/api 上传现状；
3. 先写出简短执行计划，然后连续完成代码、契约、测试和文档；
4. 运行所有适用的定向测试、静态检查、敏感内容扫描和 git diff --check；
5. 更新 STATUS.md，记录 implemented/demo_only/not_done、测试结果、数据范围、反例、阻塞和唯一下一步；
6. 创建 commit，并在具备授权时准备 PR 证据。

不要因为普通的文件阅读、局部实现、测试修复或 STATUS 更新反复停下来询问我。
在任务完成、当前阶段全部验证通过或确实遇到阻塞前持续推进。

只有遇到以下情况才暂停并报告：
- 需要读取患者、DICOM、数据库、日志、凭据或模型权重；
- 需要部署、重启服务、修改生产 checkout、push、合并或公开发布；
- 云端计划与实际仓库代码或 AGENTS 冲突；
- 缺少会改变临床语义、公共 contract 或数据权限的决定；
- 发现无法安全回滚的破坏性操作；
- 同一个阻塞连续复现且无法通过仓库内检查解决。

本轮只做 DICOM 上传与 Intake，不实现 Mapping、灌注、4D Flow 或完整临床报告算法。
代码必须在独立服务器 worktree 中完成，不在本地规划镜像中写正式代码。
完成后给出一次完整交接：commit、测试、修改文件、已知限制、剩余阻塞和下一步。
```
