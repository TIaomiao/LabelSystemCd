from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cmr_segmentation_bundle import get_default_paths


def main() -> None:
    paths = get_default_paths()
    print("Bundle root:", paths.bundle_root)
    print("SAX/LGE model dir exists:", paths.sax_lge_model_dir.exists())
    print("4CH model exists:", paths.four_ch_model_path.exists())


if __name__ == "__main__":
    main()
