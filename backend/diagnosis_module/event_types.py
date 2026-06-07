
"""
事件类型定义和 Pydantic 模型
用于 SSE 流式输出
"""

from typing import Any, Dict, Optional, List
from pydantic import BaseModel
from datetime import datetime
from enum import Enum
import json


class EventType(str, Enum):
    """事件类型枚举"""
    DIAGNOSTIC_PLAN = "diagnostic_plan"
    WORKFLOW_NODE_START = "workflow_node_start"
    WORKFLOW_NODE_END = "workflow_node_end"
    LOG_DETAIL = "log_detail"
    SEGMENTATION_COMPLETE = "segmentation_complete"
    PHASE_DETECTION = "phase_detection"
    MEASUREMENT_RESULT = "measurement_result"
    FILE_GENERATED = "file_generated"
    ERROR = "error"
    STREAM_END = "stream_end"


class StreamEvent(BaseModel):
    """SSE 事件基础模型"""
    type: EventType
    timestamp: str
    workflow_tag: Optional[str] = None
    content: Dict[str, Any]

    def to_sse_format(self) -> str:
        """转换为 SSE 格式字符串"""
        event_dict = self.model_dump()
        event_json = json.dumps(event_dict, ensure_ascii=False)
        return f"data: {event_json}\n\n"


class DiagnosticPlanEvent(BaseModel):
    """诊断计划事件"""
    plan: Dict[str, Any]
    workflow_graph: Dict[str, Any]


class WorkflowNodeStartEvent(BaseModel):
    """工作流节点开始事件"""
    node_id: str
    title: str
    description: Optional[str] = None


class WorkflowNodeEndEvent(BaseModel):
    """工作流节点结束事件"""
    node_id: str
    status: str  # "success" 或 "failed"


class LogDetailEvent(BaseModel):
    """日志详情事件"""
    node_id: str
    logs: List[str]


class SegmentationCompleteEvent(BaseModel):
    """分割完成事件"""
    sequence: str  # "SAX" 或 "4CH"
    timepoint: int
    filename: str
    file_url: str


class PhaseDetectionEvent(BaseModel):
    """时相检测事件"""
    sequence: str
    ED: Optional[Dict[str, Any]] = None
    ES: Optional[Dict[str, Any]] = None


class MeasurementResultEvent(BaseModel):
    """指标测量结果事件"""
    metric_name: str
    value: Optional[float]
    unit: str


class FileGeneratedEvent(BaseModel):
    """文件生成事件"""
    type: str  # "metrics", "report", "visualization" 等
    file_url: str
    display_name: str


class ErrorEvent(BaseModel):
    """错误事件"""
    node_id: Optional[str] = None
    message: str
    severity: str  # "warning" 或 "error"


class StreamEndEvent(BaseModel):
    """流结束事件"""
    status: str  # "success", "partial", "failed"
    total_time_seconds: Optional[float] = None


def create_event(
    event_type: EventType,
    content: Dict[str, Any],
    workflow_tag: Optional[str] = None
) -> StreamEvent:
    """
    创建一个 SSE 事件

    Args:
        event_type: 事件类型
        content: 事件内容
        workflow_tag: 工作流标记（可选）

    Returns:
        StreamEvent 对象
    """
    return StreamEvent(
        type=event_type,
        timestamp=datetime.utcnow().isoformat() + "Z",
        workflow_tag=workflow_tag,
        content=content
    )
