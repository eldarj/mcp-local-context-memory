import json
import sqlite3
import struct
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sentence_transformers import SentenceTransformer

DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "db.sqlite"

_embed_model: SentenceTransformer | None = None


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


def _from_blob(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))

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


@app.get("/api/stats")
def get_stats():
    conn = get_conn()
    try:
        note_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        file_row = conn.execute(
            "SELECT COUNT(*) as c, COALESCE(SUM(size_bytes), 0) as s FROM files"
        ).fetchone()
        tag_rows = conn.execute("SELECT tags FROM notes").fetchall()
        recent_notes = conn.execute(
            "SELECT key, tags, updated_at FROM notes ORDER BY updated_at DESC LIMIT 10"
        ).fetchall()
        recent_files = conn.execute(
            "SELECT name, mime_type, size_bytes, created_at FROM files ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
    finally:
        conn.close()

    tag_counts: dict[str, int] = {}
    for r in tag_rows:
        try:
            tags = json.loads(r["tags"]) if r["tags"] else []
        except Exception:
            tags = []
        for t in tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    tag_breakdown = sorted(tag_counts.items(), key=lambda x: -x[1])

    return {
        "note_count": note_count,
        "file_count": file_row["c"],
        "total_file_bytes": file_row["s"],
        "tag_breakdown": [[t, c] for t, c in tag_breakdown],
        "recent_notes": [dict(r) for r in recent_notes],
        "recent_files": [dict(r) for r in recent_files],
    }


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


@app.get("/stats", response_class=HTMLResponse)
def stats_page():
    data = get_stats()

    tag_rows_html = "".join(
        f"<tr><td><span class='tag'>{t}</span></td><td>{c}</td></tr>"
        for t, c in data["tag_breakdown"]
    )

    def note_tags_html(tags_json: str) -> str:
        try:
            tags = json.loads(tags_json) if tags_json else []
        except Exception:
            tags = []
        return " ".join(f"<span class='tag'>{t}</span>" for t in tags)

    def note_row_html(r: dict) -> str:
        key_js = json.dumps(r["key"])
        return (
            f"<tr>"
            f"<td><span class='note-link' onclick='openSidebar({key_js})'>{r['key']}</span></td>"
            f"<td>{note_tags_html(r['tags'])}</td>"
            f"<td style='color:#999;font-size:11px'>{r['updated_at']}</td></tr>"
        )

    recent_notes_html = "".join(note_row_html(r) for r in data["recent_notes"])

    recent_files_html = "".join(
        f"<tr><td style='font-family:monospace;font-size:12px'>{r['name']}</td>"
        f"<td style='color:#999;font-size:11px'>{r['mime_type']}</td>"
        f"<td style='color:#999;font-size:11px'>{_fmt_bytes(r['size_bytes'] or 0)}</td>"
        f"<td style='color:#999;font-size:11px'>{r['created_at']}</td></tr>"
        for r in data["recent_files"]
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Knowledge Base — Stats</title>
  <link rel="stylesheet" href="/style.css">
  <script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>
  <style>
    body {{ overflow: auto; display: block; }}
    .stats-page {{ max-width: 860px; margin: 0 auto; padding: 32px 24px; }}
    .cards {{ display: flex; gap: 16px; margin-bottom: 32px; flex-wrap: wrap; }}
    .card {{ background: #fff; border: 1px solid #ddddd8; border-radius: 8px;
             padding: 20px 24px; flex: 1; min-width: 160px; }}
    .card .value {{ font-size: 32px; font-weight: 700; color: #1a1a1a; }}
    .card .label {{ font-size: 12px; color: #999; margin-top: 4px; }}
    .section {{ margin-bottom: 32px; }}
    .section h2 {{ font-size: 14px; font-weight: 600; color: #555;
                   text-transform: uppercase; letter-spacing: 0.5px;
                   margin-bottom: 12px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff;
             border: 1px solid #ddddd8; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 9px 14px; text-align: left; border-bottom: 1px solid #f0f0eb; }}
    th {{ background: #f8f8f5; font-size: 11px; color: #888;
          text-transform: uppercase; letter-spacing: 0.4px; font-weight: 600; }}
    tr:last-child td {{ border-bottom: none; }}
    .note-link {{ font-family: monospace; font-size: 12px; color: #4466cc;
                  cursor: pointer; }}
    .note-link:hover {{ text-decoration: underline; }}
    /* Sidebar as fixed overlay — same structure as graph page */
    #sidebar {{ position: fixed; top: 0; right: 0; bottom: 0; width: 0;
                overflow: hidden; transition: width 0.22s ease;
                border-left: 1px solid #ddddd8; display: flex;
                flex-direction: column; background: #ffffff;
                z-index: 100; box-shadow: -4px 0 20px rgba(0,0,0,0.08); }}
    #sidebar.open {{ width: 750px; }}
  </style>
</head>
<body>
  <header>
    <h1>Knowledge Base</h1>
    <span id="node-count" style="color:#999;font-size:13px">Stats</span>
    <a href="/" style="margin-left:auto;font-size:13px;color:#777;text-decoration:none;margin-right:16px;">&#8592; Graph</a>
    <a href="/notes" style="font-size:13px;color:#777;text-decoration:none;margin-right:16px;">Notes</a>
    <a href="/timeline" style="font-size:13px;color:#777;text-decoration:none;margin-right:16px;">Timeline</a>
    <a href="/info" style="font-size:13px;color:#777;text-decoration:none;">Info</a>
  </header>
  <div class="stats-page">

    <div class="cards">
      <div class="card">
        <div class="value">{data['note_count']}</div>
        <div class="label">Notes</div>
      </div>
      <div class="card">
        <div class="value">{data['file_count']}</div>
        <div class="label">Files</div>
      </div>
      <div class="card">
        <div class="value">{_fmt_bytes(data['total_file_bytes'])}</div>
        <div class="label">File storage</div>
      </div>
      <div class="card">
        <div class="value">{len(data['tag_breakdown'])}</div>
        <div class="label">Unique tags</div>
      </div>
    </div>

    <div class="section">
      <h2>Recently updated notes</h2>
      <table>
        <thead><tr><th>Key</th><th>Tags</th><th>Updated</th></tr></thead>
        <tbody>{recent_notes_html or '<tr><td colspan="3" style="color:#bbb">No notes yet</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>Recently added files</h2>
      <table>
        <thead><tr><th>Name</th><th>Type</th><th>Size</th><th>Created</th></tr></thead>
        <tbody>{recent_files_html or '<tr><td colspan="4" style="color:#bbb">No files yet</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>Tags</h2>
      <table>
        <thead><tr><th>Tag</th><th>Notes</th></tr></thead>
        <tbody>{tag_rows_html or '<tr><td colspan="2" style="color:#bbb">No tags yet</td></tr>'}</tbody>
      </table>
    </div>

  </div>

  <!-- Sidebar — same structure as graph page -->
  <div id="sidebar">
    <div id="sidebar-header">
      <div id="note-key"></div>
      <button id="close-btn" onclick="closeSidebar()">&#x2715;</button>
    </div>
    <div id="sidebar-meta">
      <div id="note-tags"></div>
      <div id="note-meta"></div>
    </div>
    <div id="sidebar-body">
      <div id="note-loading" style="display:none">Loading&hellip;</div>
      <div id="note-content" style="display:none">
        <div id="note-body"></div>
      </div>
    </div>
  </div>

  <script>
    async function openSidebar(key) {{
      document.getElementById('sidebar').classList.add('open');
      document.getElementById('note-loading').style.display = 'block';
      document.getElementById('note-content').style.display = 'none';
      try {{
        const res = await fetch(`/api/notes/${{encodeURIComponent(key)}}`);
        if (!res.ok) throw new Error(`${{res.status}}`);
        const note = await res.json();
        document.getElementById('note-key').textContent = note.key;
        document.getElementById('note-tags').innerHTML =
          note.tags.map(t => `<span class="tag">${{t}}</span>`).join('');
        document.getElementById('note-meta').textContent = `Updated ${{note.updated_at}}`;
        document.getElementById('note-body').innerHTML = marked.parse(note.body);
        document.getElementById('note-loading').style.display = 'none';
        document.getElementById('note-content').style.display = 'block';
      }} catch (e) {{
        document.getElementById('note-loading').textContent = 'Failed to load: ' + e.message;
      }}
    }}

    function closeSidebar() {{
      document.getElementById('sidebar').classList.remove('open');
    }}

    document.addEventListener('keydown', e => {{
      if (e.key === 'Escape') closeSidebar();
    }});
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/api/search")
def api_search(q: str = "", mode: str = "keyword"):
    conn = get_conn()
    try:
        if not q.strip():
            rows = conn.execute(
                "SELECT key, tags, updated_at FROM notes ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

        if mode == "semantic":
            emb_rows = conn.execute(
                "SELECT key, embedding FROM note_embeddings"
            ).fetchall()
            if not emb_rows:
                return []
            query_vec = np.array(
                _get_embed_model().encode(q, normalize_embeddings=True)
            ).reshape(1, -1)
            keys = [r["key"] for r in emb_rows]
            matrix = np.array([_from_blob(r["embedding"]) for r in emb_rows])
            scores = cosine_similarity(query_vec, matrix)[0]
            ranked_keys = [keys[i] for i in np.argsort(scores)[::-1][:50]]
            placeholders = ",".join("?" * len(ranked_keys))
            meta_rows = conn.execute(
                f"SELECT key, tags, updated_at FROM notes WHERE key IN ({placeholders})",  # noqa: S608
                ranked_keys,
            ).fetchall()
            meta = {r["key"]: dict(r) for r in meta_rows}
            return [meta[k] for k in ranked_keys if k in meta]
        else:
            pattern = f"%{q}%"
            rows = conn.execute(
                """SELECT key, tags, updated_at FROM notes
                   WHERE key LIKE ? COLLATE NOCASE OR body LIKE ? COLLATE NOCASE
                   ORDER BY updated_at DESC""",
                (pattern, pattern),
            ).fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/notes", response_class=HTMLResponse)
def notes_page():
    SIDEBAR_CSS = """
    #sidebar { position: fixed; top: 0; right: 0; bottom: 0; width: 0;
               overflow: hidden; transition: width 0.22s ease;
               border-left: 1px solid #ddddd8; display: flex;
               flex-direction: column; background: #ffffff;
               z-index: 100; box-shadow: -4px 0 20px rgba(0,0,0,0.08); }
    #sidebar.open { width: 750px; }
    """
    SIDEBAR_HTML = """
  <div id="sidebar">
    <div id="sidebar-header">
      <div id="note-key"></div>
      <button id="close-btn" onclick="closeSidebar()">&#x2715;</button>
    </div>
    <div id="sidebar-meta">
      <div id="note-tags"></div>
      <div id="note-meta"></div>
    </div>
    <div id="sidebar-body">
      <div id="note-loading" style="display:none">Loading&hellip;</div>
      <div id="note-content" style="display:none">
        <div id="note-body"></div>
      </div>
    </div>
  </div>"""
    SIDEBAR_JS = """
    async function openSidebar(key) {
      document.getElementById('sidebar').classList.add('open');
      document.getElementById('note-loading').style.display = 'block';
      document.getElementById('note-content').style.display = 'none';
      try {
        const res = await fetch(`/api/notes/${encodeURIComponent(key)}`);
        if (!res.ok) throw new Error(`${res.status}`);
        const note = await res.json();
        document.getElementById('note-key').textContent = note.key;
        document.getElementById('note-tags').innerHTML =
          note.tags.map(t => `<span class="tag">${t}</span>`).join('');
        document.getElementById('note-meta').textContent = `Updated ${note.updated_at}`;
        document.getElementById('note-body').innerHTML = marked.parse(note.body);
        document.getElementById('note-loading').style.display = 'none';
        document.getElementById('note-content').style.display = 'block';
      } catch (e) {
        document.getElementById('note-loading').textContent = 'Failed to load: ' + e.message;
      }
    }
    function closeSidebar() {
      document.getElementById('sidebar').classList.remove('open');
    }
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSidebar(); });"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Knowledge Base — Notes</title>
  <link rel="stylesheet" href="/style.css">
  <script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>
  <style>
    body {{ overflow: auto; display: block; }}
    .notes-page {{ max-width: 860px; margin: 0 auto; padding: 32px 24px; }}
    .search-bar {{ display: flex; gap: 8px; margin-bottom: 24px; }}
    .search-bar input {{
      flex: 1; padding: 9px 14px; border: 1px solid #ddddd8; border-radius: 6px;
      font-size: 14px; color: #1a1a1a; background: #fff; outline: none;
    }}
    .search-bar input:focus {{ border-color: #aaa; }}
    .search-bar button {{
      padding: 9px 16px; border: 1px solid #ddddd8; border-radius: 6px;
      font-size: 13px; cursor: pointer; white-space: nowrap;
      background: #fff; color: #555; transition: background 0.15s;
    }}
    .search-bar button:hover {{ background: #f0f0eb; }}
    .search-bar button.mode-semantic {{ background: #1a1a1a; color: #fff; border-color: #1a1a1a; }}
    #result-count {{ font-size: 12px; color: #999; margin-bottom: 14px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff;
             border: 1px solid #ddddd8; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 9px 14px; text-align: left; border-bottom: 1px solid #f0f0eb; }}
    th {{ background: #f8f8f5; font-size: 11px; color: #888;
          text-transform: uppercase; letter-spacing: 0.4px; font-weight: 600; }}
    tr:last-child td {{ border-bottom: none; }}
    .note-link {{ font-family: monospace; font-size: 12px; color: #4466cc; cursor: pointer; }}
    .note-link:hover {{ text-decoration: underline; }}
    #spinner {{ display: none; font-size: 12px; color: #999; margin-bottom: 14px; }}
    {SIDEBAR_CSS}
  </style>
</head>
<body>
  <header>
    <h1>Knowledge Base</h1>
    <span id="node-count" style="color:#999;font-size:13px">Notes</span>
    <a href="/" style="margin-left:auto;font-size:13px;color:#777;text-decoration:none;margin-right:16px;">&#8592; Graph</a>
    <a href="/stats" style="font-size:13px;color:#777;text-decoration:none;margin-right:16px;">Stats</a>
    <a href="/timeline" style="font-size:13px;color:#777;text-decoration:none;margin-right:16px;">Timeline</a>
    <a href="/info" style="font-size:13px;color:#777;text-decoration:none;">Info</a>
  </header>

  <div class="notes-page">
    <div class="search-bar">
      <input id="search-input" type="text" placeholder="Search notes…" oninput="onSearchInput()" />
      <button id="mode-btn" onclick="toggleMode()">Search by: Title</button>
    </div>
    <div id="spinner">Searching&hellip;</div>
    <div id="result-count"></div>
    <table id="notes-table">
      <thead><tr><th>Key</th><th>Tags</th><th>Updated</th></tr></thead>
      <tbody id="notes-body"><tr><td colspan="3" style="color:#bbb">Loading&hellip;</td></tr></tbody>
    </table>
  </div>

  {SIDEBAR_HTML}

  <script>
    let searchMode = 'keyword';
    let debounceTimer = null;

    function toggleMode() {{
      searchMode = searchMode === 'keyword' ? 'semantic' : 'keyword';
      const btn = document.getElementById('mode-btn');
      if (searchMode === 'semantic') {{
        btn.textContent = 'Search by: Meaning';
        btn.classList.add('mode-semantic');
      }} else {{
        btn.textContent = 'Search by: Title';
        btn.classList.remove('mode-semantic');
      }}
      runSearch();
    }}

    function onSearchInput() {{
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(runSearch, 300);
    }}

    async function runSearch() {{
      const q = document.getElementById('search-input').value.trim();
      document.getElementById('spinner').style.display = 'block';
      document.getElementById('result-count').textContent = '';
      try {{
        const res = await fetch(`/api/search?q=${{encodeURIComponent(q)}}&mode=${{searchMode}}`);
        const notes = await res.json();
        renderNotes(notes);
      }} catch (e) {{
        document.getElementById('notes-body').innerHTML =
          `<tr><td colspan="3" style="color:#c00">Error: ${{e.message}}</td></tr>`;
      }} finally {{
        document.getElementById('spinner').style.display = 'none';
      }}
    }}

    function renderNotes(notes) {{
      document.getElementById('result-count').textContent =
        notes.length === 0 ? 'No notes found.' : `${{notes.length}} note${{notes.length === 1 ? '' : 's'}}`;
      if (notes.length === 0) {{
        document.getElementById('notes-body').innerHTML =
          '<tr><td colspan="3" style="color:#bbb">No notes found.</td></tr>';
        return;
      }}
      document.getElementById('notes-body').innerHTML = notes.map(n => {{
        const tags = (() => {{ try {{ return JSON.parse(n.tags || '[]'); }} catch {{ return []; }} }})();
        const tagsHtml = tags.map(t => `<span class="tag">${{t}}</span>`).join(' ');
        const keyJs = JSON.stringify(n.key);
        return `<tr>
          <td><span class="note-link" onclick="openSidebar(${{keyJs}})">${{n.key}}</span></td>
          <td>${{tagsHtml}}</td>
          <td style="color:#999;font-size:11px">${{n.updated_at}}</td>
        </tr>`;
      }}).join('');
    }}

    {SIDEBAR_JS}

    runSearch();
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/api/timeline")
def api_timeline(tag: str = ""):
    conn = get_conn()
    try:
        if tag:
            rows = conn.execute(
                """SELECT key, tags, created_at, updated_at,
                          substr(body, 1, 300) as snippet
                   FROM notes
                   WHERE tags LIKE ?
                   ORDER BY created_at ASC""",
                (f'%"{tag}"%',),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT key, tags, created_at, updated_at,
                          substr(body, 1, 300) as snippet
                   FROM notes
                   ORDER BY created_at ASC"""
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@app.get("/timeline", response_class=HTMLResponse)
def timeline_page():
    SIDEBAR_CSS = """
    #sidebar { position: fixed; top: 0; right: 0; bottom: 0; width: 0;
               overflow: hidden; transition: width 0.22s ease;
               border-left: 1px solid #ddddd8; display: flex;
               flex-direction: column; background: #ffffff;
               z-index: 100; box-shadow: -4px 0 20px rgba(0,0,0,0.08); }
    #sidebar.open { width: 750px; }
    """
    SIDEBAR_HTML = """
  <div id="sidebar">
    <div id="sidebar-header">
      <div id="note-key"></div>
      <button id="close-btn" onclick="closeSidebar()">&#x2715;</button>
    </div>
    <div id="sidebar-meta">
      <div id="note-tags"></div>
      <div id="note-meta"></div>
    </div>
    <div id="sidebar-body">
      <div id="note-loading" style="display:none">Loading&hellip;</div>
      <div id="note-content" style="display:none">
        <div id="note-body"></div>
      </div>
    </div>
  </div>"""
    SIDEBAR_JS = """
    async function openSidebar(key) {
      document.getElementById('sidebar').classList.add('open');
      document.getElementById('note-loading').style.display = 'block';
      document.getElementById('note-content').style.display = 'none';
      try {
        const res = await fetch(`/api/notes/${encodeURIComponent(key)}`);
        if (!res.ok) throw new Error(`${res.status}`);
        const note = await res.json();
        document.getElementById('note-key').textContent = note.key;
        document.getElementById('note-tags').innerHTML =
          note.tags.map(t => `<span class="tag">${t}</span>`).join('');
        document.getElementById('note-meta').textContent = `Updated ${note.updated_at}`;
        document.getElementById('note-body').innerHTML = marked.parse(note.body);
        document.getElementById('note-loading').style.display = 'none';
        document.getElementById('note-content').style.display = 'block';
      } catch (e) {
        document.getElementById('note-loading').textContent = 'Failed to load: ' + e.message;
      }
    }
    function closeSidebar() {
      document.getElementById('sidebar').classList.remove('open');
    }
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSidebar(); });"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Knowledge Base — Timeline</title>
  <link rel="stylesheet" href="/style.css">
  <script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>
  <style>
    body {{ overflow: auto; display: block; }}
    .timeline-page {{ max-width: 860px; margin: 0 auto; padding: 32px 24px; }}

    /* Tag filter bar */
    .tag-filter {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 28px; align-items: center; }}
    .tag-filter-label {{ font-size: 11px; color: #999; text-transform: uppercase;
                         letter-spacing: 0.5px; margin-right: 4px; }}
    .filter-tag {{ background: #f0f0eb; color: #555; padding: 4px 10px; border-radius: 4px;
                   font-size: 12px; cursor: pointer; border: 1px solid transparent;
                   transition: all 0.15s; user-select: none; }}
    .filter-tag:hover {{ background: #e4e4de; }}
    .filter-tag.active {{ background: #1a1a1a; color: #fff; border-color: #1a1a1a; }}
    .clear-btn {{ font-size: 12px; color: #999; cursor: pointer; margin-left: 8px; }}
    .clear-btn:hover {{ color: #555; }}

    /* Result count */
    #result-count {{ font-size: 12px; color: #999; margin-bottom: 20px; }}

    /* Timeline layout */
    .timeline {{ position: relative; padding-left: 32px; }}
    .timeline::before {{
      content: ''; position: absolute; left: 6px; top: 0; bottom: 0;
      width: 2px; background: #e8e8e4; border-radius: 1px;
    }}

    /* Month group header */
    .month-group {{ margin-bottom: 8px; }}
    .month-label {{
      position: relative; font-size: 11px; font-weight: 600; color: #888;
      text-transform: uppercase; letter-spacing: 0.8px; padding: 16px 0 10px;
      display: flex; align-items: center; gap: 10px;
    }}
    .month-label::before {{
      content: ''; display: inline-block; width: 10px; height: 10px;
      border-radius: 50%; background: #ccc; border: 2px solid #fff;
      outline: 2px solid #ccc; position: absolute; left: -29px;
    }}

    /* Note card */
    .note-card {{
      background: #fff; border: 1px solid #ddddd8; border-radius: 8px;
      padding: 14px 18px; margin-bottom: 10px; cursor: pointer;
      transition: box-shadow 0.15s, border-color 0.15s;
      position: relative;
    }}
    .note-card:hover {{
      box-shadow: 0 2px 12px rgba(0,0,0,0.07); border-color: #bbb;
    }}
    .note-card::before {{
      content: ''; position: absolute; left: -27px; top: 18px;
      width: 8px; height: 8px; border-radius: 50%;
      background: #4466cc; border: 2px solid #fff; outline: 2px solid #4466cc;
    }}
    .note-key {{
      font-family: monospace; font-size: 13px; color: #4466cc;
      margin-bottom: 6px; word-break: break-all;
    }}
    .note-tags {{ display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }}
    .note-snippet {{
      font-size: 12px; color: #777; line-height: 1.5;
      white-space: pre-wrap; overflow: hidden;
      display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
    }}
    .note-date {{ font-size: 11px; color: #bbb; margin-top: 8px; }}

    #spinner {{ display: none; font-size: 12px; color: #999; margin-bottom: 14px; }}

    {SIDEBAR_CSS}
  </style>
</head>
<body>
  <header>
    <h1>Knowledge Base</h1>
    <span id="node-count" style="color:#999;font-size:13px">Timeline</span>
    <a href="/" style="margin-left:auto;font-size:13px;color:#777;text-decoration:none;margin-right:16px;">&#8592; Graph</a>
    <a href="/notes" style="font-size:13px;color:#777;text-decoration:none;margin-right:16px;">Notes</a>
    <a href="/stats" style="font-size:13px;color:#777;text-decoration:none;margin-right:16px;">Stats</a>
    <a href="/info" style="font-size:13px;color:#777;text-decoration:none;">Info</a>
  </header>

  <div class="timeline-page">
    <div class="tag-filter" id="tag-bar">
      <span class="tag-filter-label">Filter:</span>
      <span id="tag-chips-loading" style="font-size:12px;color:#bbb">Loading tags&hellip;</span>
    </div>
    <div id="spinner">Loading&hellip;</div>
    <div id="result-count"></div>
    <div class="timeline" id="timeline-root"></div>
  </div>

  {SIDEBAR_HTML}

  <script>
    let activeTag = null;

    // ── Tag bar ───────────────────────────────────────────────────────────────
    async function loadTags() {{
      const res = await fetch('/api/stats');
      const data = await res.json();
      const bar = document.getElementById('tag-bar');
      bar.innerHTML = '<span class="tag-filter-label">Filter by tag:</span>';

      const clearBtn = document.createElement('span');
      clearBtn.className = 'clear-btn';
      clearBtn.textContent = 'Clear';
      clearBtn.style.display = 'none';
      clearBtn.onclick = () => {{ setTag(null); }};

      data.tag_breakdown.forEach(([tag, count]) => {{
        const chip = document.createElement('span');
        chip.className = 'filter-tag';
        chip.dataset.tag = tag;
        chip.textContent = `${{tag}} (${{count}})`;
        chip.onclick = () => {{
          setTag(activeTag === tag ? null : tag);
        }};
        bar.appendChild(chip);
      }});

      bar.appendChild(clearBtn);
    }}

    function setTag(tag) {{
      activeTag = tag;
      document.querySelectorAll('.filter-tag').forEach(c => {{
        c.classList.toggle('active', c.dataset.tag === tag);
      }});
      const clearBtn = document.querySelector('.clear-btn');
      if (clearBtn) clearBtn.style.display = tag ? 'inline' : 'none';
      loadTimeline();
    }}

    // ── Timeline render ───────────────────────────────────────────────────────
    async function loadTimeline() {{
      document.getElementById('spinner').style.display = 'block';
      document.getElementById('result-count').textContent = '';
      document.getElementById('timeline-root').innerHTML = '';

      const url = activeTag
        ? `/api/timeline?tag=${{encodeURIComponent(activeTag)}}`
        : '/api/timeline';

      const res = await fetch(url);
      const notes = await res.json();

      document.getElementById('spinner').style.display = 'none';
      document.getElementById('result-count').textContent =
        notes.length === 0 ? 'No notes found.'
        : `${{notes.length}} note${{notes.length === 1 ? '' : 's'}}${{activeTag ? ` tagged "${{activeTag}}"` : ''}}`;

      if (notes.length === 0) return;

      // Group by YYYY-MM
      const groups = {{}};
      notes.forEach(n => {{
        const month = (n.created_at || '').slice(0, 7) || 'Unknown';
        if (!groups[month]) groups[month] = [];
        groups[month].push(n);
      }});

      const root = document.getElementById('timeline-root');
      Object.keys(groups).sort().reverse().forEach(month => {{
        const groupEl = document.createElement('div');
        groupEl.className = 'month-group';

        const label = document.createElement('div');
        label.className = 'month-label';
        label.textContent = formatMonth(month);
        groupEl.appendChild(label);

        groups[month].slice().reverse().forEach(note => {{
          groupEl.appendChild(buildCard(note));
        }});

        root.appendChild(groupEl);
      }});
    }}

    function formatMonth(ym) {{
      if (!ym || ym === 'Unknown') return 'Unknown';
      const [y, m] = ym.split('-');
      const months = ['Jan','Feb','Mar','Apr','May','Jun',
                      'Jul','Aug','Sep','Oct','Nov','Dec'];
      return `${{months[parseInt(m,10)-1] || m}} ${{y}}`;
    }}

    function buildCard(note) {{
      const tags = (() => {{ try {{ return JSON.parse(note.tags || '[]'); }} catch {{ return []; }} }})();
      const snippet = (note.snippet || '').replace(/^#+\\s*/gm, '').replace(/\\*+/g, '').trim();

      const card = document.createElement('div');
      card.className = 'note-card';
      card.onclick = () => openSidebar(note.key);

      const keyEl = document.createElement('div');
      keyEl.className = 'note-key';
      keyEl.textContent = note.key;
      card.appendChild(keyEl);

      if (tags.length) {{
        const tagsEl = document.createElement('div');
        tagsEl.className = 'note-tags';
        tags.forEach(t => {{
          const chip = document.createElement('span');
          chip.className = 'tag' + (t === activeTag ? ' active' : '');
          chip.textContent = t;
          chip.style.cursor = 'pointer';
          chip.onclick = e => {{ e.stopPropagation(); setTag(activeTag === t ? null : t); }};
          tagsEl.appendChild(chip);
        }});
        card.appendChild(tagsEl);
      }}

      if (snippet) {{
        const snippetEl = document.createElement('div');
        snippetEl.className = 'note-snippet';
        snippetEl.textContent = snippet.slice(0, 220);
        card.appendChild(snippetEl);
      }}

      const dateEl = document.createElement('div');
      dateEl.className = 'note-date';
      dateEl.textContent = note.created_at || '';
      card.appendChild(dateEl);

      return card;
    }}

    {SIDEBAR_JS}

    loadTags().then(() => loadTimeline());
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/info", response_class=HTMLResponse)
def info_page():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Knowledge Base — Info</title>
  <link rel="stylesheet" href="/style.css">
  <style>
    body { overflow: auto; display: block; }
    .info-page { max-width: 860px; margin: 0 auto; padding: 32px 24px; }

    .section { margin-bottom: 40px; }
    .section h2 {
      font-size: 13px; font-weight: 600; color: #555;
      text-transform: uppercase; letter-spacing: 0.6px;
      margin-bottom: 16px; padding-bottom: 8px;
      border-bottom: 1px solid #eee;
    }

    /* Feature grid */
    .feature-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
    .feature-card {
      background: #fff; border: 1px solid #ddddd8; border-radius: 8px;
      padding: 16px 18px;
    }
    .feature-card h3 { font-size: 13px; font-weight: 600; color: #1a1a1a; margin-bottom: 6px; }
    .feature-card p  { font-size: 12px; color: #777; line-height: 1.6; margin: 0; }

    /* Tools table */
    table { width: 100%; border-collapse: collapse; background: #fff;
            border: 1px solid #ddddd8; border-radius: 8px; overflow: hidden; }
    th, td { padding: 9px 14px; text-align: left; border-bottom: 1px solid #f0f0eb;
              font-size: 13px; }
    th { background: #f8f8f5; font-size: 11px; color: #888;
         text-transform: uppercase; letter-spacing: 0.4px; font-weight: 600; }
    tr:last-child td { border-bottom: none; }
    td:first-child { font-family: monospace; font-size: 12px; color: #4466cc; white-space: nowrap; }
    td.dim { color: #999; font-size: 12px; }

    /* Skill cards */
    .skill-list { display: flex; flex-direction: column; gap: 10px; }
    .skill-card {
      background: #fff; border: 1px solid #ddddd8; border-radius: 8px;
      padding: 14px 18px; display: flex; align-items: baseline; gap: 16px;
    }
    .skill-name {
      font-family: monospace; font-size: 13px; color: #1a1a1a;
      font-weight: 600; white-space: nowrap; min-width: 240px;
    }
    .skill-desc { font-size: 12px; color: #777; line-height: 1.6; }

    /* UI pages table */
    .pages-list { display: flex; flex-direction: column; gap: 8px; }
    .page-row {
      background: #fff; border: 1px solid #ddddd8; border-radius: 8px;
      padding: 12px 18px; display: flex; align-items: baseline; gap: 16px;
    }
    .page-path { font-family: monospace; font-size: 13px; color: #4466cc; min-width: 120px; }
    .page-desc { font-size: 12px; color: #777; }

    /* Tip box */
    .tip {
      background: #f8f8f5; border: 1px solid #ddddd8; border-radius: 8px;
      padding: 14px 18px; font-size: 12px; color: #666; line-height: 1.7;
    }
    .tip code {
      font-family: monospace; background: #eee; padding: 1px 5px;
      border-radius: 3px; font-size: 11px; color: #333;
    }
  </style>
</head>
<body>
  <header>
    <h1>Knowledge Base</h1>
    <span id="node-count" style="color:#999;font-size:13px">Info</span>
    <a href="/" style="margin-left:auto;font-size:13px;color:#777;text-decoration:none;margin-right:16px;">&#8592; Graph</a>
    <a href="/notes" style="font-size:13px;color:#777;text-decoration:none;margin-right:16px;">Notes</a>
    <a href="/stats" style="font-size:13px;color:#777;text-decoration:none;margin-right:16px;">Stats</a>
    <a href="/timeline" style="font-size:13px;color:#777;text-decoration:none;">Timeline</a>
  </header>

  <div class="info-page">

    <!-- Overview -->
    <div class="section">
      <h2>What is this?</h2>
      <div class="feature-grid">
        <div class="feature-card">
          <h3>Persistent memory for Claude</h3>
          <p>A private MCP server that gives Claude a personal knowledge layer across all sessions. Notes and files survive restarts — stored locally in SQLite.</p>
        </div>
        <div class="feature-card">
          <h3>Semantic search</h3>
          <p>Every note is embedded with <code>all-MiniLM-L6-v2</code>. Search by meaning, not just keywords. Cosine similarity ranks results by relevance.</p>
        </div>
        <div class="feature-card">
          <h3>Auto-tagging</h3>
          <p>Store a note with no tags and the server infers them from tag centroid embeddings — based on what you've stored before.</p>
        </div>
        <div class="feature-card">
          <h3>MCP Resources</h3>
          <p>All notes are exposed as <code>notes://&lt;key&gt;</code> MCP Resources. Claude can read them directly into context without a tool call.</p>
        </div>
        <div class="feature-card">
          <h3>Cross-session context</h3>
          <p>Use <code>/learn-store-context</code> to summarize a session, and <code>/learn-load-context</code> to restore it next time — like a personal memory log.</p>
        </div>
        <div class="feature-card">
          <h3>Extensible</h3>
          <p>Drop a <code>.py</code> file in <code>tools/</code> with a <code>register(mcp)</code> function. It's auto-loaded on next server start.</p>
        </div>
      </div>
    </div>

    <!-- MCP Tools -->
    <div class="section">
      <h2>MCP Tools</h2>
      <table>
        <thead><tr><th>Tool</th><th>Description</th></tr></thead>
        <tbody>
          <tr><td>ping()</td><td class="dim">Health check — returns "pong"</td></tr>
          <tr><td>store_note(key, body, tags?)</td><td class="dim">Save or overwrite a note. Auto-tags if no tags provided. Generates and stores embedding.</td></tr>
          <tr><td>get_note(key)</td><td class="dim">Retrieve a note by its exact key.</td></tr>
          <tr><td>search_notes(query, keyword?)</td><td class="dim">Semantic search by default (cosine similarity). Pass <code>keyword=True</code> for LIKE fallback.</td></tr>
          <tr><td>list_notes(tag?)</td><td class="dim">List all notes, optionally filtered by tag.</td></tr>
          <tr><td>delete_note(key)</td><td class="dim">Delete a note and its embedding.</td></tr>
          <tr><td>store_file(name, content_base64, mime_type, tags?)</td><td class="dim">Store a binary file (image, PDF, etc.) by name.</td></tr>
          <tr><td>get_file(name)</td><td class="dim">Retrieve a stored file by name.</td></tr>
          <tr><td>list_files(tag?)</td><td class="dim">List all stored files, optionally filtered by tag.</td></tr>
          <tr><td>delete_file(name)</td><td class="dim">Delete a stored file.</td></tr>
        </tbody>
      </table>
    </div>

    <!-- Skills / Slash Commands -->
    <div class="section">
      <h2>Skills &amp; Slash Commands</h2>
      <p style="font-size:12px;color:#999;margin-bottom:14px;">
        Invoke any skill in Claude Code by typing <code>/skill-name</code>. Skills live in
        <code>.claude/skills/</code> — copy to <code>~/.claude/skills/</code> for global access.
      </p>
      <div class="skill-list">
        <div class="skill-card">
          <span class="skill-name">/learn-store-context</span>
          <span class="skill-desc">Summarize the current conversation and store it as a note tagged <code>conversation</code>. Run at the end of every session to build a memory log.</span>
        </div>
        <div class="skill-card">
          <span class="skill-name">/learn-load-context</span>
          <span class="skill-desc">Load all <code>conversation</code>-tagged notes and restore prior session context. Run at the start of a new session to resume where you left off.</span>
        </div>
        <div class="skill-card">
          <span class="skill-name">/learn-start-ui</span>
          <span class="skill-desc">Start this knowledge base UI via Docker Compose. Opens at <code>http://localhost:8000</code>.</span>
        </div>
        <div class="skill-card">
          <span class="skill-name">/learn-summarize-repo</span>
          <span class="skill-desc">Walk the current repo, read key files, and store a structured architecture summary note under <code>repo-summary/&lt;name&gt;</code>.</span>
        </div>
        <div class="skill-card">
          <span class="skill-name">/learn-integration-documentation</span>
          <span class="skill-desc">Document the full integration surface of the current repo — REST endpoints, events, env vars, auth — and store as <code>integration-docs/&lt;name&gt;</code>.</span>
        </div>
        <div class="skill-card">
          <span class="skill-name">/learn-generate-swagger</span>
          <span class="skill-desc">Read the REST API codebase and generate a valid OpenAPI 3.0.3 YAML spec. Stored as a file under <code>swagger/&lt;name&gt;.yaml</code> with a summary note.</span>
        </div>
      </div>
    </div>

    <!-- UI Pages -->
    <div class="section">
      <h2>UI Pages</h2>
      <div class="pages-list">
        <div class="page-row">
          <span class="page-path"><a href="/" style="color:#4466cc;text-decoration:none;">/</a></span>
          <span class="page-desc">D3 force graph — nodes are notes, edges are cosine similarity links. Node size = body length, colour = primary tag.</span>
        </div>
        <div class="page-row">
          <span class="page-path"><a href="/notes" style="color:#4466cc;text-decoration:none;">/notes</a></span>
          <span class="page-desc">Searchable table of all notes. Toggle between keyword (title/body) and semantic (embedding) search modes.</span>
        </div>
        <div class="page-row">
          <span class="page-path"><a href="/stats" style="color:#4466cc;text-decoration:none;">/stats</a></span>
          <span class="page-desc">Dashboard — note &amp; file counts, total storage, tag breakdown, recently updated notes and files.</span>
        </div>
        <div class="page-row">
          <span class="page-path"><a href="/timeline" style="color:#4466cc;text-decoration:none;">/timeline</a></span>
          <span class="page-desc">Chronological timeline grouped by month. Filter by tag to trace decision history across topics (real-estate, finance, java, etc.).</span>
        </div>
        <div class="page-row">
          <span class="page-path"><a href="/info" style="color:#4466cc;text-decoration:none;">/info</a></span>
          <span class="page-desc">This page — feature reference, tool list, slash commands.</span>
        </div>
      </div>
    </div>

    <!-- Tips -->
    <div class="section">
      <h2>Tips</h2>
      <div class="tip">
        <strong>Key naming convention:</strong> use <code>category/subcategory-title</code> (e.g.
        <code>chatgpt/2025-10-01-auth-design</code>, <code>ideas/feature-name</code>,
        <code>conversation/2026-02-28-120000</code>). Keys are searchable and shown in the graph.<br><br>
        <strong>Tags:</strong> comma-separated string works from Cursor (<code>"java,api,auth"</code>);
        Claude Code can pass a list. Both are normalized by the server.<br><br>
        <strong>Semantic search default:</strong> <code>search_notes("auth microservices")</code> uses
        embedding similarity. Add <code>keyword=True</code> for exact LIKE matching.<br><br>
        <strong>MCP Resources:</strong> Claude can reference <code>notes://your/key</code> directly
        in conversation — no tool call needed — once the resource list is fetched.<br><br>
        <strong>Dynamic tools:</strong> drop a <code>.py</code> file in <code>tools/</code> with
        <code>def register(mcp): ...</code> — picked up automatically on next Claude Code start.
        Prefix with <code>_</code> to disable without deleting.
      </div>
    </div>

  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


# Static files must be mounted last
app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
