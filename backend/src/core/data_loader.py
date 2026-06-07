from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from config.settings import DATA_DIR


@dataclass
class PatientCase:
    patient_id: str
    root_dir: Path
    patient_info: Dict

    @property
    def sequences(self) -> Dict[str, Path]:
        return {
            "4CH": self.root_dir / "4CH",
            "SAX": self.root_dir / "SAX",
            "LGE": next((p for p in self.root_dir.glob("LGE*") if p.is_dir()), None),
        }


def load_patient_case(patient_id: str) -> PatientCase:
    root_dir = DATA_DIR / patient_id
    if not root_dir.is_dir():
        raise FileNotFoundError(f"患者目录不存在: {root_dir}")
    info_path = root_dir / "patient_info.json"
    if not info_path.is_file():
        raise FileNotFoundError(f"缺少patient_info.json: {info_path}")
    with info_path.open("r", encoding="utf-8") as f:
        info = json.load(f)
    return PatientCase(patient_id=patient_id, root_dir=root_dir, patient_info=info)

