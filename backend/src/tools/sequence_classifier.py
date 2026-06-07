from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Union, Optional

import torch
from PIL import Image
from safetensors.torch import load_file
from transformers import AutoImageProcessor, AutoTokenizer

from config.settings import SEQUENCE_CLASSIFIER_DIR, BASE_DIR

# 导入现有模型定义
import sys

# 使用相对路径定位 models.py
MODELS_PY = BASE_DIR / "models.py"
if str(MODELS_PY.parent) not in sys.path:
    sys.path.append(str(MODELS_PY.parent))

from models import MedicalMultimodalClassifier  # type: ignore  # noqa: E402


class SequenceClassifier:
    def __init__(self, device: Optional[str] = None) -> None:
        self.model_dir = SEQUENCE_CLASSIFIER_DIR
        with open(self.model_dir / "config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.class_names: List[str] = cfg["class_names"]

        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.image_processor = AutoImageProcessor.from_pretrained(self.model_dir)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)

        self.model = MedicalMultimodalClassifier(num_classes=len(self.class_names))
        state_dict = load_file(str(self.model_dir / "model.safetensors"), device="cpu")
        self.model.load_state_dict(state_dict)
        self.model.to(self.device)
        self.model.eval()

    def predict(self, image_path: Path, question: str) -> Dict[str, Union[float, str]]:
        image = self.image_processor(Image.open(image_path).convert("RGB"), return_tensors="pt")
        text_inputs = self.tokenizer(
            question,
            padding=True,
            truncation=True,
            max_length=64,
            return_tensors="pt",
        )
        pixel_values = image["pixel_values"].to(self.device)
        input_ids = text_inputs["input_ids"].to(self.device)
        attention_mask = text_inputs["attention_mask"].to(self.device)

        with torch.no_grad():
            outputs = self.model(pixel_values=pixel_values, input_ids=input_ids, attention_mask=attention_mask)
            logits = outputs["logits"]
            probs = torch.softmax(logits, dim=-1).cpu().numpy()[0]

        best_idx = int(probs.argmax())
        return {
            "pred_label": self.class_names[best_idx],
            "confidence": float(probs[best_idx]),
            "probabilities": {name: float(probs[i]) for i, name in enumerate(self.class_names)},
        }

