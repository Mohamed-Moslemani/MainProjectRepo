import sys
from pathlib import Path

_registry_root = Path(__file__).resolve().parent.parent
if str(_registry_root) not in sys.path:
    sys.path.insert(0, str(_registry_root))
