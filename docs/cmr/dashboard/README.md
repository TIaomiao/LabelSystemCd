# CMR Session 看板

这是一个只读静态看板原型。页面数据来自各功能的 `STATUS.md` 机器区块；看板不写状态、不连接数据库、不读取服务器运行目录。

## 本地打开

在仓库根目录运行：

```text
python scripts/cmr/render_status_board.py
```

然后直接双击 `docs/cmr/dashboard/index.html`。页面是自包含 HTML，不需要端口、SSH 隧道或常驻服务。

## GitHub Pages 边界

只有确认仓库 Pages 访问控制不会把工程状态暴露给无关人员后，才考虑发布。页面只能包含 session、分支短 commit、Issue/PR编号、测试状态、阻塞和下一步；不得加入病例、DICOM、服务器路径、日志、token或模型信息。

当前推荐先把它作为仓库内静态产物和本地预览，不自动发布。
