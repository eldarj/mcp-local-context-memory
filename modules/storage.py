"""
File storage tools.

Stored files live on disk under DATA_DIR/files/<name>.
Metadata (mime type, tags, size) is kept in the `files` SQLite table.

Tools registered:
  store_file  — save a file/image/document (base64-encoded content)
  get_file    — retrieve a file by name (returns base64 content + metadata)
  list_files  — list stored files, optionally filtered by tag
  delete_file — remove a file
"""

import base64
import json
from pathlib import Path

import db
from config import FILES_DIR


def _normalize_tags(tags: str | None) -> list[str]:
    """Parse tags from comma-separated string (avoids Cursor MCP array serialization issues)."""
    if tags is None:
        return []
    s = str(tags).strip()
    if not s:
        return []
    return [t.strip() for t in s.split(",") if t.strip()]


def register(mcp) -> None:  # noqa: ANN001

    @mcp.tool()
    def store_file(
        name: str,
        content_base64: str,
        mime_type: str,
        tags: str | None = None,
    ) -> str:
        """
        Store a file, image, or document under the given name.

        Args:
            name:           Unique filename (may include subdirectory, e.g. "images/logo.png").
            content_base64: Base64-encoded file content.
            mime_type:      MIME type string, e.g. "image/png" or "text/plain".
            tags:           Optional comma-separated tags (e.g. "screenshots,ref"). Use this
                            format when calling from Cursor to avoid array serialization issues.

        Returns a confirmation string with the stored byte count.
        """
        try:
            content = base64.b64decode(content_base64)
        except Exception as exc:
            return f"Error: could not decode base64 content — {exc}"

        dest: Path = FILES_DIR / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

        tag_list = _normalize_tags(tags)
        tags_json = json.dumps(tag_list)
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO files (name, mime_type, tags, size_bytes)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    mime_type  = excluded.mime_type,
                    tags       = excluded.tags,
                    size_bytes = excluded.size_bytes
                """,
                (name, mime_type, tags_json, len(content)),
            )

        return f"Stored '{name}' ({len(content):,} bytes, {mime_type})."

    @mcp.tool()
    def get_file(name: str) -> str:
        """
        Retrieve a stored file by name.

        Returns a JSON object with keys:
          name, content_base64, mime_type, tags, size_bytes, created_at
        Returns an error string if the file is not found.
        """
        path: Path = FILES_DIR / name
        if not path.exists():
            return f"Error: file '{name}' not found."

        with db.connect() as conn:
            row = conn.execute(
                "SELECT mime_type, tags, size_bytes, created_at FROM files WHERE name = ?",
                (name,),
            ).fetchone()

        content_b64 = base64.b64encode(path.read_bytes()).decode()
        meta = dict(row) if row else {}

        return json.dumps(
            {
                "name": name,
                "content_base64": content_b64,
                **meta,
            },
            indent=2,
        )

    @mcp.tool()
    def list_files(tag: str | None = None) -> str:
        """
        List all stored files.

        Args:
            tag: Optional tag to filter by. Only files whose tags include this
                 value exactly are returned.

        Returns a JSON array of file metadata objects (no content).
        """
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT name, mime_type, tags, size_bytes, created_at FROM files ORDER BY name"
            ).fetchall()

        files = [dict(r) for r in rows]

        if tag:
            files = [f for f in files if tag in json.loads(f.get("tags", "[]"))]

        return json.dumps(files, indent=2)

    @mcp.tool()
    def delete_file(name: str) -> str:
        """
        Delete a stored file by name.

        Removes both the file from disk and its metadata from the database.
        Returns a confirmation or an error if not found.
        """
        path: Path = FILES_DIR / name
        removed_from_disk = False
        if path.exists():
            path.unlink()
            removed_from_disk = True

        with db.connect() as conn:
            deleted = conn.execute(
                "DELETE FROM files WHERE name = ?", (name,)
            ).rowcount

        if deleted or removed_from_disk:
            return f"Deleted '{name}'."
        return f"Error: file '{name}' not found."
