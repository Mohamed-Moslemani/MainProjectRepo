"""Shared pytest configuration. Makes the gateway app + shared packages importable."""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent.parent
_gateway_root = Path(__file__).resolve().parent.parent

for p in (_project_root, _gateway_root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
