#!/usr/bin/env python3
"""Backfill semantic embeddings for existing notes that don't have one yet.

Run once after upgrading to semantic search:

    python3 scripts/backfill_embeddings.py

Safe to re-run — skips notes that already have an embedding.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import db
from modules.embeddings import encode, to_blob


def main() -> None:
    db.init()

    with db.connect() as conn:
        notes = conn.execute("SELECT key, body FROM notes").fetchall()
        already_done = {
            r["key"]
            for r in conn.execute("SELECT key FROM note_embeddings").fetchall()
        }

    to_backfill = [n for n in notes if n["key"] not in already_done]

    if not to_backfill:
        print("All notes already have embeddings. Nothing to do.")
        return

    print(f"Backfilling embeddings for {len(to_backfill)} note(s)...")

    for i, note in enumerate(to_backfill, 1):
        blob = to_blob(encode(note["body"]))
        with db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO note_embeddings (key, embedding) VALUES (?, ?)",
                (note["key"], blob),
            )
        print(f"  [{i}/{len(to_backfill)}] {note['key']}")

    print("Done.")


if __name__ == "__main__":
    main()
