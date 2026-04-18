"""Shared pytest configuration. Makes the OCR service app package importable."""

import sys
from pathlib import Path

_ocr_root = Path(__file__).resolve().parent.parent

if str(_ocr_root) not in sys.path:
    sys.path.insert(0, str(_ocr_root))
