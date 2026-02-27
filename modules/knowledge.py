"""
Knowledge base tools.

Notes are text entries stored in the `notes` SQLite table.
Each note has a unique key, a body (free text), and optional tags.

Search defaults to semantic (embedding-based) similarity so queries match
by meaning rather than exact keywords. Pass keyword=True to fall back to
the original case-insensitive LIKE search.

Tools registered:
  store_note   — save or overwrite a note (also stores its embedding)
  get_note     — retrieve a note by key
  search_notes — semantic search by default; keyword search opt-in
  list_notes   — list all note keys (+ tags), optionally filtered by tag
  delete_note  — remove a note (and its embedding)
"""

import json

import numpy as np

import db
from modules.embeddings import AUTO_TAG_SKIP, encode, from_blob, rank, suggest_tags, to_blob


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


def _compute_tag_centroids() -> dict[str, list[float]]:
    """Compute per-tag centroid embedding vectors from all stored notes.

    For each tag, averages all embeddings of notes carrying that tag and
    L2-normalises the result. Tags in AUTO_TAG_SKIP are excluded so
    overly generic tags don't bleed into auto-suggestions.
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT n.tags, e.embedding FROM notes n JOIN note_embeddings e ON n.key = e.key"
        ).fetchall()

    tag_vecs: dict[str, list[list[float]]] = {}
    for r in rows:
        try:
            tags = json.loads(r["tags"]) if r["tags"] else []
        except Exception:
            tags = []
        vec = from_blob(r["embedding"])
        for tag in tags:
            if tag in AUTO_TAG_SKIP:
                continue
            tag_vecs.setdefault(tag, []).append(vec)

    centroids: dict[str, list[float]] = {}
    for tag, vecs in tag_vecs.items():
        mat = np.array(vecs)
        mean = mat.mean(axis=0)
        norm = float(np.linalg.norm(mean))
        if norm > 0:
            mean = mean / norm
        centroids[tag] = mean.tolist()
    return centroids


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
        An embedding is generated and stored alongside the note to
        enable semantic search.

        Args:
            key:  Unique identifier for the note (e.g. "python/argparse-tips").
            body: Full text content of the note.
            tags: Optional comma-separated tags (e.g. "newrelic,mcp,cursor"). Use this format
                  when calling from Cursor to avoid JSON serialization issues with array parameters.

        Returns a confirmation string.
        """
        tag_list = _normalize_tags(tags)
        embedding_vec = encode(body)
        embedding_blob = to_blob(embedding_vec)

        auto_tagged = False
        if not tag_list:
            centroids = _compute_tag_centroids()
            tag_list = suggest_tags(embedding_vec, centroids)
            auto_tagged = bool(tag_list)

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
            conn.execute(
                """
                INSERT INTO note_embeddings (key, embedding)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET embedding = excluded.embedding
                """,
                (key, embedding_blob),
            )
        suffix = f" (auto-tagged: {', '.join(tag_list)})" if auto_tagged else ""
        return f"Stored note '{key}'.{suffix}"

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
    def search_notes(query: str, keyword: bool = False) -> str:
        """
        Search notes by meaning (default) or by keyword.

        By default, uses semantic search: finds notes that match the intent
        of the query even when exact words differ. Results are ordered by
        similarity, most relevant first.

        Set keyword=True for a fast case-insensitive substring match across
        key, body, and tags — useful when you need an exact term or phrase.

        Args:
            query:   What to search for.
            keyword: If True, use keyword (LIKE) search instead of semantic.

        Returns a JSON array of matching note objects (key, body, tags,
        created_at, updated_at). Empty array if nothing matches.
        """
        if keyword:
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

        # Semantic search
        query_vec = encode(query)
        with db.connect() as conn:
            emb_rows = conn.execute(
                "SELECT key, embedding FROM note_embeddings"
            ).fetchall()

        candidates = [(r["key"], from_blob(r["embedding"])) for r in emb_rows]
        ranked = rank(query_vec, candidates)

        top_keys = [k for k, _ in ranked[:10]]
        if not top_keys:
            return "[]"

        placeholders = ",".join("?" * len(top_keys))
        with db.connect() as conn:
            rows = conn.execute(
                f"SELECT key, body, tags, created_at, updated_at FROM notes"  # noqa: S608
                f" WHERE key IN ({placeholders})",
                top_keys,
            ).fetchall()

        notes_by_key = {r["key"]: dict(r) for r in rows}
        return json.dumps(
            [notes_by_key[k] for k in top_keys if k in notes_by_key],
            indent=2,
        )

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
            conn.execute("DELETE FROM note_embeddings WHERE key = ?", (key,))

        if deleted:
            return f"Deleted note '{key}'."
        return f"Error: note '{key}' not found."
