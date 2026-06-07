from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
import torch
import torch.nn as nn
from scipy.ndimage import zoom

from .common import export_mask_pngs, strip_nii_suffix
from .config import get_default_paths


class DoubleConv(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, mid_channels: int | None = None):
        super().__init__()
        mid_channels = mid_channels or out_channels
        self.double_conv = nn.Sequential(
            nn.Conv2d(in_channels, mid_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(mid_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(mid_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.double_conv(x)


class Down(nn.Module):
    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.maxpool_conv = nn.Sequential(nn.MaxPool2d(2), DoubleConv(in_channels, out_channels))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.maxpool_conv(x)


class Up(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, bilinear: bool = True):
        super().__init__()
        if bilinear:
            self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
            self.conv = DoubleConv(in_channels, out_channels, in_channels // 2)
        else:
            self.up = nn.ConvTranspose2d(in_channels, in_channels // 2, kernel_size=2, stride=2)
            self.conv = DoubleConv(in_channels, out_channels)

    def forward(self, x1: torch.Tensor, x2: torch.Tensor) -> torch.Tensor:
        x1 = self.up(x1)
        diff_y = x2.size()[2] - x1.size()[2]
        diff_x = x2.size()[3] - x1.size()[3]
        x1 = nn.functional.pad(
            x1,
            [diff_x // 2, diff_x - diff_x // 2, diff_y // 2, diff_y - diff_y // 2],
        )
        x = torch.cat([x2, x1], dim=1)
        return self.conv(x)


class OutConv(nn.Module):
    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv(x)


class UNet(nn.Module):
    def __init__(self, n_channels: int, n_classes: int, bilinear: bool = True):
        super().__init__()
        factor = 2 if bilinear else 1
        self.inc = DoubleConv(n_channels, 64)
        self.down1 = Down(64, 128)
        self.down2 = Down(128, 256)
        self.down3 = Down(256, 512)
        self.down4 = Down(512, 1024 // factor)
        self.up1 = Up(1024, 512 // factor, bilinear)
        self.up2 = Up(512, 256 // factor, bilinear)
        self.up3 = Up(256, 128 // factor, bilinear)
        self.up4 = Up(128, 64, bilinear)
        self.outc = OutConv(64, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x1 = self.inc(x)
        x2 = self.down1(x1)
        x3 = self.down2(x2)
        x4 = self.down3(x3)
        x5 = self.down4(x4)
        x = self.up1(x5, x4)
        x = self.up2(x, x3)
        x = self.up3(x, x2)
        x = self.up4(x, x1)
        return self.outc(x)


class FourChSegmentationRunner:
    def __init__(
        self,
        model_path: str | Path | None = None,
        img_size: int = 256,
        n_classes: int = 5,
        gpu_id: int | None = None,
    ):
        default_paths = get_default_paths()
        self.model_path = Path(model_path) if model_path is not None else default_paths.four_ch_model_path
        self.img_size = img_size
        self.n_classes = n_classes

        if torch.cuda.is_available():
            device_id = gpu_id if gpu_id is not None else 0
            if device_id >= torch.cuda.device_count():
                raise ValueError(
                    f"GPU {device_id} unavailable; visible GPUs: 0-{torch.cuda.device_count() - 1}"
                )
            self.device = torch.device(f"cuda:{device_id}")
            torch.cuda.set_device(device_id)
        else:
            self.device = torch.device("cpu")

        if not self.model_path.is_file():
            raise FileNotFoundError(f"4CH model not found: {self.model_path}")

        self.model = UNet(n_channels=1, n_classes=self.n_classes).to(self.device)
        checkpoint = torch.load(self.model_path, map_location=self.device)
        state_dict = {}
        for key, value in checkpoint.items():
            state_dict[key[7:] if key.startswith("module.") else key] = value
        self.model.load_state_dict(state_dict)
        self.model.eval()

    @staticmethod
    def _normalize_image(data: np.ndarray) -> np.ndarray:
        min_value = float(np.min(data))
        max_value = float(np.max(data))
        if max_value - min_value > 0:
            return (data - min_value) / (max_value - min_value)
        return data

    @staticmethod
    def _resize_image(data: np.ndarray, target_size: tuple[int, int], is_mask: bool = False) -> np.ndarray:
        height, width = data.shape
        target_height, target_width = target_size
        if height == target_height and width == target_width:
            return data
        order = 0 if is_mask else 1
        return zoom(data, (target_height / height, target_width / width), order=order)

    def _predict_slice(self, image_slice: np.ndarray) -> np.ndarray:
        original_shape = image_slice.shape
        resized = self._resize_image(image_slice, (self.img_size, self.img_size), is_mask=False)
        normalized = self._normalize_image(resized)
        input_tensor = torch.from_numpy(normalized).float().unsqueeze(0).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self.model(input_tensor)
            prediction = torch.argmax(torch.softmax(logits, dim=1), dim=1).cpu().numpy()[0]

        return self._resize_image(prediction, original_shape, is_mask=True)

    def run(self, input_path: Path, output_dir: Path) -> Path:
        input_path = Path(input_path)
        output_dir = Path(output_dir)
        if not input_path.is_file():
            raise FileNotFoundError(f"Input NIfTI not found: {input_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        image = nib.load(str(input_path))
        image_data = image.get_fdata()
        prediction = np.zeros_like(image_data, dtype=np.uint8)

        if image_data.ndim == 2:
            prediction = self._predict_slice(image_data)
        elif image_data.ndim == 3:
            for index in range(image_data.shape[2]):
                prediction[:, :, index] = self._predict_slice(image_data[:, :, index])
        elif image_data.ndim == 4:
            for z_index in range(image_data.shape[2]):
                for t_index in range(image_data.shape[3]):
                    prediction[:, :, z_index, t_index] = self._predict_slice(image_data[:, :, z_index, t_index])
        else:
            raise ValueError(f"Unsupported input ndim: {image_data.ndim}")

        remapped = np.zeros_like(prediction, dtype=np.int16)
        remapped[prediction == 1] = 420
        remapped[prediction == 2] = 500
        remapped[prediction == 3] = 550
        remapped[prediction == 4] = 600

        if remapped.ndim == 2:
            remapped = remapped[:, :, np.newaxis]

        output_name = f"{strip_nii_suffix(input_path.name)}_seg.nii.gz"
        output_path = output_dir / output_name
        nib.save(nib.Nifti1Image(remapped.astype(np.int16), image.affine), str(output_path))
        export_mask_pngs(output_path)

        if torch.cuda.is_available() and self.device.type == "cuda":
            with torch.cuda.device(self.device.index if self.device.index is not None else 0):
                torch.cuda.synchronize()
                torch.cuda.empty_cache()

        return output_path
