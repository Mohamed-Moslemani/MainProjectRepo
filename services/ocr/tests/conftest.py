"""Pytest path setup so service code + cross-service `shared/` imports work.

The OCR app package lives under `services/ocr/`, while `shared/` (the
cross-service helpers used by every FastAPI app — request ID middleware,
telemetry, model_info) lives at the repo root. Tests run with the
working directory set to `services/ocr/` in CI; without this both
`from app.main import app` and `from shared.request_id import …` fail
with ModuleNotFoundError.

In production both paths resolve because the Dockerfile copies `shared/`
into `/app/shared/` so it sits next to the service's own `app/`.
"""

import sys
from pathlib import Path

_ocr_root = Path(__file__).resolve().parent.parent
_repo_root = _ocr_root.parent.parent

for path in (_ocr_root, _repo_root):
    p = str(path)
    if p not in sys.path:
        sys.path.insert(0, p)
