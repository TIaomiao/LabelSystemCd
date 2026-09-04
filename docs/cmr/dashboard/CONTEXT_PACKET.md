# CMR Session Context Packet

只读交接摘要。事实来自各功能 `STATUS.md`；代码、Issue、PR和测试仍是最终证据源。
本文件不包含患者、DICOM、数据库、日志、凭据、模型权重或服务器绝对路径。

## 使用规则

- 先读取仓库 `AGENTS.md`、`docs/cmr/README.md`、accepted ADR 和目标功能文件。
- `state` 只能是 `planned`、`demo_only`、`technically_verified`、`doctor_reviewed`、`accepted`。
- 技术测试通过不等于临床有效；医生验收状态必须单独确认。
- 规划 agent 不声称实现，执行 agent 必须回写 STATUS.md、commit、测试和唯一下一步。

## Session 总览

| Session | 功能 | 状态 | 分支 | Commit | Issue/PR | 阻塞 | 下一步 |
|---|---|---|---|---|---|---|---|
| CMR-00 | 仓库治理与多 session 总控 | technically_verified | `chore/cmr-m0-governance` | `f52a53d` | #1 / #1 | Cockpit PR #3的GitHub CI和工程评审待完成 | 以CMR-01 PR #2为主线完成ADR-002架构评审，同时跟踪PR #3 CI |
| CMR-01 | 共享结果契约与质量底座 | technically_verified | `feat/cmr-01-result-contract` | `748767c` | — / #2 | apps/web TypeScript typecheck 因前端依赖未安装而找不到 tsc；ADR-002 尚待架构评审 | 在 PR #2 完成 ADR-002 架构评审并检查 GitHub CI |
| CMR-10 | Cine心功能 | planned | `not-created` | `0000000` | — / — | 等待共享底座契约 | 完成临床输入、输出单位和失败条件的功能规划 |
| CMR-11 | Cine应变 | planned | `not-created` | `0000000` | — / — | 等待共享底座和Cine心功能边界 | 定义proxy与validated Feature Tracking的区别 |
| CMR-20 | T1 Mapping/ECV | planned | `not-created` | `0000000` | — / — | 等待共享底座契约 | 完成配准、ECV公式和质量门槛规划 |
| CMR-30 | LGE/T2W联合分析 | planned | `not-created` | `0000000` | — / — | 等待共享底座契约 | 完成LGE可靠性闭环和T2W联合分析范围规划 |
| CMR-40 | 首过灌注 | planned | `not-created` | `0000000` | — / — | 等待共享底座契约 | 完成输入序列、曲线和质量契约规划 |
| CMR-50 | 4D Flow | planned | `not-created` | `0000000` | — / — | 等待共享底座契约和资源审计 | 完成数据、算力和验证可行性审计 |

## CMR-00 · 仓库治理与多 session 总控

- 状态：`technically_verified`；更新时间：`2026-09-04T11:09:22+08:00`；数据范围：`none`
- 依赖：无
- 已实现：CMR目录边界与分层AGENTS.md；模块manifest和治理测试；云端规划到Codex执行的交接契约；仓库边界ADR-001；TIaomiao专用SSH key已创建并完成人工认证；PR #1当前头2/2 Checks通过、师兄已确认并合并为3c6f21f；服务器已核验合并提交并推送基线tag cmr-m0-governance-merged-20260904；Cockpit PR #3已建立并进入CI与工程评审
- 仅演示：静态session看板原型和Codex对话追溯
- 尚未实现：TIaomiao Git identity统一
- 测试：CMR governance unit tests=passed;Python compileall boundary=passed;workflow YAML parse=passed
- 医生复核：`not_applicable`
- 阻塞：Cockpit PR #3的GitHub CI和工程评审待完成
- 唯一下一步：以CMR-01 PR #2为主线完成ADR-002架构评审，同时跟踪PR #3 CI
- 证据索引：`docs/cmr/decisions/ADR-001-repository-boundary.md`, `docs/cmr/HANDOFF_CONTRACT.md`, `tests/cmr/test_repository_safety.py`, `tests/cmr/test_status_board.py`, `docs/cmr/CODEX_TASK_REGISTRY.json`

### 当前正式门禁

- PR #1 当前头 Checks：`passed`；证据提交 `f52a53d`；新鲜度 `current`；核验时间 `2026-09-04`；构建者于2026-09-04报告当前头f52a53d的Checks为2/2通过。
- PR #1 工程评审：`passed`；证据提交 `f52a53d`；新鲜度 `current`；核验时间 `2026-09-04`；构建者于2026-09-04确认师兄已完成工程确认。
- PR #1 合并：`passed`；证据提交 `3c6f21f`；新鲜度 `current`；核验时间 `2026-09-04`；PR #1已合并为3c6f21f；服务器已fetch核验并推送新main基线tag。

### 历史证据（不得沿用为当前门禁）

- PR #1 历史 Checks：`passed`；证据提交 `fad0529`；核验时间 `2026-08-31`；2026-08-31截图确认All checks have passed（2/2）；仅证明旧头。

### Cockpit 交付

- 分支：`feat/cmr-session-cockpit-mvp`；最近验证提交：`5bcbd30`
- 测试：`12/12`；生成检查：`passed`；bundle：`verified`
- 远端状态：`pr_open`；PR：`#3`；更新时间：`2026-09-04T11:09:22+08:00`

## CMR-01 · 共享结果契约与质量底座

- 状态：`technically_verified`；更新时间：`2026-09-04T11:09:22+08:00`；数据范围：`synthetic`
- 依赖：无
- 已实现：canonical JSON Schema result envelope v1；schema-driven backend parse validation serialization and stale checks；generated frontend TypeScript contract boundary with drift check；synthetic scalar dimensionless artifact and negative fixtures；proposed ADR-002 and CMR-01 specification evidence；rebased onto reviewed baseline cmr-m0-governance-merged-20260904 at 3c6f21f；branch pushed to origin；GitHub PR #2 已建立并进入架构与工程评审
- 仅演示：暂无
- 尚未实现：architecture acceptance of ADR-002；frontend TypeScript compiler execution；downstream module adapters；legacy migration；database persistence；production integration；physician review
- 测试：CMR contract tests (21)=passed;CMR governance regressions (7)=passed;generated type drift check=passed;Python compile boundary=passed;git diff check=passed;apps/web Node tests (17)=passed;apps/web TypeScript typecheck=blocked
- 医生复核：`not_scheduled`
- 阻塞：apps/web TypeScript typecheck 因前端依赖未安装而找不到 tsc；ADR-002 尚待架构评审
- 唯一下一步：在 PR #2 完成 ADR-002 架构评审并检查 GitHub CI
- 证据索引：`contracts/cmr/result-envelope.schema.json`, `docs/cmr/decisions/ADR-002-result-contract-v1.md`, `docs/cmr/features/CMR-01/ACCEPTANCE.md`

## CMR-10 · Cine心功能

- 状态：`planned`；更新时间：`2026-09-01T12:00:00+08:00`；数据范围：`none`
- 依赖：CMR-01
- 已实现：暂无
- 仅演示：暂无
- 尚未实现：ED/ES定义；LV/RV完整性；医生验收样例
- 测试：未开始=not_run
- 医生复核：`not_scheduled`
- 阻塞：等待共享底座契约
- 唯一下一步：完成临床输入、输出单位和失败条件的功能规划
- 证据索引：`docs/cmr/FEATURE_PORTFOLIO.md`

## CMR-11 · Cine应变

- 状态：`planned`；更新时间：`2026-09-01T12:00:00+08:00`；数据范围：`none`
- 依赖：CMR-01, CMR-10
- 已实现：暂无
- 仅演示：暂无
- 尚未实现：Feature Tracking定义；数值验证；困难病例验收
- 测试：未开始=not_run
- 医生复核：`not_scheduled`
- 阻塞：等待共享底座和Cine心功能边界
- 唯一下一步：定义proxy与validated Feature Tracking的区别
- 证据索引：`docs/cmr/FEATURE_PORTFOLIO.md`

## CMR-20 · T1 Mapping/ECV

- 状态：`planned`；更新时间：`2026-09-01T12:00:00+08:00`；数据范围：`none`
- 依赖：CMR-01
- 已实现：暂无
- 仅演示：暂无
- 尚未实现：Pre/Post配准；Hct输入；正常范围
- 测试：未开始=not_run
- 医生复核：`not_scheduled`
- 阻塞：等待共享底座契约
- 唯一下一步：完成配准、ECV公式和质量门槛规划
- 证据索引：`docs/cmr/FEATURE_PORTFOLIO.md`

## CMR-30 · LGE/T2W联合分析

- 状态：`planned`；更新时间：`2026-09-01T12:00:00+08:00`；数据范围：`none`
- 依赖：CMR-01
- 已实现：暂无
- 仅演示：暂无
- 尚未实现：跨序列配准；T2比值；可挽救心肌定义
- 测试：未开始=not_run
- 医生复核：`not_scheduled`
- 阻塞：等待共享底座契约
- 唯一下一步：完成LGE可靠性闭环和T2W联合分析范围规划
- 证据索引：`docs/cmr/FEATURE_PORTFOLIO.md`

## CMR-40 · 首过灌注

- 状态：`planned`；更新时间：`2026-09-01T12:00:00+08:00`；数据范围：`none`
- 依赖：CMR-01
- 已实现：暂无
- 仅演示：暂无
- 尚未实现：动态曲线；静息/负荷匹配；MPRI
- 测试：未开始=not_run
- 医生复核：`not_scheduled`
- 阻塞：等待共享底座契约
- 唯一下一步：完成输入序列、曲线和质量契约规划
- 证据索引：`docs/cmr/FEATURE_PORTFOLIO.md`

## CMR-50 · 4D Flow

- 状态：`planned`；更新时间：`2026-09-01T12:00:00+08:00`；数据范围：`none`
- 依赖：CMR-01
- 已实现：暂无
- 仅演示：暂无
- 尚未实现：三维速度场；校正；物理验证
- 测试：未开始=not_run
- 医生复核：`not_scheduled`
- 阻塞：等待共享底座契约和资源审计
- 唯一下一步：完成数据、算力和验证可行性审计
- 证据索引：`docs/cmr/FEATURE_PORTFOLIO.md`

## 正在推进的 Codex 对话

状态快照观测时间：`2026-09-04T11:09:22+08:00`。任务状态可能随后变化，thread ID 用于回到原对话核验。

| 对话 | Session | 状态快照 | 职责 | 最后活动 | Thread ID |
|---|---|---|---|---|---|
| CMR-00 · 总控与集成 | CMR-00 | idle | 仓库治理、Cockpit、跨 session 集成与交接门禁 | `2026-09-04T11:09:22+08:00` | `01a051e9-5dcf-7ea3-80ad-ddce1ae5260a` |
| 建立 CMR 结果公共契约 | CMR-01 | idle | CMR-01 公共结果契约、校验、共享类型与合成测试 | `2026-09-02T14:42:35+08:00` | `01a06008-72ad-79d2-855a-8ba17c3eba87` |
| CMR-01 · 服务器转移、PR与架构评审 | CMR-01 | active | 以CMR-01为主线完成Git交付、PR追踪、ADR-002评审与下一阶段门禁 | `2026-09-04T11:09:22+08:00` | `01a05643-d7d7-7f32-a322-f59f143666c8` |
