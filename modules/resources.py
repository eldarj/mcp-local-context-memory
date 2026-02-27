"""
MCP Resources — exposes stored notes as readable MCP Resources.

URI scheme: notes://<key>
  Examples:
    notes://python/argparse-tips
    notes://repo-summary/my-repo
    notes://conversation/2026-02-26-session1

Resources are enumerated dynamically from SQLite at list time, so notes
created after server startup are immediately visible to clients that
re-request the resource list.
"""

import json

import db


def _fetch_note_body(key: str) -> str:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT body FROM notes WHERE key = ?", (key,)
        ).fetchone()
    if not row:
        return f"Note '{key}' not found."
    return row["body"]


def _build_resource_list():
    """Return a FunctionResource for every note in the DB (called at list time)."""
    from mcp.server.fastmcp.resources.types import FunctionResource
    from pydantic import AnyUrl

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT key, tags, updated_at FROM notes ORDER BY key"
        ).fetchall()

    resources = []
    for r in rows:
        key = r["key"]
        try:
            tags = json.loads(r["tags"]) if r["tags"] else []
        except Exception:
            tags = []
        tag_str = ", ".join(tags) if tags else "no tags"
        uri_str = f"notes://{key}"
        resources.append(
            FunctionResource(
                uri=AnyUrl(uri_str),
                name=key,
                description=f"[{tag_str}] — updated {r['updated_at']}",
                mime_type="text/plain",
                fn=lambda k=key: _fetch_note_body(k),
            )
        )
    return resources


def register(mcp) -> None:  # noqa: ANN001
    # Register the URI template so the MCP SDK can route reads to this handler.
    @mcp.resource("notes://{key}", mime_type="text/plain")
    def get_note_resource(key: str) -> str:
        """Read a stored note by its key as an MCP resource."""
        return _fetch_note_body(key)

    # Override list_resources so clients see a live view of all notes in the DB,
    # not just the static template registered above.
    mcp._resource_manager.list_resources = _build_resource_list
