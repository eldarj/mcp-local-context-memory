"""
Knowledge base tools.

Notes are text entries stored in the `notes` SQLite table.
Each note has a unique key, a body (free text), and optional tags.
Search is full-text LIKE-based across key, body, and tags — sufficient
for a personal knowledge base without the complexity of FTS5 triggers.

Tools registered:
  store_note   — save or overwrite a note
  get_note     — retrieve a note by key
  search_notes — keyword search across all note fields
  list_notes   — list all note keys (+ tags), optionally filtered by tag
  delete_note  — remove a note
"""

import json

import db


def _normalize_tags(tags: str | list[str] | None) -> list[str]:
    """Accept tags as list or comma-separated string (avoids Cursor MCP array serialization issues)."""
    if tags is None:
        return []
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    s = str(tags).strip()
    if not s:
        return []
    return [t.strip() for t in s.split(",") if t.strip()]


def register(mcp) -> None:  # noqa: ANN001

    @mcp.tool()
    def store_note(
        key: str,
        body: str,
        tags: str | None = None,
    ) -> str:
        """
        Save a text note or snippet under a unique key.

        If a note with this key already exists it is overwritten.

        Args:
            key:  Unique identifier for the note (e.g. "python/argparse-tips").
            body: Full text content of the note.
            tags: Optional comma-separated tags (e.g. "newrelic,mcp,cursor"). Use this format
                  when calling from Cursor to avoid JSON serialization issues with array parameters.

        Returns a confirmation string.
        """
        tag_list = _normalize_tags(tags)
        tags_json = json.dumps(tag_list)
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO notes (key, body, tags)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    body       = excluded.body,
                    tags       = excluded.tags,
                    updated_at = datetime('now')
                """,
                (key, body, tags_json),
            )
        return f"Stored note '{key}'."

    @mcp.tool()
    def get_note(key: str) -> str:
        """
        Retrieve a note by its key.

        Returns a JSON object with keys: key, body, tags, created_at, updated_at.
        Returns an error string if the key is not found.
        """
        with db.connect() as conn:
            row = conn.execute(
                "SELECT key, body, tags, created_at, updated_at FROM notes WHERE key = ?",
                (key,),
            ).fetchone()

        if not row:
            return f"Error: note '{key}' not found."

        return json.dumps(dict(row), indent=2)

    @mcp.tool()
    def search_notes(query: str) -> str:
        """
        Search notes by keyword.

        Matches notes whose key, body, or tags contain the query string
        (case-insensitive substring match).

        Returns a JSON array of matching note objects (key, body, tags,
        created_at, updated_at). Empty array if nothing matches.
        """
        pattern = f"%{query}%"
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT key, body, tags, created_at, updated_at
                FROM notes
                WHERE key   LIKE ? COLLATE NOCASE
                   OR body  LIKE ? COLLATE NOCASE
                   OR tags  LIKE ? COLLATE NOCASE
                ORDER BY updated_at DESC
                """,
                (pattern, pattern, pattern),
            ).fetchall()

        return json.dumps([dict(r) for r in rows], indent=2)

    @mcp.tool()
    def list_notes(tag: str | None = None) -> str:
        """
        List all notes (key, tags, created_at, updated_at — no body).

        Args:
            tag: Optional tag to filter by. Only notes whose tags include
                 this value exactly are returned.

        Returns a JSON array of note summary objects.
        """
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT key, tags, created_at, updated_at FROM notes ORDER BY key"
            ).fetchall()

        notes = [dict(r) for r in rows]

        if tag:
            notes = [n for n in notes if tag in json.loads(n.get("tags", "[]"))]

        return json.dumps(notes, indent=2)

    @mcp.tool()
    def delete_note(key: str) -> str:
        """
        Delete a note by its key.

        Returns a confirmation string, or an error if the key is not found.
        """
        with db.connect() as conn:
            deleted = conn.execute(
                "DELETE FROM notes WHERE key = ?", (key,)
            ).rowcount

        if deleted:
            return f"Deleted note '{key}'."
        return f"Error: note '{key}' not found."
