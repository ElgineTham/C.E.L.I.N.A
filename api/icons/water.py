import sys
from pathlib import Path

for parent in Path(__file__).resolve().parents:
    api = parent / "backend" / "API"
    if (api / "server.py").exists():
        sys.path.insert(0, str(api))
        break

from server import Handler as handler
