# CMR product program

This directory governs modular development of CMR Workstation product capabilities.

## Scope

- Shared CMR geometry, registration, contour, measurement, provenance and quality contracts.
- Cine function, cine strain, T1 Mapping, LGE/T2, perfusion and 4D Flow modules.
- Technical verification, physician review and controlled integration.

Routine production maintenance belongs to ordinary workstation issues. Lung-cancer EHR governance remains isolated under its own `zian_workspace/ehr_pipeline` rules.

## Read order

1. `ARCHITECTURE.md`
2. Relevant accepted decisions under `decisions/`
3. `ROADMAP.md`
4. `HANDOFF_CONTRACT.md`
5. `GIT_WORKFLOW.md`
6. `SESSION_REGISTRY.md`
7. The selected feature specification and status

Current repository decision:

- `decisions/ADR-001-repository-boundary.md`: keep CMR product runtime code in
  the LabelSystem monorepo for M0 and define the conditions for reconsidering a
  split.

Cloud planning sessions should also use `CLOUD_PROJECT_INSTRUCTIONS.md`. Active plans live in one private GitHub issue per feature; accepted contracts and execution evidence live in this repository and its pull requests.

多平台 agent 的读取顺序、角色分工、启动 prompt 和收尾检查见 `SESSION_PLAYBOOK.md`。

功能状态与静态看板：

- `features/<session>/STATUS.md`：每个 session 的机器可读状态和人类摘要；
- `features/STATUS_TEMPLATE.md`：新功能复制的状态模板；
- `CODEX_TASK_REGISTRY.json`：人工筛选的 CMR 产品 Codex 对话追溯表，只保存任务ID、标题、对应session和状态快照；
- `dashboard/index.html`：由 `scripts/cmr/render_status_board.py` 生成的只读、自包含看板；
- `dashboard/README.md`：本地打开和 GitHub Pages 隐私边界。

Chat history is not the source of truth. Update these files at each handoff.
