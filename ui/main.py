import json
import sqlite3
from pathlib import Path

import numpy as np
import umap
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "db.sqlite"

app = FastAPI()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/graph")
def get_graph():
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT n.key, n.tags, SUBSTR(n.body, 1, 140) AS snippet, e.embedding
            FROM notes n
            JOIN note_embeddings e ON n.key = e.key
        """).fetchall()
    finally:
        conn.close()

    if len(rows) < 2:
        return {"nodes": []}

    keys = [r["key"] for r in rows]
    snippets = [r["snippet"].replace("\n", " ") if r["snippet"] else "" for r in rows]

    tags_list = []
    for r in rows:
        try:
            tags_list.append(json.loads(r["tags"]) if r["tags"] else [])
        except Exception:
            tags_list.append([])

    embeddings = np.array([
        np.frombuffer(r["embedding"], dtype=np.float32) for r in rows
    ])

    n_neighbors = min(15, len(rows) - 1)
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=0.3,
        metric="cosine",
        random_state=42,
    )
    coords = reducer.fit_transform(embeddings)

    nodes = [
        {
            "key": keys[i],
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
            "tags": tags_list[i],
            "snippet": snippets[i],
        }
        for i in range(len(keys))
    ]
    return {"nodes": nodes}


@app.get("/api/notes/{key:path}")
def get_note(key: str):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT key, body, tags, created_at, updated_at FROM notes WHERE key = ?",
            (key,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Note not found")

    return {
        "key": row["key"],
        "body": row["body"],
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# Static files must be mounted last
app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
