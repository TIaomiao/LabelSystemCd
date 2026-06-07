from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
import time
from pathlib import Path

import nibabel as nib
import torch

from .common import export_mask_pngs, strip_nii_suffix
from .config import apply_nnunet_env

apply_nnunet_env()

from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor


class NnUNetSegmentationRunner:
    def __init__(self) -> None:
        apply_nnunet_env()
        self._predictor_cache: dict[str, nnUNetPredictor] = {}

    def _build_predictor(
        self,
        model_dir: Path,
        folds: tuple[str, ...],
        checkpoint: str,
        gpu_id: int | None,
    ) -> nnUNetPredictor:
        if torch.cuda.is_available():
            device_id = gpu_id if gpu_id is not None else 0
            if device_id >= torch.cuda.device_count():
                raise ValueError(
                    f"GPU {device_id} unavailable; visible GPUs: 0-{torch.cuda.device_count() - 1}"
                )
            torch.cuda.set_device(device_id)
            device = torch.device(f"cuda:{device_id}")
        else:
            device = torch.device("cpu")

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
        return predictor

    def run(
        self,
        image_path: Path,
        model_dir: Path,
        output_dir: Path,
        folds: tuple[str, ...] = ("0",),
        checkpoint: str = "checkpoint_final.pth",
        gpu_id: int | None = None,
    ) -> Path:
        image_path = Path(image_path)
        model_dir = Path(model_dir)
        output_dir = Path(output_dir)

        if not image_path.is_file():
            raise FileNotFoundError(f"Input NIfTI not found: {image_path}")
        if not model_dir.is_dir():
            raise FileNotFoundError(f"Model directory not found: {model_dir}")

        output_dir.mkdir(parents=True, exist_ok=True)
        cache_key = f"{model_dir}|{folds}|{checkpoint}|{gpu_id}"
        predictor = self._predictor_cache.get(cache_key)
        if predictor is None:
            predictor = self._build_predictor(model_dir, folds, checkpoint, gpu_id)
            self._predictor_cache[cache_key] = predictor

        case_id = strip_nii_suffix(image_path.name)
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            temp_input = temp_dir / f"{case_id}_0000.nii.gz"
            shutil.copy2(image_path, temp_input)

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                predictor.predict_from_files(
                    str(temp_dir),
                    str(output_dir),
                    save_probabilities=False,
                    overwrite=True,
                    num_processes_preprocessing=1,
                    num_processes_segmentation_export=1,
                )

        prediction = output_dir / f"{case_id}.nii.gz"
        if not prediction.exists():
            matches = sorted(output_dir.glob(f"{case_id}*.nii.gz"))
            if not matches:
                raise RuntimeError(f"No nnU-Net prediction was written for {case_id}")
            prediction = matches[0]

        _ = nib.load(str(prediction)).shape
        export_mask_pngs(prediction)

        if torch.cuda.is_available() and predictor.device.type == "cuda":
            device_index = predictor.device.index if predictor.device.index is not None else 0
            with torch.cuda.device(device_index):
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                time.sleep(1.0)
                torch.cuda.empty_cache()

        return prediction

    def run_batch(
        self,
        items: list[tuple[Path, Path]],
        model_dir: Path,
        folds: tuple[str, ...] = ("0",),
        checkpoint: str = "checkpoint_final.pth",
        gpu_id: int | None = None,
    ) -> list[Path]:
        if not items:
            return []

        model_dir = Path(model_dir)
        if not model_dir.is_dir():
            raise FileNotFoundError(f"Model directory not found: {model_dir}")

        normalized_items: list[tuple[Path, Path]] = []
        for image_path, output_dir in items:
            image_path = Path(image_path)
            output_dir = Path(output_dir)
            if not image_path.is_file():
                raise FileNotFoundError(f"Input NIfTI not found: {image_path}")
            output_dir.mkdir(parents=True, exist_ok=True)
            normalized_items.append((image_path, output_dir))

        cache_key = f"{model_dir}|{folds}|{checkpoint}|{gpu_id}"
        predictor = self._predictor_cache.get(cache_key)
        if predictor is None:
            predictor = self._build_predictor(model_dir, folds, checkpoint, gpu_id)
            self._predictor_cache[cache_key] = predictor

        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            temp_input = temp_dir / "inputs"
            temp_output = temp_dir / "outputs"
            temp_input.mkdir(parents=True, exist_ok=True)
            temp_output.mkdir(parents=True, exist_ok=True)

            temp_case_ids: list[str] = []
            seen_case_ids: dict[str, int] = {}
            for index, (image_path, _output_dir) in enumerate(normalized_items):
                base_case_id = strip_nii_suffix(image_path.name)
                seen_count = seen_case_ids.get(base_case_id, 0)
                seen_case_ids[base_case_id] = seen_count + 1
                case_id = base_case_id if seen_count == 0 else f"{base_case_id}_{index:03d}"
                temp_case_ids.append(case_id)
                shutil.copy2(image_path, temp_input / f"{case_id}_0000.nii.gz")

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                predictor.predict_from_files(
                    str(temp_input),
                    str(temp_output),
                    save_probabilities=False,
                    overwrite=True,
                    num_processes_preprocessing=1,
                    num_processes_segmentation_export=1,
                )

            predictions: list[Path] = []
            for case_id, (image_path, output_dir) in zip(temp_case_ids, normalized_items):
                temp_prediction = temp_output / f"{case_id}.nii.gz"
                if not temp_prediction.exists():
                    matches = sorted(temp_output.glob(f"{case_id}*.nii.gz"))
                    if not matches:
                        raise RuntimeError(f"No nnU-Net prediction was written for {case_id}")
                    temp_prediction = matches[0]

                output_path = output_dir / f"{strip_nii_suffix(image_path.name)}.nii.gz"
                shutil.copy2(temp_prediction, output_path)
                _ = nib.load(str(output_path)).shape
                export_mask_pngs(output_path)
                predictions.append(output_path)

        if torch.cuda.is_available() and predictor.device.type == "cuda":
            device_index = predictor.device.index if predictor.device.index is not None else 0
            with torch.cuda.device(device_index):
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                time.sleep(1.0)
                torch.cuda.empty_cache()

        return predictions
