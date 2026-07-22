from pathlib import Path

HOME = Path.home()
BASE = HOME / "AURORA-GUI"
CASES = BASE / "cases"
UPLOADS = BASE / "uploads"
GO_BIN = HOME / "go" / "bin"

CASES.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)
