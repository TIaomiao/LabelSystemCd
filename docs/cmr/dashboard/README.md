# CMR Session 看板

这是一个只读静态看板原型。页面状态来自各功能的 `STATUS.md` 机器区块，对话追溯来自人工筛选的
`docs/cmr/CODEX_TASK_REGISTRY.json`；看板不写状态、不连接数据库、不读取服务器运行目录。

正式门禁必须把当前提交证据与历史证据分开，并显示核验时间和新鲜度。Codex 对话状态只是带时间的快照，
不会自动证明任务仍在运行；工作站维护和 EHR 治理对话不得登记到本看板。

给云端 GPT、DeepSeek、Kimi 等外部规划/审查平台读取的纯文本上下文包是 `CONTEXT_PACKET.md`。它只包含脱敏工程状态，不能替代 Issue、PR、测试或医生验收证据。

## 本地打开

在仓库根目录运行：

```text
python scripts/cmr/render_status_board.py
```

然后直接双击 `docs/cmr/dashboard/index.html`。页面是自包含 HTML，不需要端口、SSH 隧道或常驻服务。上下文包用普通 Markdown 打开或上传给外部模型。

## GitHub Pages 边界

只有确认仓库 Pages 访问控制不会把工程状态暴露给无关人员后，才考虑发布。页面只能包含 session、分支短 commit、Issue/PR编号、测试状态、阻塞和下一步；不得加入病例、DICOM、服务器路径、日志、token或模型信息。

当前推荐先把它作为仓库内静态产物和本地预览，不自动发布。

状态字段和跨平台交接 prompt 见 `docs/cmr/SESSION_PLAYBOOK.md`。看板不替代 GitHub Issue、PR、CI 或医生验收记录。
