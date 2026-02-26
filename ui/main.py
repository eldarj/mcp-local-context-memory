import json
import sqlite3
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "db.sqlite"

app = FastAPI()


def get_conn():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/graph")
def get_graph():
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT n.key, n.tags, n.body, SUBSTR(n.body, 1, 140) AS snippet, e.embedding
            FROM notes n
            JOIN note_embeddings e ON n.key = e.key
        """).fetchall()
    finally:
        conn.close()

    if len(rows) < 2:
        return {"nodes": [], "links": []}

    keys = [r["key"] for r in rows]
    snippets = [r["snippet"].replace("\n", " ") if r["snippet"] else "" for r in rows]

    def extract_title(body: str) -> str:
        first_line = body.split("\n")[0].strip()
        # Format A: "## Session: title" or "## title"
        if first_line.startswith("#"):
            title = first_line.lstrip("#").strip()
            for prefix in ("Session: ", "Session - "):
                if title.startswith(prefix):
                    title = title[len(prefix):]
            return title
        # Format B: "Session on YYYY-MM-DD in project: X\n\n## What we discussed"
        if "in project:" in first_line:
            return first_line.split("in project:")[-1].strip()
        # Format C: plain "Session: title"
        if first_line.lower().startswith("session:"):
            return first_line.split(":", 1)[-1].strip()
        return first_line

    tags_list = []
    for r in rows:
        try:
            tags_list.append(json.loads(r["tags"]) if r["tags"] else [])
        except Exception:
            tags_list.append([])

    embeddings = np.array([
        np.frombuffer(r["embedding"], dtype=np.float32) for r in rows
    ])

    # Pairwise cosine similarities
    sims = cosine_similarity(embeddings)

    # Each node connects to its top-3 most similar neighbours (undirected, no duplicates)
    seen = set()
    links = []
    for i in range(len(keys)):
        scores = [(j, float(sims[i][j])) for j in range(len(keys)) if j != i]
        scores.sort(key=lambda x: -x[1])
        for j, sim in scores[:3]:
            edge = (min(i, j), max(i, j))
            if edge not in seen:
                seen.add(edge)
                links.append({"source": i, "target": j, "similarity": sim})

    body_lengths = [len(r["snippet"]) for r in rows]  # snippet is already fetched

    # Fetch full body lengths separately for accurate sizing
    conn2 = get_conn()
    try:
        len_rows = conn2.execute("SELECT key, LENGTH(body) as len FROM notes").fetchall()
        len_map = {r["key"]: r["len"] for r in len_rows}
    finally:
        conn2.close()

    titles = [extract_title(r["body"]) for r in rows]

    nodes = [
        {
            "key": keys[i],
            "title": titles[i],
            "tags": tags_list[i],
            "snippet": snippets[i],
            "body_length": len_map.get(keys[i], 1000),
        }
        for i in range(len(keys))
    ]
    return {"nodes": nodes, "links": links}


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
