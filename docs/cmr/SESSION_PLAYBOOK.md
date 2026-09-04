# CMR 多 session 推进手册

## 共同上下文的唯一入口

不同平台不需要共享聊天记忆。每个 agent 进入任务时按下面顺序读取：

1. 根 `AGENTS.md` 和目标路径最近的 `AGENTS.md`；
2. `docs/cmr/README.md`、`ARCHITECTURE.md`、`ROADMAP.md`、accepted ADR；
3. 目标功能的 GitHub Issue；
4. 目标功能 `STATUS.md`、`SPEC.md`、`CLINICAL_CONTRACT.md`、`ACCEPTANCE.md`；
5. 最近一次相关 PR 和测试结果。

若外部平台不能读取私有仓库，先提供自动生成的 `docs/cmr/dashboard/CONTEXT_PACKET.md`；它只用于恢复脱敏状态，具体实现仍必须回到仓库、Issue、PR和测试核验。

结束时只回写：功能 `STATUS.md`、代码 commit、测试证据和 GitHub Issue/PR 链接。不要把完整聊天记录复制进仓库，也不要让看板维护第二套状态。

## 建议的任务分工

| 任务 | 作用 | 适合的模型/平台 |
|---|---|---|
| CMR-00 总控 | 依赖、session登记、状态看板、合并顺序 | 本地 Codex |
| CMR-01 共享底座 | 公共 contract、坐标、provenance、quality | 本地 Codex，必要时请师兄审查 |
| 一个功能执行任务 | 单一功能的代码、测试、STATUS | 本地 Codex |
| 云端规划 | 读取仓库规范，产出一个 Issue 任务书 | ChatGPT Project |
| 对抗审查 | 反例、边界、医学定义和证据缺口 | DeepSeek/Kimi/其他模型 |
| 紧急代码草案 | 快速候选实现或定位思路 | 任意模型；结果必须回到 Codex验证 |

同时最多运行一个共享底座任务和两个功能任务。模型数量不是并发上限；分支、worktree 和公共 contract 才是实际约束。

## 新建云端规划对话

```text
你是 CMR 产品规划员。请先读取仓库中的根 AGENTS.md、docs/cmr/README.md、
ARCHITECTURE.md、ROADMAP.md、HANDOFF_CONTRACT.md、CLOUD_PROJECT_INSTRUCTIONS.md，
以及当前功能的 accepted ADR 和 STATUS/SPEC/CLINICAL_CONTRACT。
先列出实际读取的路径、已确认事实、Codex待验证假设和未决的产品/临床问题。
然后只规划一个功能，并严格按 .github/ISSUE_TEMPLATE/cmr_feature_plan.md 输出一份
可粘贴到私有 GitHub Issue 的任务书。不要声称代码已经实现、测试通过或医生认可。
```

## 新建 Codex 执行对话

```text
你是 CMR 功能执行 agent。任务入口是 GitHub Issue <编号/链接>。
请先读取根和目标路径的 AGENTS.md、docs/cmr/README.md、相关 accepted ADR、
该 Issue、目标功能 STATUS.md/SPEC.md/CLINICAL_CONTRACT.md/ACCEPTANCE.md，
并报告当前 branch/worktree、基线 commit、允许修改路径、共享 contract 影响、
测试入口、回滚方式和单一下一步。先核对云端 Issue 的假设，冲突时停下并报告。
只在独立 worktree/feature branch 工作，不碰生产 checkout，不读取病例/DICOM/数据库/日志，
不部署、不重启服务。完成后更新 STATUS.md，写明 implemented/demo_only/not_done、
实际测试、数据范围、已知反例、阻塞和唯一下一步，然后提交 commit 并给出 PR 证据。
```

## 对抗性审查对话

```text
请只根据下面的 Issue、STATUS、PR和测试证据审查这个 CMR 功能。
先列出最强反驳论点、可推翻结论的反例、适用边界和替代解释；
再区分已实现、demo_only、推测、尚未实现，最后给出证据缺口和唯一下一步。
不要把技术测试通过写成临床有效，不要补造病例、医生意见或仓库事实。
```

## 紧急代码草案对话

```text
请给出一个最小候选补丁或定位方案，不要直接声称可以合并。
先说明你依据的文件和不确定假设；不得引入新公共 contract、数据库迁移、部署或患者数据。
候选结果交给本地 Codex 在独立 worktree 中重新核对、测试、记录 STATUS 和 PR。
```

## 交接检查清单

- [ ] `STATUS.md` 的 JSON 机器区块已更新；
- [ ] 状态属于 `planned/demo_only/technically_verified/doctor_reviewed/accepted`；
- [ ] branch、worktree、commit、Issue 和 PR 可追溯；
- [ ] 测试结果区分 passed / failed / not_run / blocked；
- [ ] 没有患者、DICOM、数据库、日志、凭据、模型权重或服务器绝对路径；
- [ ] 已写最强反例、失败边界和唯一下一步；
- [ ] 看板重新生成并通过 `--check`；
- [ ] 医生验收状态没有被技术测试自动升级。
