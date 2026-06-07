from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import torch

# 必须在导入 nnU-Net 之前设置环境变量
from config.settings import NNUNET_ENV, CUDA_DEVICE_ID

# 设置 nnU-Net 环境变量（在导入之前）
for key, value in NNUNET_ENV.items():
    os.environ.setdefault(key, value)

from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor


class SegmentationRunner:
    """
    nnU-Net 推理封装：支持任意模型目录
    支持模型缓存，避免重复加载
    """

    def __init__(self) -> None:
        # 环境变量已在模块导入时设置，这里确保设置（防止被覆盖）
        for key, value in NNUNET_ENV.items():
            os.environ.setdefault(key, value)
        # 缓存已加载的预测器：{model_dir: predictor}
        self._predictor_cache: dict[str, nnUNetPredictor] = {}

    def run(
        self,
        image_path: Path,
        model_dir: Path,
        output_dir: Path,
        folds: tuple[str, ...] = ("0",),
        checkpoint: str = "checkpoint_final.pth",
    ) -> Path:
        """
        运行nnUNet分割
        
        参数:
            image_path: 输入NIfTI文件路径
            model_dir: nnUNet模型目录
            output_dir: 输出目录
            folds: 使用的fold
            checkpoint: checkpoint文件名
            
        返回:
            分割结果文件路径
        """
        if not image_path.is_file():
            raise FileNotFoundError(f"输入文件不存在: {image_path}")
        if not model_dir.is_dir():
            raise FileNotFoundError(f"模型目录不存在: {model_dir}")

        output_dir.mkdir(parents=True, exist_ok=True)

        # 初始化device变量
        if torch.cuda.is_available():
            try:
                device = torch.device("cuda:0")
                torch.cuda.set_device(0)
                gpu_name = torch.cuda.get_device_name(0)
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
                print(f"[SegmentationRunner] 使用GPU 0: {gpu_name} ({gpu_memory:.1f}GB)")
            except Exception as e:
                print(f"[SegmentationRunner] 警告: GPU 0 不可用 ({e})，使用CPU")
                device = torch.device("cpu")
        else:
            device = torch.device("cpu")
            print("[SegmentationRunner] CUDA不可用，使用CPU")

        # 使用缓存的预测器或创建新的
        model_key = f"{model_dir}_{folds}_{checkpoint}"

        if model_key not in self._predictor_cache:
            # 首次使用该模型，需要加载
            
            predictor = nnUNetPredictor(
                tile_step_size=0.5,
                use_gaussian=True,
                use_mirroring=True,
                perform_everything_on_device=device.type == "cuda",
                device=device,
                verbose=False,
                verbose_preprocessing=False,
                allow_tqdm=False,
            )
            predictor.initialize_from_trained_model_folder(
                str(model_dir),
                use_folds=folds,
                checkpoint_name=checkpoint,
            )
            self._predictor_cache[model_key] = predictor
        else:
            # 复用已加载的预测器
            predictor = self._predictor_cache[model_key]

        # 准备输入文件（nnUNet要求_0000后缀）
        case_id = image_path.stem.replace(".nii", "")
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir = Path(tmp_dir)
            tmp_input = tmp_dir / f"{case_id}_0000.nii.gz"
            shutil.copy2(image_path, tmp_input)

            # 运行预测
            # 注意：减少进程数以避免显存问题，并确保后台worker正确清理
            predictor.predict_from_files(
                str(tmp_dir),
                str(output_dir),
                save_probabilities=False,
                overwrite=True,
                num_processes_preprocessing=1,  # 减少预处理进程数，避免显存累积
                num_processes_segmentation_export=1,  # 减少导出进程数，避免显存累积
            )
            
            # 显式清理GPU缓存（如果使用GPU）
            # 等待所有CUDA操作和后台worker完成
            if torch.cuda.is_available() and device.type == "cuda":
                try:
                    with torch.cuda.device(0):
                        torch.cuda.synchronize()
                        torch.cuda.empty_cache()
                except Exception:
                    pass
                    
                    # 额外等待，确保后台worker完成（nnU-Net使用后台worker处理导出）
                    import time
                    time.sleep(1.0)  # 等待1秒，确保后台worker完成
                    
                    # 再次清理
                    torch.cuda.empty_cache()

        # 查找预测结果
        prediction = output_dir / f"{case_id}.nii.gz"
        if prediction.exists() and prediction.stat().st_size > 0:
            # 验证文件可读
            try:
                import nibabel as nib
                img = nib.load(str(prediction))
                _ = img.shape  # 触发加载验证
                return prediction
            except Exception as e:
                raise RuntimeError(f"分割结果文件损坏: {prediction}, 错误: {e}")

        # 回退：查找同名结果
        matches = list(output_dir.glob(f"{case_id}*.nii.gz"))
        matches = [m for m in matches if m.stat().st_size > 0]
        
        if not matches:
            raise RuntimeError(f"未找到有效的预测输出: {case_id}")
        
        # 返回第一个有效的结果
        for match in matches:
            try:
                import nibabel as nib
                img = nib.load(str(match))
                _ = img.shape
                return match
            except Exception:
                continue
        
        raise RuntimeError(f"所有预测输出文件都无效: {case_id}")
