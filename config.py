"""Central configuration — all values come from environment variables with sane defaults."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ------------------------------------------------------------------
# Filesystem layout
# ------------------------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = DATA_DIR / "db.sqlite"
FILES_DIR = DATA_DIR / "files"

# ------------------------------------------------------------------
# Server
# ------------------------------------------------------------------
SERVER_NAME = "my-own-mcp-server"
