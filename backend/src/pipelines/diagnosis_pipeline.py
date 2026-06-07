from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from agents.main_agent import MainAgent
from config.settings import (
    LOG_DIR,
    OUTPUT_DIR,
    SRC_DIR,
    TEMP_DIR,
    AVAILABLE_METRICS,
    FOUR_CH_SEG_MODEL_DIR,
    SAX_SEG_MODEL_DIR,
)
from core.data_loader import PatientCase, load_patient_case
from tools.dicom_utils import DicomSeriesProcessor
from tools.measurement_tools import (
    calculate_lvef,
    calculate_lv_rv_volume_ratio,
    calculate_lv_sphericity_index,
    calculate_relative_wall_thickness,
    calculate_rvef,
    calculate_stroke_volume,
    compute_label_volume_ml,
    measure_atrial_volumes,
    measure_sax_metrics,
)
from tools.phase_selector import PhaseVolume, compute_lv_volume_ml, determine_ed_es, compute_lv_diameter_mm
from tools.segmentation_runner import SegmentationRunner
from tools.sequence_classifier import SequenceClassifier
from utils.logging_utils import setup_logger


METRIC_DEFINITIONS = {
    "LVEDV": {
        "source": "sax",
        "path": ("lv", "EDV_ml"),
        "unit": "mL",
        "log_tool": "左心室容积测量工具 calculate_lv_volume",
    },
    "LVESV": {
        "source": "sax",
        "path": ("lv", "ESV_ml"),
        "unit": "mL",
        "log_tool": "左心室容积测量工具 calculate_lv_volume（ES阶段）",
    },
    "LVEF": {
        "source": "sax",
        "path": ("lv", "EF_percent"),
        "unit": "%",
        "log_tool": "左心室射血分数计算工具 calculate_lvef",
    },
    "SV": {
        "source": "sax",
        "path": ("lv", "SV_ml"),
        "unit": "mL",
        "log_tool": "每搏输出量计算工具 calculate_stroke_volume",
    },
    "RVEDV": {
        "source": "sax",
        "path": ("rv", "EDV_ml"),
        "unit": "mL",
        "log_tool": "右心室容积测量工具 calculate_rv_volume",
    },
    "RVESV": {
        "source": "sax",
        "path": ("rv", "ESV_ml"),
        "unit": "mL",
        "log_tool": "右心室容积测量工具 calculate_rv_volume（ES阶段）",
    },
    "RVEF": {
        "source": "sax",
        "path": ("rv", "EF_percent"),
        "unit": "%",
        "log_tool": "右心室射血分数计算工具 calculate_rvef",
    },
    "LVEDD": {
        "source": "sax",
        "path": ("structure", "lv_inner_diameter_mm"),
        "unit": "mm",
        "log_tool": "左心室内径测量工具 calculate_lv_inner_diameter",
    },
    "RVEDD": {
        "source": "sax",
        "path": ("structure", "rv_inner_diameter_mm"),
        "unit": "mm",
        "log_tool": "右心室内径测量工具 calculate_rv_inner_diameter",
    },
    "LAV": {
        "source": "four_ch",
        "path": ("LA_volume_ml",),
        "unit": "mL",
        "log_tool": "左心房容积测量工具 calculate_la_volume",
    },
    "RAV": {
        "source": "four_ch",
        "path": ("RA_volume_ml",),
        "unit": "mL",
        "log_tool": "右心房容积测量工具 calculate_ra_volume",
    },
    "IVS": {
        "source": "sax",
        "path": ("structure", "ivs_thickness_mm"),
        "unit": "mm",
        "log_tool": "室间隔厚度测量工具 calculate_ivs_thickness",
    },
    "LVPW": {
        "source": "sax",
        "path": ("structure", "lvpw_thickness_mm"),
        "unit": "mm",
        "log_tool": "左室后壁厚度测量工具 calculate_lvpw_thickness",
    },
    "RWT": {
        "source": "sax",
        "path": ("derived_metrics", "relative_wall_thickness"),
        "unit": "",
        "log_tool": "相对壁厚计算工具 calculate_relative_wall_thickness",
    },
    "SI": {
        "source": "sax",
        "path": ("derived_metrics", "lv_sphericity_index"),
        "unit": "",
        "log_tool": "球形指数计算工具 calculate_lv_sphericity_index",
    },
    "LV/RV ratio": {
        "source": "sax",
        "path": ("derived_metrics", "lv_rv_volume_ratio"),
        "unit": "",
        "log_tool": "LV/RV容积比计算工具 calculate_lv_rv_volume_ratio",
    },
}


class DiagnosisPipeline:
    def __init__(self, event_emitter: Optional[Callable] = None) -> None:
        self.logger = setup_logger(LOG_DIR / "diagnosis.log", "diagnosis")
        self.main_agent = MainAgent()
        self.seq_classifier = SequenceClassifier()
        self.seg_runner = SegmentationRunner()
        self.event_emitter = event_emitter or self._default_emitter
        self.workflow_graph: Dict = {}
        self.tool_node_map: Dict[str, str] = {}
        self.metric_tool_map: Dict[str, str] = {}
        self.measurement_node_id: Optional[str] = None
        self.report_node_id: Optional[str] = None

    def emit_event(self, event_type: str, content: Dict, workflow_tag: str = None) -> None:
        """发射事件用于流式输出"""
        from datetime import datetime, timezone
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "workflow_tag": workflow_tag,
            "content": content,
        }
        if self.event_emitter:
            self.event_emitter(event)

    def _default_emitter(self, event: Dict) -> None:
        """默认事件发射器（空实现）"""
        pass

    def run(self, patient_id: str, custom_prompt: Optional[str] = None) -> Dict:
        """
        执行诊断管道

        Args:
            patient_id: 患者 ID
            custom_prompt: 自定义诊断提示（可选，如果提供则覆盖 patient_info.json 中的）
        """
        self.logger.info("开始处理患者 %s", patient_id)
        patient = load_patient_case(patient_id)

        # 每次诊断使用独立的输出目录，避免覆盖历史
        from datetime import datetime, timezone
        self.run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
        base_patient_dir = OUTPUT_DIR / patient.patient_id
        self.output_root = base_patient_dir / self.run_id
        self.output_root.mkdir(parents=True, exist_ok=True)

        # 如果提供了 custom_prompt，更新 patient_info
        if custom_prompt:
            patient.patient_info['imaging_goal'] = custom_prompt
            self.logger.info("使用自定义诊断提示: %s", custom_prompt)

        available_sequences = [
            name for name, path in patient.sequences.items() if path is not None and path.exists()
        ]
        plan = self.main_agent.generate_plan(patient.patient_info, available_sequences)
        requested_metric_names = self._extract_requested_metrics(plan)
        self.logger.info("诊断计划: %s", json.dumps(plan, ensure_ascii=False))

        # 生成 workflow_graph（根据诊断计划）
        workflow_graph = self._generate_workflow_graph(plan)
        self.workflow_graph = workflow_graph
        # 建立工具映射和测量节点ID，方便日志标记
        self.tool_node_map = {
            node.get("title"): node.get("id")
            for node in workflow_graph.get("nodes", [])
            if node.get("type") == "tool"
        }
        self.measurement_node_id = next(
            (
                node.get("id")
                for node in workflow_graph.get("nodes", [])
                if node.get("title") == "测量指标" or node.get("id") == "measurements"
            ),
            None
        )
        self.report_node_id = next(
            (
                node.get("id")
                for node in workflow_graph.get("nodes", [])
                if node.get("id") == "report" or node.get("title") == "生成诊断报告"
            ),
            None
        )
        self.metric_tool_map = {}
        measurements_section = plan.get("measurements", {})
        for metric in measurements_section.get("metrics", []):
            name = metric.get("name")
            tool = metric.get("tool")
            if name and tool:
                self.metric_tool_map[name] = tool

        # 发射诊断计划事件
        self.emit_event(
            "diagnostic_plan",
            {
                "plan": plan,
                "workflow_graph": workflow_graph
            }
        )

        # 节点1：序列分类
        self.emit_event(
            "workflow_node_start",
            {"node_id": "seq_class", "title": "序列分类"},
            workflow_tag="seq_class"
        )

        seq_results = self._classify_sequences(patient)

        # 发射序列分类日志
        logs = [
            f"序列 {r['sequence']} 判定为 {r['pred_label']} (置信度: {r['confidence']:.2f})"
            for r in seq_results
        ]
        self.emit_event(
            "log_detail",
            {"node_id": "seq_class", "logs": logs},
            workflow_tag="seq_class"
        )

        self.emit_event(
            "workflow_node_end",
            {"node_id": "seq_class", "status": "success"},
            workflow_tag="seq_class"
        )

        # 节点2+：测量指标
        orchestrator = MeasurementOrchestrator(
            pipeline=self,
            patient=patient,
        )
        if self.measurement_node_id:
            self.emit_event(
                "workflow_node_start",
                {"node_id": self.measurement_node_id, "title": "测量指标"},
                workflow_tag=self.measurement_node_id
            )
        requested_measurements = orchestrator.measure_all(requested_metric_names)

        combined_metrics = {
            "sequence_classification": seq_results,
            "requested_metrics": requested_measurements,
            "raw_measurements": orchestrator.raw_outputs(),
        }

        report = self.main_agent.generate_report(
            patient_info=patient.patient_info,
            plan=plan,
            metrics=combined_metrics,
        )

        output_dir = self.output_root
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if self.report_node_id:
            self.emit_event(
                "workflow_node_start",
                {"node_id": self.report_node_id, "title": "生成诊断报告"},
                workflow_tag=self.report_node_id
            )

        # 保存metrics和report
        with (output_dir / "metrics.json").open("w", encoding="utf-8") as f:
            json.dump(combined_metrics, f, ensure_ascii=False, indent=2)
        with (output_dir / "report.json").open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # 生成工作流程日志
        self._generate_workflow_log(
            output_dir=output_dir,
            patient_info=patient.patient_info,
            plan=plan,
            metrics=combined_metrics,
        )
        if self.measurement_node_id:
            self.emit_event(
                "workflow_node_end",
                {"node_id": self.measurement_node_id, "status": "success"},
                workflow_tag=self.measurement_node_id
            )
        if self.report_node_id:
            self.emit_event(
                "log_detail",
                {"message": "报告生成完成"},
                workflow_tag=self.report_node_id
            )
            self.emit_event(
                "workflow_node_end",
                {"node_id": self.report_node_id, "status": "success"},
                workflow_tag=self.report_node_id
            )

        # 兼容旧路径：复制关键文件到患者根目录，便于前端访问
        try:
            import shutil
            base_patient_dir.mkdir(parents=True, exist_ok=True)
            for filename in ["report.json", "metrics.json", "workflow.log"]:
                src = output_dir / filename
                if src.exists():
                    shutil.copy2(src, base_patient_dir / filename)
        except Exception as copy_err:
            self.logger.warning("复制最新结果到根目录时出错: %s", copy_err)

        self.logger.info("处理完成，结果保存至 %s", output_dir)
        return {
            "plan": plan,
            "metrics": combined_metrics,
            "report": report,
            "output_dir": str(output_dir),
        }

    def _generate_workflow_graph(self, plan: Dict) -> Dict:
        """
        根据诊断计划生成 workflow 图
        动态提取诊断计划中的步骤和工具，生成完整的工作流节点

        Returns:
            包含 nodes 和 edges 的 workflow_graph 字典
        """
        nodes = []
        edges = []
        diagnosis_plan = plan.get("diagnosis_plan", {})

        # 节点1: 序列分类
        nodes.append({
            "id": "seq_class",
            "title": "序列分类",
            "description": diagnosis_plan.get("sequence_classification", {}).get("description",
                          "识别可用的心脏 MRI 序列"),
            "type": "step",
            "stage": 1
        })
        previous_node = "seq_class"

        # 节点2: 时期检测（来自 phase_detection）
        if "phase_detection" in diagnosis_plan:
            phase_detection = diagnosis_plan["phase_detection"]
            nodes.append({
                "id": "phase_detect",
                "title": "时期检测",
                "description": phase_detection.get("description",
                              "检测舒张末期(ED)和收缩末期(ES)"),
                "type": "step",
                "stage": 2
            })
            edges.append({"from": previous_node, "to": "phase_detect"})
            previous_node = "phase_detect"

        # 节点3+: 从 measurements 中提取工具节点
        tools_seen = set()
        measurement_node_id = None

        if "measurements" in diagnosis_plan:
            measurements = diagnosis_plan["measurements"]

            # 创建 measurements 步骤节点
            measurement_node_id = "measurements"
            nodes.append({
                "id": measurement_node_id,
                "title": "测量指标",
                "description": measurements.get("description",
                              "测量关键的心脏结构和功能指标"),
                "type": "step",
                "stage": 3
            })
            edges.append({"from": previous_node, "to": measurement_node_id})

            # 从 metrics 中提取唯一的工具
            metrics = measurements.get("metrics", [])
            tool_nodes_map = {}  # 用于跟踪工具节点

            for i, metric in enumerate(metrics):
                tool_name = metric.get("tool", "")
                metric_name = metric.get("name", "")

                if tool_name and tool_name not in tools_seen:
                    tools_seen.add(tool_name)

                    # 为工具创建节点ID（使用工具名称的简化版本）
                    tool_id = f"tool_{len(tool_nodes_map)}"
                    tool_nodes_map[tool_name] = tool_id

                    # 添加工具节点
                    nodes.append({
                        "id": tool_id,
                        "title": tool_name,
                        "description": f"用于 {metric_name}",
                        "type": "tool",
                        "metrics": [],  # 稍后填充
                        "stage": 4
                    })

                    # 连接到测量指标节点
                    edges.append({"from": measurement_node_id, "to": tool_id})

            # 为每个工具节点添加关联的指标
            for metric in metrics:
                tool_name = metric.get("tool", "")
                metric_name = metric.get("name", "")
                if tool_name in tool_nodes_map:
                    tool_id = tool_nodes_map[tool_name]
                    # 找到对应的节点并添加指标
                    for node in nodes:
                        if node["id"] == tool_id:
                            if "metrics" not in node:
                                node["metrics"] = []
                            node["metrics"].append({
                                "name": metric_name,
                                "reason": metric.get("reason", "")
                            })
                            break

        # 最后一个节点: 生成诊断报告
        report_node_id = "report"
        nodes.append({
            "id": report_node_id,
            "title": "生成诊断报告",
            "description": "根据测量结果生成诊断报告",
            "type": "step",
            "stage": 5
        })

        # 连接到报告节点
        if measurement_node_id:
            # 从所有工具节点连接到报告
            for node in nodes:
                if node.get("type") == "tool":
                    edges.append({"from": node["id"], "to": report_node_id})
        else:
            # 如果没有工具，直接从测量或时期检测连接
            edges.append({"from": previous_node, "to": report_node_id})

        return {
            "nodes": nodes,
            "edges": edges
        }

    # === 内部步骤 ===

    def _classify_sequences(self, patient: PatientCase) -> List[Dict]:
        self.logger.info("执行序列分类")
        results = []
        previews_dir = (self.output_root or OUTPUT_DIR / patient.patient_id) / "previews"
        previews_dir.mkdir(parents=True, exist_ok=True)

        for name, path in patient.sequences.items():
            if path is None or not path.exists():
                continue
            processor = DicomSeriesProcessor(path)
            preview_img = previews_dir / f"{name}.png"
            processor.export_preview_png(preview_img)
            question = "请判断该心脏MRI图像是4CH、SAX还是LGE序列？"
            pred = self.seq_classifier.predict(preview_img, question)
            result = {
                "sequence": name,
                "pred_label": pred["pred_label"],
                "confidence": pred["confidence"],
                "probabilities": pred["probabilities"],
                "preview_path": f"{self.run_id}/previews/{name}.png" if self.run_id else f"previews/{name}.png",
            }
            results.append(result)
            self.logger.info("序列 %s 判定为 %s (%.2f)", name, pred["pred_label"], pred["confidence"])
        return results

    def _process_sax(self, patient: PatientCase) -> Dict:
        """
        处理SAX序列的完整流程：
        1. 将所有DICOM按时间点转为独立的3D NIfTI
        2. 对每个3D NIfTI进行分割
        3. 测量每帧的关键指标（体积、内径）
        4. 根据测量指标判定ED/ES
        5. 计算最终功能指标
        """
        path = patient.sequences.get("SAX")
        if path is None or not path.exists():
            self.logger.warning("缺少SAX序列")
            return {}

        self.logger.info("处理SAX序列：%s", path)
        processor = DicomSeriesProcessor(path)
        
        sax_temp_dir = TEMP_DIR / patient.patient_id / (self.run_id or "current") / "SAX"
        sax_temp_dir.mkdir(parents=True, exist_ok=True)
        sax_seg_dir = (self.output_root or OUTPUT_DIR / patient.patient_id) / "segmentations" / "SAX"
        sax_seg_dir.mkdir(parents=True, exist_ok=True)

        # 步骤1: 转换所有时间点为NIfTI
        self.logger.info("步骤1: 将DICOM按时间点转换为NIfTI")
        timepoints = processor.convert_all_timepoints_to_nifti(sax_temp_dir)
        self.logger.info("共 %d 个时间点", len(timepoints))
        
        # 步骤2-3: 分割每个时间点并测量
        self.logger.info("步骤2-3: 分割并测量每个时间帧")
        self.logger.info("共 %d 个时间点需要处理", len(timepoints))
        phases: List[PhaseVolume] = []
        
        # 预加载模型（首次使用时会加载，后续复用）
        # 注意：模型会在第一次调用run()时自动加载并缓存
        self.logger.info("准备处理 %d 个时间点，模型将在首次分割时加载（约10-30秒）...", len(timepoints))
        
        # 处理每个时间点
        for idx, tp in enumerate(timepoints, 1):
            self.logger.info("处理时间点 %d/%d: Trigger %.0f ms", idx, len(timepoints), tp.trigger_time)
            
            if tp.nifti_path is None or not tp.nifti_path.exists():
                self.logger.warning("时间点 %.0f ms 的NIfTI不存在", tp.trigger_time)
                continue
            
            # 验证NIfTI
            if not self._verify_nifti(tp.nifti_path):
                self.logger.warning("NIfTI文件无效: %s", tp.nifti_path)
                continue
            
            # 分割
            seg_filename = f"sax_tt{int(tp.trigger_time):04d}.nii.gz"
            pred_path = sax_seg_dir / seg_filename
            
            if not pred_path.exists():
                try:
                    # 检查是否是首次使用（模型是否已加载）
                    model_key = f"{SAX_SEG_MODEL_DIR}_('0',)_checkpoint_final.pth"
                    is_first_run = model_key not in getattr(self.seg_runner, '_predictor_cache', {})
                    
                    if is_first_run:
                        self.logger.info("  首次运行：正在加载SAX分割模型（约10-30秒，请耐心等待）...")
                    else:
                        self.logger.info("  运行nnU-Net分割（模型已加载，预计10-15秒）...")
                    
                    pred_path = self.seg_runner.run(
                        image_path=tp.nifti_path,
                        model_dir=SAX_SEG_MODEL_DIR,
                        output_dir=sax_seg_dir,
                    )
                    
                    if is_first_run:
                        self.logger.info("  模型加载完成，分割完成: %s", pred_path.name)
                    else:
                        self.logger.info("  分割完成: %s", pred_path.name)
                    
                    # 每个时间点处理后清理GPU缓存，避免显存累积
                    import torch
                    if torch.cuda.is_available():
                        try:
                            with torch.cuda.device(0):
                                torch.cuda.empty_cache()
                                torch.cuda.synchronize()
                        except Exception:
                            pass
                        # 等待一小段时间，确保后台worker完成
                        import time
                        time.sleep(0.5)
                        
                except RuntimeError as e:
                    error_msg = str(e).lower()
                    if "out of memory" in error_msg or "cudnn_status_alloc_failed" in error_msg:
                        self.logger.error("GPU显存不足，尝试清理缓存后重试...")
                        import torch
                        if torch.cuda.is_available():
                            try:
                                with torch.cuda.device(0):
                                    torch.cuda.empty_cache()
                                    torch.cuda.synchronize()
                            except Exception:
                                pass
                        import time
                        time.sleep(2)
                        try:
                            pred_path = self.seg_runner.run(
                                image_path=tp.nifti_path,
                                model_dir=SAX_SEG_MODEL_DIR,
                                output_dir=sax_seg_dir,
                            )
                            self.logger.info("  重试成功，分割完成: %s", pred_path.name)
                        except Exception as retry_e:
                            self.logger.error("重试失败: %s", retry_e)
                            continue
                    elif "invalid device ordinal" in error_msg:
                        self.logger.error("检测到无效的GPU设备ID，回退到当前设备后重试...")
                        import torch
                        if torch.cuda.is_available():
                            try:
                                with torch.cuda.device(0):
                                    torch.cuda.empty_cache()
                                    torch.cuda.synchronize()
                            except Exception:
                                pass
                        import time
                        time.sleep(1)
                        try:
                            pred_path = self.seg_runner.run(
                                image_path=tp.nifti_path,
                                model_dir=SAX_SEG_MODEL_DIR,
                                output_dir=sax_seg_dir,
                            )
                            self.logger.info("  重试成功，分割完成: %s", pred_path.name)
                        except Exception as retry_e:
                            self.logger.error("重试失败: %s", retry_e)
                            continue
                    else:
                        self.logger.error("分割失败 %s: %s", tp.nifti_path, e)
                        import traceback
                        self.logger.error(traceback.format_exc())
                        continue
                except Exception as e:
                    self.logger.error("分割失败 %s: %s", tp.nifti_path, e)
                    import traceback
                    self.logger.error(traceback.format_exc())
                    continue
            else:
                self.logger.info("  使用已存在的分割结果: %s", pred_path.name)
            
            # 验证分割结果
            if not self._verify_nifti(pred_path):
                self.logger.warning("分割结果无效: %s", pred_path)
                continue
            
            # 测量关键指标
            self.logger.info("  测量关键指标...")
            lv_volume = compute_lv_volume_ml(pred_path, lv_label_id=3)
            lv_diameter = compute_lv_diameter_mm(pred_path)
            
            phases.append(
                PhaseVolume(
                    phase_name="",
                    seg_path=pred_path,
                    lv_volume_ml=lv_volume,
                    lv_diameter_mm=lv_diameter,
                    raw_trigger=tp.trigger_time,
                )
            )
            self.logger.info(
                "  ✓ 完成: Trigger %.0f ms, LV体积 %.2f mL, LV内径 %.2f mm",
                tp.trigger_time,
                lv_volume,
                lv_diameter if lv_diameter else 0.0,
            )

        if not phases:
            self.logger.error("没有有效的SAX分割结果")
            return {}

        # 步骤4: 根据体积判定ED/ES
        self.logger.info("步骤4: 根据LV体积判定ED/ES")
        ed_es = determine_ed_es(phases, method="volume")
        self.logger.info(
            "判定结果: ED=Trigger %.0f ms (%.2f mL), ES=Trigger %.0f ms (%.2f mL)",
            ed_es["ED"].raw_trigger,
            ed_es["ED"].lv_volume_ml,
            ed_es["ES"].raw_trigger,
            ed_es["ES"].lv_volume_ml,
        )
        
        # 保存ED/ES关键帧到专门目录
        self._save_key_frames(
            phases=phases,
            ed_frame=ed_es["ED"],
            es_frame=ed_es["ES"],
            sequence_name="SAX",
            patient_id=patient.patient_id,
        )

        # 步骤5: 计算最终指标
        self.logger.info("步骤5: 计算心功能指标")
        lv_ed = ed_es["ED"].lv_volume_ml
        lv_es = ed_es["ES"].lv_volume_ml
        lv_sv = calculate_stroke_volume(lv_ed, lv_es)
        lvef = calculate_lvef(lv_ed, lv_es)

        rv_ed = compute_label_volume_ml(ed_es["ED"].seg_path, label_id=1)
        rv_es = compute_label_volume_ml(ed_es["ES"].seg_path, label_id=1)
        rv_sv = calculate_stroke_volume(rv_ed, rv_es)
        rvef = calculate_rvef(rv_ed, rv_es)

        # 在ED帧上测量结构指标
        viz_dir = (self.output_root or OUTPUT_DIR / patient.patient_id) / "measurements" / "SAX_ED"
        vent_metrics = measure_sax_metrics(ed_es["ED"].seg_path, viz_dir=viz_dir)

        return {
            "lv": {
                "EDV_ml": lv_ed,
                "ESV_ml": lv_es,
                "SV_ml": lv_sv,
                "EF_percent": lvef,
            },
            "rv": {
                "EDV_ml": rv_ed,
                "ESV_ml": rv_es,
                "SV_ml": rv_sv,
                "EF_percent": rvef,
            },
            "structure": {
                "lv_inner_diameter_mm": vent_metrics.lv_inner_diameter_mm,
                "rv_inner_diameter_mm": vent_metrics.rv_inner_diameter_mm,
                "ivs_thickness_mm": vent_metrics.ivs_thickness_mm,
                "lvpw_thickness_mm": vent_metrics.lvpw_thickness_mm,
                "visualizations": [str(p) for p in vent_metrics.visualization_paths],
            },
            "derived_metrics": {
                "relative_wall_thickness": calculate_relative_wall_thickness(
                    vent_metrics.lvpw_thickness_mm,
                    vent_metrics.lv_inner_diameter_mm,
                ),
                "lv_sphericity_index": calculate_lv_sphericity_index(
                    lv_ed,
                    vent_metrics.lv_inner_diameter_mm,
                ),
                "lv_rv_volume_ratio": calculate_lv_rv_volume_ratio(lv_ed, rv_ed),
            },
            "phase_assignments": {
                "ED_trigger": ed_es["ED"].raw_trigger,
                "ES_trigger": ed_es["ES"].raw_trigger,
            },
        }

    def _process_4ch(self, patient: PatientCase) -> Dict:
        """
        处理4CH序列的完整流程：
        1. 将所有DICOM按时间点转为独立的3D NIfTI
        2. 对每个3D NIfTI进行分割
        3. 测量每帧的LV体积
        4. 判定ED时相
        5. 测量心房体积
        """
        path = patient.sequences.get("4CH")
        if path is None or not path.exists():
            self.logger.warning("缺少4CH序列")
            return {}

        self.logger.info("处理4CH序列：%s", path)
        processor = DicomSeriesProcessor(path)
        
        ch_temp_dir = TEMP_DIR / patient.patient_id / (self.run_id or "current") / "4CH"
        ch_temp_dir.mkdir(parents=True, exist_ok=True)
        ch_seg_dir = (self.output_root or OUTPUT_DIR / patient.patient_id) / "segmentations" / "4CH"
        ch_seg_dir.mkdir(parents=True, exist_ok=True)

        # 步骤1: 转换所有时间点为NIfTI
        self.logger.info("步骤1: 将4CH DICOM按时间点转换为NIfTI")
        timepoints = processor.convert_all_timepoints_to_nifti(ch_temp_dir)
        self.logger.info("共 %d 个时间点", len(timepoints))
        
        # 步骤2-3: 分割每个时间点并测量
        self.logger.info("步骤2-3: 分割并测量每个时间帧")
        self.logger.info("共 %d 个时间点需要处理", len(timepoints))
        phases: List[PhaseVolume] = []
        
        # 预加载模型（首次使用时会加载，后续复用）
        # 注意：模型会在第一次调用run()时自动加载并缓存
        self.logger.info("准备处理 %d 个时间点，模型将在首次分割时加载（约10-30秒）...", len(timepoints))
        
        # 处理每个时间点
        for idx, tp in enumerate(timepoints, 1):
            self.logger.info("处理时间点 %d/%d: Trigger %.0f ms", idx, len(timepoints), tp.trigger_time)
            
            if tp.nifti_path is None or not tp.nifti_path.exists():
                continue
            
            if not self._verify_nifti(tp.nifti_path):
                continue
            
            # 分割
            seg_filename = f"ch_tt{int(tp.trigger_time):04d}.nii.gz"
            pred_path = ch_seg_dir / seg_filename
            
            if not pred_path.exists():
                try:
                    # 检查是否是首次使用（模型是否已加载）
                    model_key = f"{FOUR_CH_SEG_MODEL_DIR}_('0',)_checkpoint_final.pth"
                    is_first_run = model_key not in getattr(self.seg_runner, '_predictor_cache', {})
                    
                    if is_first_run:
                        self.logger.info("  首次运行：正在加载4CH分割模型（约10-30秒，请耐心等待）...")
                    else:
                        self.logger.info("  运行nnU-Net分割（模型已加载，预计10-15秒）...")
                    
                    pred_path = self.seg_runner.run(
                        image_path=tp.nifti_path,
                        model_dir=FOUR_CH_SEG_MODEL_DIR,
                        output_dir=ch_seg_dir,
                    )
                    
                    if is_first_run:
                        self.logger.info("  模型加载完成，分割完成: %s", pred_path.name)
                    else:
                        self.logger.info("  分割完成: %s", pred_path.name)
                    
                    # 每个时间点处理后清理GPU缓存
                    import torch
                    from config.settings import CUDA_DEVICE_ID
                    if torch.cuda.is_available():
                        device_id = int(CUDA_DEVICE_ID)
                        with torch.cuda.device(device_id):
                            torch.cuda.empty_cache()
                            torch.cuda.synchronize()
                        import time
                        time.sleep(0.5)
                        
                except RuntimeError as e:
                    # 检查是否是显存不足错误
                    error_msg = str(e).lower()
                    if "out of memory" in error_msg or "cudnn_status_alloc_failed" in error_msg:
                        self.logger.error("GPU显存不足，尝试清理缓存后重试...")
                        import torch
                        if torch.cuda.is_available():
                            try:
                                with torch.cuda.device(0):
                                    torch.cuda.empty_cache()
                                    torch.cuda.synchronize()
                            except Exception:
                                pass
                        import time
                        time.sleep(2)
                        try:
                            pred_path = self.seg_runner.run(
                                image_path=tp.nifti_path,
                                model_dir=FOUR_CH_SEG_MODEL_DIR,
                                output_dir=ch_seg_dir,
                            )
                            self.logger.info("  重试成功，分割完成: %s", pred_path.name)
                        except Exception as retry_e:
                            self.logger.error("重试失败: %s", retry_e)
                            continue
                    else:
                        self.logger.error("4CH分割失败 %s: %s", tp.nifti_path, e)
                        import traceback
                        self.logger.error(traceback.format_exc())
                        continue
                except Exception as e:
                    self.logger.error("4CH分割失败 %s: %s", tp.nifti_path, e)
                    import traceback
                    self.logger.error(traceback.format_exc())
                    continue
            else:
                self.logger.info("  使用已存在的分割结果: %s", pred_path.name)
            
            if not self._verify_nifti(pred_path):
                continue
            
            # 测量LV体积
            self.logger.info("  测量LV体积...")
            lv_volume = compute_lv_volume_ml(pred_path, lv_label_id=3)
            phases.append(
                PhaseVolume(
                    phase_name="",
                    seg_path=pred_path,
                    lv_volume_ml=lv_volume,
                    lv_diameter_mm=None,
                    raw_trigger=tp.trigger_time,
                )
            )
            self.logger.info("  ✓ 完成: Trigger %.0f ms, LV体积 %.2f mL", tp.trigger_time, lv_volume)

        if not phases:
            self.logger.error("没有有效的4CH分割结果")
            return {}

        # 步骤4: 判定ED时相
        ed_es = determine_ed_es(phases, method="volume")
        self.logger.info(
            "4CH判定ED: Trigger %.0f ms (LV %.2f mL)",
            ed_es["ED"].raw_trigger,
            ed_es["ED"].lv_volume_ml,
        )
        
        # 保存ED关键帧
        self._save_key_frames(
            phases=phases,
            ed_frame=ed_es["ED"],
            es_frame=None,  # 4CH只需要ED
            sequence_name="4CH",
            patient_id=patient.patient_id,
        )

        # 步骤5: 测量心房体积（在ED时相）
        atria = measure_atrial_volumes(ed_es["ED"].seg_path, la_label=420, ra_label=550)
        return {
            "ED_trigger": ed_es["ED"].raw_trigger,
            "LA_volume_ml": atria.la_volume_ml,
            "RA_volume_ml": atria.ra_volume_ml,
        }
    
    def _save_key_frames(
        self,
        phases: List[PhaseVolume],
        ed_frame: PhaseVolume,
        es_frame: Optional[PhaseVolume],
        sequence_name: str,
        patient_id: str,
    ) -> None:
        """
        保存ED/ES关键帧到专门目录
        注意：每个ED/ES帧是一个3D体数据，包含该时刻所有切片层面
        
        参数:
            phases: 所有时间帧
            ed_frame: ED帧（体积最大的时刻）
            es_frame: ES帧（体积最小的时刻，可选）
            sequence_name: 序列名称（SAX或4CH）
            patient_id: 患者ID
        """
        import shutil
        import nibabel as nib
        
        key_frames_dir = (self.output_root or OUTPUT_DIR / patient_id) / "key_frames" / sequence_name
        key_frames_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存ED帧
        self.logger.info("保存ED关键帧")
        ed_dest = key_frames_dir / f"ED_tt{int(ed_frame.raw_trigger):04d}.nii.gz"
        if ed_frame.seg_path.exists():
            shutil.copy2(ed_frame.seg_path, ed_dest)
            
            # 获取帧信息
            img = nib.load(str(ed_frame.seg_path))
            shape = img.shape
            num_slices = shape[2] if len(shape) >= 3 else 1
            
            self.logger.info(
                "  ED帧: Trigger %.0f ms, LV体积 %.2f mL, 包含 %d 个切片层面 → %s",
                ed_frame.raw_trigger,
                ed_frame.lv_volume_ml,
                num_slices,
                ed_dest.name,
            )
        
        # 保存ES帧
        if es_frame and es_frame.seg_path.exists():
            self.logger.info("保存ES关键帧")
            es_dest = key_frames_dir / f"ES_tt{int(es_frame.raw_trigger):04d}.nii.gz"
            shutil.copy2(es_frame.seg_path, es_dest)
            
            img = nib.load(str(es_frame.seg_path))
            shape = img.shape
            num_slices = shape[2] if len(shape) >= 3 else 1
            
            self.logger.info(
                "  ES帧: Trigger %.0f ms, LV体积 %.2f mL, 包含 %d 个切片层面 → %s",
                es_frame.raw_trigger,
                es_frame.lv_volume_ml,
                num_slices,
                es_dest.name,
            )
        
        # 创建说明文件
        info_file = key_frames_dir / "README.txt"
        with info_file.open("w", encoding="utf-8") as f:
            f.write(f"{sequence_name} 序列关键帧说明\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"ED（舒张末期）帧:\n")
            f.write(f"  - 触发时间: {ed_frame.raw_trigger:.0f} ms\n")
            f.write(f"  - LV体积: {ed_frame.lv_volume_ml:.2f} mL\n")
            if ed_frame.lv_diameter_mm:
                f.write(f"  - LV内径: {ed_frame.lv_diameter_mm:.2f} mm\n")
            f.write(f"  - 文件: ED_tt{int(ed_frame.raw_trigger):04d}.nii.gz\n")
            f.write(f"  - 说明: 该文件是3D体数据，包含该时刻所有切片层面的分割结果\n\n")
            
            if es_frame:
                f.write(f"ES（收缩末期）帧:\n")
                f.write(f"  - 触发时间: {es_frame.raw_trigger:.0f} ms\n")
                f.write(f"  - LV体积: {es_frame.lv_volume_ml:.2f} mL\n")
                if es_frame.lv_diameter_mm:
                    f.write(f"  - LV内径: {es_frame.lv_diameter_mm:.2f} mm\n")
                f.write(f"  - 文件: ES_tt{int(es_frame.raw_trigger):04d}.nii.gz\n")
                f.write(f"  - 说明: 该文件是3D体数据，包含该时刻所有切片层面的分割结果\n\n")
            
            f.write(f"\n判定方法:\n")
            f.write(f"  - ED: 左心室体积最大的时刻（心室充盈最大）\n")
            f.write(f"  - ES: 左心室体积最小的时刻（心室收缩最强）\n")
            
            f.write(f"\n文件内容:\n")
            f.write(f"  - 格式: NIfTI (.nii.gz)\n")
            f.write(f"  - 维度: 3D (X, Y, Z)\n")
            f.write(f"  - 标签值:\n")
            if sequence_name == "SAX":
                f.write(f"    * 1 = 右心室 (RV)\n")
                f.write(f"    * 2 = 心肌 (MYO)\n")
                f.write(f"    * 3 = 左心室 (LV)\n")
            else:  # 4CH
                f.write(f"    * 420 = 左心房 (LA)\n")
                f.write(f"    * 500 = 左心室 (LV)\n")
                f.write(f"    * 205 = 心肌 (MYO)\n")
                f.write(f"    * 550 = 右心房 (RA)\n")
                f.write(f"    * 600 = 右心室 (RV)\n")
            
            f.write(f"\n用途:\n")
            f.write(f"  - 用于计算心功能指标（LVEF、RVEF等）\n")
            f.write(f"  - 用于测量结构参数（内径、壁厚等）\n")
            f.write(f"  - 用于生成测量可视化\n")
            f.write(f"  - 用于验证和调试算法\n")
        
        self.logger.info("关键帧已保存至: %s", key_frames_dir)
    
    def _generate_workflow_log(
        self,
        output_dir: Path,
        patient_info: Dict,
        plan: Dict,
        metrics: Dict,
    ) -> None:
        """
        生成可读的工作流程日志文件
        
        参数:
            output_dir: 输出目录
            patient_info: 患者信息
            plan: 诊断计划
            metrics: 测量结果
        """
        from datetime import datetime
        
        log_file = output_dir / "workflow.log"
        
        with log_file.open("w", encoding="utf-8") as f:
            # 标题
            f.write("=" * 80 + "\n")
            f.write("心脏MRI多智能体诊断系统 - 工作流程日志\n")
            f.write("=" * 80 + "\n\n")
            
            # 时间戳
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"患者ID: {patient_info.get('patient_id', 'N/A')}\n\n")
            
            # 第1部分：患者信息
            f.write("-" * 80 + "\n")
            f.write("第1部分：患者基本信息\n")
            f.write("-" * 80 + "\n")
            f.write(f"年龄: {patient_info.get('age', 'N/A')} 岁\n")
            f.write(f"性别: {patient_info.get('sex', 'N/A')}\n")
            f.write(f"身高: {patient_info.get('height_cm', 'N/A')} cm\n")
            f.write(f"体重: {patient_info.get('weight_kg', 'N/A')} kg\n")
            f.write(f"BMI: {patient_info.get('bmi', 'N/A')}\n")
            f.write(f"主诉: {patient_info.get('chief_complaint', 'N/A')}\n")
            
            if patient_info.get('medical_history'):
                f.write(f"既往史: {', '.join(patient_info['medical_history'])}\n")
            if patient_info.get('current_medications'):
                f.write(f"用药: {', '.join(patient_info['current_medications'])}\n")
            f.write("\n")
            
            # 第2部分：诊断计划
            f.write("-" * 80 + "\n")
            f.write("第2部分：Main Agent生成的诊断计划\n")
            f.write("-" * 80 + "\n")
            
            diagnosis_plan = plan.get("diagnosis_plan", {})
            
            # 序列分类计划
            seq_plan = diagnosis_plan.get("sequence_classification", {})
            f.write(f"[序列分类]\n")
            f.write(f"  描述: {seq_plan.get('description', 'N/A')}\n")
            f.write(f"  输入序列: {', '.join(seq_plan.get('inputs', []))}\n\n")
            
            # 时相检测计划
            phase_plan = diagnosis_plan.get("phase_detection", {})
            f.write(f"[时相检测]\n")
            f.write(f"  描述: {phase_plan.get('description', 'N/A')}\n")
            sequences = phase_plan.get("sequences", {})
            for seq_name, seq_info in sequences.items():
                if isinstance(seq_info, dict):
                    need_ed = seq_info.get("need_ed", False)
                    need_es = seq_info.get("need_es", False)
                    f.write(f"  {seq_name}: 需要ED={need_ed}, 需要ES={need_es}\n")
            f.write("\n")
            
            # 测量计划
            meas_plan = diagnosis_plan.get("measurements", {})
            f.write(f"[测量计划]\n")
            f.write(f"  描述: {meas_plan.get('description', 'N/A')}\n")
            f.write(f"  需要测量的指标:\n")
            
            meas_metrics = meas_plan.get("metrics", [])
            for idx, metric in enumerate(meas_metrics, 1):
                if isinstance(metric, dict):
                    name = metric.get("name", "N/A")
                    tool = metric.get("tool", "N/A")
                    reason = metric.get("reason", "N/A")
                    f.write(f"    {idx}. {name}\n")
                    f.write(f"       工具: {tool}\n")
                    f.write(f"       原因: {reason}\n")
                elif isinstance(metric, str):
                    f.write(f"    {idx}. {metric}\n")
            f.write("\n")
            
            # 第3部分：序列分类结果
            f.write("-" * 80 + "\n")
            f.write("第3部分：序列分类结果\n")
            f.write("-" * 80 + "\n")
            
            seq_results = metrics.get("sequence_classification", [])
            for result in seq_results:
                f.write(f"序列: {result['sequence']}\n")
                f.write(f"  预测类别: {result['pred_label']}\n")
                f.write(f"  置信度: {result['confidence']:.4f}\n")
                probs = result.get("probabilities", {})
                f.write(f"  概率分布: ")
                f.write(", ".join([f"{k}={v:.4f}" for k, v in probs.items()]))
                f.write("\n\n")
            
            # 第4部分：指标测量过程
            f.write("-" * 80 + "\n")
            f.write("第4部分：指标测量过程与结果\n")
            f.write("-" * 80 + "\n")
            
            requested = metrics.get("requested_metrics", [])
            for idx, metric in enumerate(requested, 1):
                name = metric.get("name", "N/A")
                value = metric.get("value")
                unit = metric.get("unit", "")
                status = metric.get("status", "unknown")
                
                # 获取使用的工具
                spec = METRIC_DEFINITIONS.get(name, {})
                tool = spec.get("log_tool", "未知工具")
                
                f.write(f"{idx}. 指标: {name}\n")
                f.write(f"   调用工具: {tool}\n")
                
                if status == "ok":
                    f.write(f"   测量结果: {value} {unit}\n")
                    f.write(f"   状态: ✓ 成功\n")
                else:
                    f.write(f"   状态: ✗ {status}\n")
                f.write("\n")
            
            # 第5部分：关键帧信息
            f.write("-" * 80 + "\n")
            f.write("第5部分：ED/ES关键帧信息\n")
            f.write("-" * 80 + "\n")
            
            raw = metrics.get("raw_measurements", {})
            
            # SAX关键帧
            sax_metrics = raw.get("sax_metrics", {})
            if sax_metrics:
                phase_info = sax_metrics.get("phase_assignments", {})
                f.write(f"[SAX序列]\n")
                f.write(f"  ED时刻: Trigger {phase_info.get('ED_trigger', 'N/A')} ms\n")
                f.write(f"  ES时刻: Trigger {phase_info.get('ES_trigger', 'N/A')} ms\n")
                f.write(f"  关键帧保存位置: output/{patient_info.get('patient_id')}/key_frames/SAX/\n")
                f.write(f"    - ED_tt{int(phase_info.get('ED_trigger', 0)):04d}.nii.gz\n")
                f.write(f"    - ES_tt{int(phase_info.get('ES_trigger', 0)):04d}.nii.gz\n")
                f.write("\n")
            
            # 4CH关键帧
            ch_metrics = raw.get("four_ch_metrics", {})
            if ch_metrics:
                ed_trigger = ch_metrics.get("ED_trigger", "N/A")
                f.write(f"[4CH序列]\n")
                f.write(f"  ED时刻: Trigger {ed_trigger} ms\n")
                f.write(f"  关键帧保存位置: output/{patient_info.get('patient_id')}/key_frames/4CH/\n")
                f.write(f"    - ED_tt{int(ed_trigger) if isinstance(ed_trigger, (int, float)) else 0:04d}.nii.gz\n")
                f.write("\n")
            
            # 第6部分：工作流程总结
            f.write("-" * 80 + "\n")
            f.write("第6部分：工作流程总结\n")
            f.write("-" * 80 + "\n")
            f.write("完整诊断流程:\n\n")
            
            f.write("步骤1: 序列分类\n")
            f.write("  - 工具: 序列分类模型 (ViT + DistilBERT)\n")
            f.write("  - 输入: DICOM首帧预览图(PNG)\n")
            f.write("  - 输出: 序列类型判定(4CH/SAX/LGE)\n")
            f.write("  - 结果: 已保存至 previews/ 目录\n\n")
            
            f.write("步骤2: DICOM转换\n")
            f.write("  - 工具: SimpleITK DICOM读取器\n")
            f.write("  - 处理: 按触发时间分组，每个时间点转为3D NIfTI\n")
            f.write("  - 输出: 多个时间帧的NIfTI文件\n")
            f.write("  - 结果: 已保存至 temp/ 目录\n\n")
            
            f.write("步骤3: 心脏结构分割\n")
            f.write("  - 工具: nnU-Net分割模型\n")
            f.write("  - SAX模型: Dataset301_ACDC (分割LV/RV/MYO)\n")
            f.write("  - 4CH模型: Dataset303_MMWHS (分割LA/RA/LV/RV/MYO)\n")
            f.write("  - 输入: 每个时间帧的NIfTI\n")
            f.write("  - 输出: 分割掩膜(NIfTI格式)\n")
            f.write("  - 结果: 已保存至 segmentations/ 目录\n\n")
            
            f.write("步骤4: 时相判定\n")
            f.write("  - 工具: 体积测量工具 + 时相选择算法\n")
            f.write("  - 方法: 测量每帧LV体积和内径\n")
            f.write("  - 判定: ED=体积最大帧, ES=体积最小帧\n")
            f.write("  - 结果: ED/ES帧已保存至 key_frames/ 目录\n\n")
            
            f.write("步骤5: 指标测量\n")
            f.write("  - 根据诊断计划测量所需指标\n")
            f.write(f"  - 共测量 {len(requested)} 个指标\n")
            f.write("  - 调用的测量工具:\n")
            
            tools_used = set()
            for metric in requested:
                name = metric.get("name")
                if name in METRIC_DEFINITIONS:
                    tool = METRIC_DEFINITIONS[name].get("log_tool", "")
                    if tool:
                        tools_used.add(tool)
            
            for tool in sorted(tools_used):
                f.write(f"    * {tool}\n")
            f.write("\n")
            
            f.write("步骤6: 诊断报告生成\n")
            f.write("  - 工具: Main Agent (DeepSeek LLM)\n")
            f.write("  - 输入: 患者信息 + 测量结果\n")
            f.write("  - 输出: 结构化诊断报告\n")
            f.write("  - 结果: 已保存至 report.json\n\n")
            
            # 输出目录结构
            f.write("-" * 80 + "\n")
            f.write("输出文件目录结构\n")
            f.write("-" * 80 + "\n")
            f.write(f"output/{patient_info.get('patient_id')}/\n")
            f.write("├── metrics.json              # 量化测量结果\n")
            f.write("├── report.json               # 诊断报告\n")
            f.write("├── workflow.log              # 本工作流程日志\n")
            f.write("├── previews/                 # 序列预览图\n")
            f.write("│   ├── 4CH.png\n")
            f.write("│   ├── SAX.png\n")
            f.write("│   └── LGE.png\n")
            f.write("├── segmentations/            # 所有时间帧的分割结果\n")
            f.write("│   ├── SAX/\n")
            f.write("│   │   ├── sax_tt0000.nii.gz, sax_tt0034.nii.gz, ...\n")
            f.write("│   │   └── (每个触发时间一个文件)\n")
            f.write("│   └── 4CH/\n")
            f.write("│       ├── ch_tt0000.nii.gz, ch_tt0035.nii.gz, ...\n")
            f.write("│       └── (每个触发时间一个文件)\n")
            f.write("├── key_frames/               # ED/ES关键帧\n")
            f.write("│   ├── SAX/\n")
            f.write("│   │   ├── ED_tt....nii.gz  # ED时刻所有切片\n")
            f.write("│   │   ├── ES_tt....nii.gz  # ES时刻所有切片\n")
            f.write("│   │   └── README.txt\n")
            f.write("│   └── 4CH/\n")
            f.write("│       ├── ED_tt....nii.gz\n")
            f.write("│       └── README.txt\n")
            f.write("└── measurements/             # 测量可视化\n")
            f.write("    └── SAX_ED/\n")
            f.write("        └── sax_tt....nii_slice##.png  # 内径/壁厚测量示意图\n")
            f.write("\n")
            
            # 关键指标汇总
            f.write("-" * 80 + "\n")
            f.write("关键指标汇总\n")
            f.write("-" * 80 + "\n")
            
            for metric in requested:
                name = metric.get("name")
                value = metric.get("value")
                unit = metric.get("unit", "")
                status = metric.get("status")
                
                if status == "ok":
                    f.write(f"{name}: {value} {unit}\n")
                else:
                    f.write(f"{name}: {status}\n")
            
            f.write("\n")
            f.write("=" * 80 + "\n")
            f.write("日志结束\n")
            f.write("=" * 80 + "\n")
        
        self.logger.info("工作流程日志已生成: %s", log_file)
    
    def _verify_nifti(self, nifti_path: Path) -> bool:
        """验证NIfTI文件是否有效"""
        try:
            import nibabel as nib
            img = nib.load(str(nifti_path))
            data = img.get_fdata()
            # 检查数据是否有效
            if data.size == 0:
                return False
            # 检查shape是否合理
            if any(s <= 0 for s in data.shape):
                return False
            return True
        except Exception as e:
            self.logger.warning("NIfTI验证失败 %s: %s", nifti_path, e)
            return False


    def _extract_requested_metrics(self, plan: Dict) -> List[str]:
        metrics: List[str] = []
        try:
            plan_metrics = (
                plan.get("diagnosis_plan", {})
                .get("measurements", {})
                .get("metrics", [])
            )
            for item in plan_metrics:
                if isinstance(item, str):
                    name = item.strip()
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("metric")
                else:
                    name = None
                if name:
                    metrics.append(name)
        except Exception as exc:  # pragma: no cover
            self.logger.warning("解析计划指标失败: %s", exc)
        if not metrics:
            metrics = [m for group in AVAILABLE_METRICS.values() for m in group]
        # 去重同时保持顺序
        seen = set()
        ordered = []
        for name in metrics:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

class MeasurementOrchestrator:
    def __init__(self, pipeline: DiagnosisPipeline, patient: PatientCase) -> None:
        self.pipeline = pipeline
        self.patient = patient
        self._sax_metrics: Optional[Dict] = None
        self._four_ch_metrics: Optional[Dict] = None
        # 工具节点跟踪，用于发射工作流事件
        self._tool_started: set[str] = set()
        self._tool_remaining: Dict[str, int] = {}
        for metric_name, tool_name in self.pipeline.metric_tool_map.items():
            if tool_name:
                self._tool_remaining[tool_name] = self._tool_remaining.get(tool_name, 0) + 1

    def measure_all(self, metric_names: List[str]) -> List[Dict]:
        results: List[Dict] = []
        seen: set[str] = set()
        for name in metric_names:
            if name in seen:
                continue
            seen.add(name)
            results.append(self._measure_single(name))
        return results

    def raw_outputs(self) -> Dict[str, Dict]:
        outputs: Dict[str, Dict] = {}
        if self._sax_metrics is not None:
            outputs["sax_metrics"] = self._sax_metrics
        if self._four_ch_metrics is not None:
            outputs["four_ch_metrics"] = self._four_ch_metrics
        return outputs

    def _measure_single(self, name: str) -> Dict:
        spec = METRIC_DEFINITIONS.get(name)
        if spec is None:
            return {"name": name, "value": None, "unit": None, "status": "unsupported"}

        tool_name = self.pipeline.metric_tool_map.get(name)
        workflow_tag = None
        if tool_name and tool_name in self.pipeline.tool_node_map:
            workflow_tag = self.pipeline.tool_node_map[tool_name]
        elif self.pipeline.measurement_node_id:
            workflow_tag = self.pipeline.measurement_node_id

        # 工具开始事件（仅一次）
        if tool_name and tool_name not in self._tool_started and workflow_tag:
            self._tool_started.add(tool_name)
            pending_metrics = [
                m_name
                for m_name, t_name in self.pipeline.metric_tool_map.items()
                if t_name == tool_name
            ]
            self.pipeline.emit_event(
                "workflow_node_start",
                {"node_id": workflow_tag, "title": tool_name},
                workflow_tag=workflow_tag
            )
            # 日志：工具启动
            self.pipeline.emit_event(
                "log_detail",
                {
                    "message": f"启动测量工具: {tool_name}",
                    "logs": [f"待测指标: {', '.join(pending_metrics)}"] if pending_metrics else None,
                },
                workflow_tag=workflow_tag
            )

        if workflow_tag:
            start_msg = f"开始测量 {name}" + (f"（工具: {tool_name}）" if tool_name else "")
            self.pipeline.emit_event(
                "log_detail",
                {"message": start_msg},
                workflow_tag=workflow_tag
            )

        log_tool = spec.get("log_tool", "相关测量工具")
        self.pipeline.logger.info("开始测量指标 %s，调用：%s", name, log_tool)

        source_data = self._get_source_data(spec["source"])
        if not source_data:
            if workflow_tag:
                self.pipeline.emit_event(
                    "log_detail",
                    {"message": f"{name}: 数据源缺失"},
                    workflow_tag=workflow_tag
                )
            return {"name": name, "value": None, "unit": spec["unit"], "status": "missing_source"}

        value = self._nested_get(source_data, spec["path"])
        status = "ok" if value is not None else "missing_value"
        if status == "ok":
            unit = spec.get("unit") or ""
            self.pipeline.logger.info(
                "完成测量指标 %s，结果：%s %s", name, value, unit
            )
            if workflow_tag:
                self.pipeline.emit_event(
                    "log_detail",
                    {"message": f"{name}: {value} {unit}".strip()},
                    workflow_tag=workflow_tag
                )
        else:
            self.pipeline.logger.warning("指标 %s 测量失败，状态：%s", name, status)
            if workflow_tag:
                self.pipeline.emit_event(
                    "log_detail",
                    {"message": f"{name} 测量失败，状态: {status}"},
                    workflow_tag=workflow_tag
                )

        # 如果该工具所有指标已完成，则发射结束事件
        if tool_name and tool_name in self._tool_remaining and workflow_tag:
            self._tool_remaining[tool_name] -= 1
            if self._tool_remaining[tool_name] <= 0:
                self.pipeline.emit_event(
                    "log_detail",
                    {"message": f"工具完成: {tool_name}"},
                    workflow_tag=workflow_tag
                )
                self.pipeline.emit_event(
                    "workflow_node_end",
                    {"node_id": workflow_tag, "status": "success"},
                    workflow_tag=workflow_tag
                )
                del self._tool_remaining[tool_name]

        return {"name": name, "value": value, "unit": spec["unit"], "status": status}

    def _get_source_data(self, source: str) -> Optional[Dict]:
        if source == "sax":
            if self._sax_metrics is None:
                self.pipeline.logger.info(
                    "触发SAX指标测量流程：将调用序列分类→时相判定→SAX分割→形态测量等工具链。"
                )
                self._sax_metrics = self.pipeline._process_sax(self.patient)
            return self._sax_metrics
        if source == "four_ch":
            if self._four_ch_metrics is None:
                self.pipeline.logger.info(
                    "触发4CH指标测量流程：将调用序列分类→时相判定→4CH分割→心房体积测量等工具链。"
                )
                self._four_ch_metrics = self.pipeline._process_4ch(self.patient)
            return self._four_ch_metrics
        return None

    @staticmethod
    def _nested_get(container: Dict, path: tuple[str, ...]) -> Optional[float]:
        current = container
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current
