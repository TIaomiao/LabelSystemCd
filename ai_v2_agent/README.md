# AI_V2 Agent Runner

这个目录是 LabelSystem 侧的干净封装，用来调用 `/home/Larry/code/Ziqiu/MRIAgent/nlp_metric/agent` 里的新版 Agent，并把输出稳定写到报告评分页面可读取的位置。

## 目录职责

- `config.py`：集中管理路径、API、模型、输出目录，支持环境变量覆盖。
- `run_single.py`：单病例运行入口，屏蔽学生代码里硬编码的 conda state 权限问题。
- `run_batch.py`：150 例批量入口，复用已完成的心功能验收 `metrics.json`，再运行 AI_V2 的 `precompute + llm`。

## 默认配置

- API Base：`https://a.loping151.net/v1`
- 模型：`[j]gpt-5.4`
- 输出目录：`/home/Larry/code/Ziqiu/MRIAgent/src/output/AI_V2_report150`
- 病例清单：`tmp/km_report150_raw_agent_cases.json`
- 心功能指标来源：`/home/Larry/code/Ziqiu/MRIAgent/results/cardiac_function_km_report150_raw_20260428/outputs/CMR_ALL`

## 单例运行

```bash
cd /home/Larry/code/Ziqiu/LabelSystem
/home/Larry/miniconda3/envs/m3dd/bin/python ai_v2_agent/run_single.py \
  --center CMR_ALL \
  --patient-id "0000978064_20250120_he jian ping" \
  --mode llm
```

如果没有 `metrics_merged.json`，先跑：

```bash
/home/Larry/miniconda3/envs/m3dd/bin/python ai_v2_agent/run_single.py \
  --center CMR_ALL \
  --patient-id "0000978064_20250120_he jian ping" \
  --mode precompute
```

## 批量运行

```bash
cd /home/Larry/code/Ziqiu/LabelSystem
/home/Larry/miniconda3/bin/python /home/Larry/.codex/skills/long-experiment-runner/scripts/expctl.py \
  start ai_v2_agent/manifest_report150.json \
  --state tmp/ai_v2_report150_state.json \
  --detach
```

查看进度：

```bash
/home/Larry/miniconda3/bin/python /home/Larry/.codex/skills/long-experiment-runner/scripts/expctl.py \
  status tmp/ai_v2_report150_state.json --tail 80
```

## 环境变量覆盖

- `AI_V2_API_KEY`
- `AI_V2_API_BASE`
- `AI_V2_MODEL`
- `AI_V2_LGE_MODEL`
- `AI_V2_OUTPUT_ROOT`
- `AI_V2_GPU`
- `AI_V2_CASES_JSON`
- `AI_V2_FUNCTION_METRICS_ROOT`

## 页面读取

报告评分页面通过 `report_version=AI_V2` 读取：

`/home/Larry/code/Ziqiu/MRIAgent/src/output/AI_V2_report150/CMR_ALL/<病例>/report.json`
