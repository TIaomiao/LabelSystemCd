# AI 专家受控 Codex 执行工作流

## 目标

反馈 AI 先把医生对话整理为问题单；只读 Codex 调查真实仓库并生成带 commit、文件范围、风险和验证方式的方案。方案草案阶段允许管理员用自然语言连续追问和缩小范围，系统会把最近几轮管理员意见与 Codex 结论一起交给下一轮调查，不要求管理员手工逐字段重写方案。管理员批准方案后，修改必须发生在独立 Git worktree，形成候选提交，经过第二次人工批准才能合并。合并不等于发布，不会重启服务或推送远端。

## 状态流

```text
问题单 → 只读调查 → 方案草案 → 批准方案
                                  ↓
                         受控执行 queued/running
                                  ↓
                         固定验证 + 候选 commit
                                  ↓
                         review_ready
                           ↙             ↘
                    拒绝/重新执行      批准实际改动
                                           ↓
                                  ff-only 合并
                                           ↓
                                  merged（尚未发布）
```

“批准方案”和“批准实际代码改动”是两次不同的管理员操作。

## 方案协作对话

- 每条管理员意见对应一次新的只读仓库调查，原始医生对话不会被改写或混入管理员意见。
- 下一轮调查会携带最近 5 轮已完成调查的管理员意见、结论、代码证据、建议改动、风险和验证步骤，因此属于同一个持续方案审查过程。
- 页面默认只展示当前结论、根因、拟修改内容、风险和待确认事项；文件范围、逐行代码证据、验证细节和执行任务书默认折叠。
- 调查提示词要求所有面向管理员的叙述字段使用简体中文；仓库路径、代码标识、API 名称和既有产品标签可以保留英文。
- 结构化字段编辑保留为高级入口。正常审查应优先直接告诉 Codex，例如：“不要改 importer，只处理补打标签后的前端状态刷新，并说明这个范围是否足够。”

受控 Codex 从仓库根目录 `/home/Larry/code/Ziqiu/LabelSystem` 启动，因此适用根目录 `AGENTS.md`。该文件规定只读调查、生产数据边界、禁止部署和验证入口，并不要求英文输出。

## 管理员实际需要做什么

正常情况下，负责人不需要执行 Git 命令：

1. 检查问题单是否准确；必要时修正问题范围。
2. 在“方案协作对话”里用自然语言追问，直到当前结论和修改范围可以接受。
3. 点击“确认方案”。这只冻结方案，不会修改代码。
4. 点击“启动受控 Codex”。控制器自动从方案绑定的干净 commit 创建独立 worktree。
5. 查看实时记录、代码 diff 和固定测试；通过后点击“批准实际改动”。
6. 点击“合并”。控制器只做 fast-forward 合并，仍不会发布、重启或 push。

只有出现“主仓库不干净”或“基线已前进”时，才需要先让服务器维护者/Codex 整理并提交一份新的可运行基线，再重新调查。负责人不需要自行 stash、rebase 或手工处理 worktree。

## 执行前硬门禁

- 方案必须绑定有效的 40 位 base SHA。
- 调查时仓库必须干净，包括未跟踪文件。
- 执行时当前 HEAD 必须仍等于方案 base SHA，且主工作树仍干净。
- 方案必须冻结允许修改的文件清单。
- 任一条件不满足均返回 409，不创建可写 Codex 任务。

这意味着当前长期未提交的工作树必须先由负责人整理成完整、可运行、可追溯的代码基线，再重新调查问题。系统不会自动 stash、复制或提交这些改动。

## 执行隔离

- Worktree 默认位于仓库同级的 `LabelSystem_codex_worktrees/<run_id>`。
- Codex 固定使用 `approval=never`、`workspace-write`、`ephemeral`。
- 子进程环境使用白名单，不继承数据库 URI、SSH Agent、云凭据和生产路径。
- 不向修改执行器传入反馈附件、DICOM 或病例路径。
- 固定验证命令在 Bubblewrap 只读根文件系统、断网环境中运行；只有执行 worktree 和专用临时目录可写。
- Codex 不负责 commit、merge、push、部署或服务控制；候选 commit 由可信控制器生成。

## Diff 门禁

以下情况会直接失败关闭：

- 超出批准文件范围（测试文件可放在 `tests/`）
- 触及 `.git`、`.env`、`backend/instance`、`deployment`、数据/病例目录
- 新增数据库、DICOM、NIfTI、私钥或证书文件
- 符号链接、路径逃逸、超过 80 个文件、单文件或总 diff 超过 2 MB
- `git diff --check`、Python 编译或前端构建失败

## 审计产物

每次执行保存在：

```text
backend/instance/feedback_execution_runs/<run_id>/
```

主要文件：

- `request.json`：批准时冻结的问题和方案快照
- `runner-events.jsonl`：控制器阶段与命令审计
- `events.jsonl`：Codex JSON 事件流
- `stderr.log`：Codex 错误输出
- `summary.txt`：Codex 最终总结
- `changed_files.json`、`changes.diff`、`diff.stat`
- `controller.log`、`tests.json`
- `merge.json`：合并记录，并明确 `release_performed=false`

管理页面通过轮询展示实时事件、diff、固定测试和人工审查状态。执行日志、diff、停止、批准和合并接口只允许管理员。

## 合并门禁

- 候选必须通过固定测试并处于 `review_approved`。
- 管理员必须提交页面显示的完整 candidate SHA 二次确认。
- 候选必须是 base SHA 的单一子提交。
- 当前目标分支、HEAD 和主工作树必须与批准时完全一致。
- 只允许 `git merge --ff-only`，不自动 rebase、不自动解冲突。

目标分支前进或工作树变脏时，合并会被阻断；重新建立基线后重新调查和执行。

## 服务中断

服务重启时，尚未完成的代码生成记录会标记为 `failed / interrupted_by_restart`，保留日志和 worktree，禁止自动重放。若中断发生在最终合并阶段，记录退回 `review_approved / merge_interrupted`；管理员重新点击合并时，控制器会核对 HEAD 和 candidate SHA，幂等确认已完成的 fast-forward 或安全重试。旧版只有 `queued` 状态、没有 execution 记录的问题不会被自动消费。
