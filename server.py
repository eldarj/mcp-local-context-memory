"""
my-own-mcp-server — entry point.

Startup order:
  1. Initialise database + filesystem layout
  2. Create FastMCP instance
  3. Register built-in tools (ping)
  4. Register module tools (storage, knowledge)
  5. Auto-load dynamic tools from tools/
  6. Run (stdio — Claude Code spawns this process)
"""

import importlib
import sys
from pathlib import Path

import db
from config import SERVER_NAME
from mcp.server.fastmcp import FastMCP

# ── 1. Init ───────────────────────────────────────────────────────────────────
db.init()

# ── 2. FastMCP instance ───────────────────────────────────────────────────────
mcp = FastMCP(SERVER_NAME)

# ── 3. Built-in tools ─────────────────────────────────────────────────────────

@mcp.tool()
def ping() -> str:
    """Health check — confirms the server is reachable."""
    return "pong"

# ── 4. Module tools ───────────────────────────────────────────────────────────
from modules import knowledge, storage  # noqa: E402

storage.register(mcp)
knowledge.register(mcp)

# ── 5. Dynamic tool loading ───────────────────────────────────────────────────
_TOOLS_DIR = Path(__file__).parent / "tools"

# Ensure tools/ is importable as a flat namespace
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

for _tool_file in sorted(_TOOLS_DIR.glob("*.py")):
    if _tool_file.name.startswith("_"):
        continue
    _module_name = _tool_file.stem
    try:
        _module = importlib.import_module(_module_name)
        if hasattr(_module, "register"):
            _module.register(mcp)
            print(f"[tools] Loaded: {_tool_file.name}", file=sys.stderr)
        else:
            print(
                f"[tools] Skipped {_tool_file.name} — no register(mcp) function found.",
                file=sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[tools] Failed to load {_tool_file.name}: {exc}", file=sys.stderr)

# ── 6. Run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="stdio")
