"""Shared pytest configuration for the face service."""

import sys
from pathlib import Path

_face_root = Path(__file__).resolve().parent.parent

if str(_face_root) not in sys.path:
    sys.path.insert(0, str(_face_root))
