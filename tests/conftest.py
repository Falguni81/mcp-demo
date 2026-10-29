"""Point the server at this project before any test imports `server`."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["DEV_REPO_PATH"] = str(ROOT)
os.environ["DEV_LOG_DIR"] = str(ROOT / "logs")
