"""
Import ChatGPT conversation history into the MCP knowledge base.

Reads all conversations-00N.json files from data/temp/, extracts meaningful
content, and stores each conversation as a note in SQLite with auto-tagging.

Usage:
    python3 scripts/import_chatgpt_history.py [--dry-run] [--min-chars 200]
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

# Make sure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import db
from modules.embeddings import AUTO_TAG_SKIP, encode, suggest_tags, to_blob
from modules.knowledge import _compute_tag_centroids, _normalize_tags

TEMP_DIR = Path(__file__).parent.parent / "data" / "temp"
DEFAULT_MIN_CHARS = 300  # skip conversations with very little content


# ── Topic classifier (keyword-based, supplements auto-tagging) ───────────────

TOPIC_KEYWORDS: list[tuple[list[str], str]] = [
    (["incident", "outage", "postmortem", "root cause", "pagerduty", "alert", "slo", "sla", "on-call"], "incident"),
    (["adr", "architecture decision", "decision record"], "adr"),
    (["rfc", "request for comment", "proposal", "design doc"], "rfc"),
    (["kubernetes", "k8s", "helm", "docker", "container", "pod", "deployment", "ingress"], "kubernetes"),
    (["terraform", "infra", "infrastructure", "aws", "gcp", "azure", "cloud", "ec2", "s3", "iam"], "infrastructure"),
    (["python", "django", "fastapi", "flask"], "python"),
    (["java", "spring", "springboot", "maven", "gradle", "jackson", "jvm"], "java"),
    (["javascript", "typescript", "react", "vue", "angular", "node", "nextjs", "webpack"], "frontend"),
    (["sql", "postgres", "mysql", "sqlite", "database", "query", "migration", "orm", "hibernate"], "database"),
    (["git", "github", "gitlab", "ci", "cd", "pipeline", "github actions", "jenkins"], "devops"),
    (["api", "rest", "graphql", "grpc", "endpoint", "swagger", "openapi"], "api"),
    (["security", "auth", "oauth", "jwt", "ssl", "tls", "vulnerability", "cve"], "security"),
    (["redis", "kafka", "rabbitmq", "queue", "pubsub", "message broker"], "messaging"),
    (["machine learning", "ml", "llm", "gpt", "embedding", "vector", "ai ", " ai,", "model training"], "ml"),
    (["invest", "stock", "etf", "crypto", "trading", "portfolio", "dividend", "finance"], "finance"),
    (["dubai", "uae", "apartment", "rent", "property", "real estate", "jlt", "marina"], "real-estate"),
    (["salary", "job", "interview", "resume", "cv", "career", "offer letter"], "career"),
    (["test", "unit test", "integration test", "jest", "pytest", "mock", "stub"], "testing"),
    (["regex", "algorithm", "data structure", "leetcode", "complexity"], "algorithms"),
    (["bash", "shell", "linux", "unix", "script", "cron", "systemd"], "linux"),
]


def classify_topics(title: str, text: str) -> list[str]:
    combined = (title + " " + text).lower()
    tags = []
    for keywords, tag in TOPIC_KEYWORDS:
        if any(kw in combined for kw in keywords):
            tags.append(tag)
    return tags


# ── Conversation extraction ──────────────────────────────────────────────────

def walk_messages(mapping: dict, node_id: str, visited: set) -> list[tuple[str, str]]:
    """Recursively walk the conversation tree, returning (role, text) pairs."""
    if node_id in visited or node_id not in mapping:
        return []
    visited.add(node_id)
    node = mapping[node_id]
    results = []

    msg = node.get("message")
    if msg:
        role = msg.get("author", {}).get("role", "")
        content = msg.get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        text = "\n".join(str(p) for p in parts if isinstance(p, str) and p.strip())
        if text and role in ("user", "assistant"):
            results.append((role, text))

    for child in node.get("children", []):
        results.extend(walk_messages(mapping, child, visited))

    return results


def extract_conversation(conv: dict) -> tuple[str, str, list[tuple[str, str]]]:
    """Return (title, iso_date, [(role, text), ...])."""
    title = conv.get("title") or "Untitled"
    ts = conv.get("create_time") or conv.get("update_time") or 0
    iso_date = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "unknown"

    mapping = conv.get("mapping", {})
    # Find root node (no parent, or parent not in mapping)
    root = None
    for nid, node in mapping.items():
        p = node.get("parent")
        if not p or p not in mapping:
            root = nid
            break

    messages = walk_messages(mapping, root, set()) if root else []
    return title, iso_date, messages


def build_note_body(title: str, iso_date: str, messages: list[tuple[str, str]]) -> str:
    lines = [f"# {title}", f"*ChatGPT conversation — {iso_date}*", ""]
    for role, text in messages:
        label = "**User:**" if role == "user" else "**Assistant:**"
        # Trim very long assistant replies to keep notes scannable
        snippet = text if role == "user" else text[:1200] + (" …" if len(text) > 1200 else "")
        lines.append(f"{label}\n{snippet}\n")
    return "\n".join(lines)


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:80]


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Parse only, don't write to DB")
    parser.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS)
    parser.add_argument("--file", type=str, default=None, help="Process single file only")
    args = parser.parse_args()

    # Collect JSON files
    if args.file:
        files = [TEMP_DIR / args.file]
    else:
        files = sorted(TEMP_DIR.glob("conversations-*.json"))

    print(f"Processing {len(files)} file(s) from {TEMP_DIR}")
    if args.dry_run:
        print("DRY RUN — nothing will be written\n")

    db.init()

    # Pre-compute tag centroids once for auto-tagging
    centroids = {} if args.dry_run else _compute_tag_centroids()

    # Track existing keys to avoid duplicates
    if not args.dry_run:
        with db.connect() as conn:
            existing = {r[0] for r in conn.execute("SELECT key FROM notes").fetchall()}
    else:
        existing = set()

    total = stored = skipped_short = skipped_exists = 0

    for fpath in files:
        print(f"\n── {fpath.name} ──")
        with open(fpath) as f:
            conversations = json.load(f)

        for conv in conversations:
            total += 1
            title, iso_date, messages = extract_conversation(conv)

            # Build full text for length check and classification
            body = build_note_body(title, iso_date, messages)
            content_text = " ".join(t for _, t in messages)

            if len(content_text) < args.min_chars:
                skipped_short += 1
                continue

            key = f"chatgpt/{iso_date}-{slugify(title)}"

            if key in existing and not args.dry_run:
                # Re-run to fix created_at; embeddings already exist so skip re-encoding
                with db.connect() as conn:
                    conn.execute(
                        "UPDATE notes SET created_at = ?, updated_at = ? WHERE key = ?",
                        (iso_date + " 00:00:00", iso_date + " 00:00:00", key),
                    )
                skipped_exists += 1
                continue

            # Tags: keyword classifier + auto-tag from centroids
            keyword_tags = classify_topics(title, content_text)
            keyword_tags.append("chatgpt")

            if not args.dry_run:
                vec = encode(body)
                auto_tags = suggest_tags(vec, centroids)
                # Merge, deduplicate, skip generic
                all_tags = list(dict.fromkeys(keyword_tags + [
                    t for t in auto_tags if t not in AUTO_TAG_SKIP and t not in keyword_tags
                ]))
                tags_json = json.dumps(all_tags)
                blob = to_blob(vec)

                with db.connect() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO notes (key, body, tags, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (key, body, tags_json, iso_date + " 00:00:00", iso_date + " 00:00:00"),
                    )
                    conn.execute(
                        """INSERT OR REPLACE INTO note_embeddings (key, embedding)
                           VALUES (?, ?)""",
                        (key, blob),
                    )

                existing.add(key)
                stored += 1
                tag_str = ", ".join(all_tags[:5])
                print(f"  [+] {key}  [{tag_str}]")
            else:
                keyword_tags_str = ", ".join(keyword_tags[:5])
                print(f"  [dry] {key}  [{keyword_tags_str}]  ({len(content_text)} chars)")
                stored += 1

    print(f"\n{'='*60}")
    print(f"Total conversations : {total}")
    print(f"Stored              : {stored}")
    print(f"Skipped (too short) : {skipped_short}")
    print(f"Skipped (duplicate) : {skipped_exists}")


if __name__ == "__main__":
    main()
