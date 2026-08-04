# AI 专家受控 Codex 执行工作流

## 目标

反馈 AI 只负责把医生对话整理为问题单；只读 Codex 调查真实仓库并生成带 commit、文件范围、风险和验证方式的方案。管理员批准方案后，修改必须发生在独立 Git worktree，形成候选提交，经过第二次人工批准才能合并。合并不等于发布，不会重启服务或推送远端。

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
