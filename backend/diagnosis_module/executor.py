
import sys
import logging
import traceback
from pathlib import Path
from typing import Dict, Generator, Optional, Callable, Union
import json
from flask import current_app

# 确保能导入 src 中的模块
# We assume 'src' and 'utils_cardiac' are in 'backend' or accessible.
# In LabelSystem, backend structure:
# backend/
#   app.py
#   diagnosis_module/ (executor.py here)
#   src/ (copied from CardiacLabUID)
#   utils_cardiac/ (copied)

# Add paths to sys.path
def setup_paths():
    base_dir = Path(__file__).resolve().parent.parent # backend/
    src_dir = base_dir / "src"
    utils_dir = base_dir / "utils_cardiac"
    
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    if str(utils_dir) not in sys.path:
        sys.path.insert(0, str(utils_dir))

setup_paths()

from .event_types import StreamEvent, EventType, create_event

logger = logging.getLogger(__name__)


class DiagnosisExecutor:
    """
    统一的诊断执行入口，支持 CLI 和 API 两种模式

    - CLI 模式（use_streaming=False）：返回完整结果字典，日志输出到 stdout
    - API 模式（use_streaming=True）：返回事件生成器，每个步骤 yield SSE 事件
    """

    def __init__(
        self,
        patient_id: str,
        prompt: Optional[str] = None,
        use_streaming: bool = False,
        event_handler: Optional[Callable[[StreamEvent], None]] = None
    ):
        """
        初始化诊断执行器

        Args:
            patient_id: 患者 ID
            prompt: 可选的诊断提示
            use_streaming: 是否使用流式模式
            event_handler: 事件处理函数（用于 API 模式）
        """
        self.patient_id = patient_id
        self.prompt = prompt
        self.use_streaming = use_streaming
        self.event_handler = event_handler or self._default_event_handler

    def run_diagnosis(self) -> Union[Dict, Generator[str, None, None]]:
        """
        执行诊断

        Returns:
            - use_streaming=False: 完整的诊断结果字典
            - use_streaming=True: SSE 事件生成器
        """
        if self.use_streaming:
            return self._run_with_streaming()
        else:
            return self._run_without_streaming()

    def _run_without_streaming(self) -> Dict:
        """
        CLI 模式：直接调用诊断管道，返回完整结果
        所有日志照常输出到 stdout/stderr
        """
        # 动态导入，确保路径正确
        setup_paths()

        from pipelines.diagnosis_pipeline import DiagnosisPipeline

        pipeline = DiagnosisPipeline()
        result = pipeline.run(self.patient_id, custom_prompt=self.prompt)
        return result

    def _run_with_streaming(self) -> Generator[str, None, None]:
        """
        API 模式：启用事件流，每个关键步骤 yield SSE 格式的事件
        """
        # 动态导入，确保路径正确
        setup_paths()

        from pipelines.diagnosis_pipeline import DiagnosisPipeline

        # Queue to hold events yielded by the event handler callback
        import queue
        event_queue = queue.Queue()
        
        def queue_event_handler(event: StreamEvent):
            event_queue.put(event)

        # 创建诊断管道，绑定事件处理器
        pipeline = DiagnosisPipeline(event_emitter=queue_event_handler)

        # 由于 DiagnosisPipeline.run 是同步阻塞的，我们需要在一个线程中运行它，
        # 然后在主线程（生成器）中消费队列。
        # 或者，如果 Pipeline 本身没有 async/await，我们可以直接运行，但这样无法流式输出？
        # Wait, the original FastAPI implementation didn't use threads here explicitly?
        # Let's check the original implementation.
        # Original:
        # pipeline = DiagnosisPipeline(event_emitter=self.event_handler)
        # result = pipeline.run(...)
        # self.emit_event(END)
        
        # If pipeline.run calls event_handler synchronously, then we can't yield from within run() easily 
        # unless run() is a generator itself.
        # But DiagnosisPipeline.run() seems to be a regular function that calls event_emitter.
        # To make this a generator that yields events as they happen, we need to decouple execution from yielding.
        
        # Simpler approach for Flask/Python generator:
        # We can use a thread to run the pipeline, and the generator yields from the queue.
        
        import threading
        
        def worker():
            try:
                pipeline.run(self.patient_id, custom_prompt=self.prompt)
                # 诊断完成，发送流结束事件
                queue_event_handler(create_event(
                    EventType.STREAM_END,
                    {"status": "success"}
                ))
            except Exception as e:
                logger.error(f"Pipeline error: {e}")
                traceback.print_exc()
                queue_event_handler(create_event(
                    EventType.ERROR,
                    {"message": str(e), "traceback": traceback.format_exc()}
                ))
            finally:
                # Signal end of queue
                event_queue.put(None)

        t = threading.Thread(target=worker)
        t.start()
        
        # Generator loop
        while True:
            event = event_queue.get()
            if event is None:
                break
            
            # Format as SSE
            yield f"data: {event.json(ensure_ascii=False)}\n\n"

    def _default_event_handler(self, event: StreamEvent):
        """默认事件处理器：打印日志"""
        if event.type == EventType.LOG_DETAIL:
            print(f"[LOG] {event.content.get('message', '')}")
        elif event.type == EventType.ERROR:
            print(f"[ERROR] {event.content.get('message', '')}")
        else:
            print(f"[EVENT] {event.type}: {event.content}")

    def emit_event(self, event_type: EventType, content: Dict):
        """手动触发事件"""
        event = create_event(event_type, content)
        self.event_handler(event)
