"""SQLite helpers: schema initialisation and connection factory."""

import sqlite3
from contextlib import contextmanager
from typing import Generator

from config import DB_PATH, FILES_DIR


def init() -> None:
    """Create directories and tables on first run (idempotent)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)

    with _raw_connect() as conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS notes (
                key        TEXT PRIMARY KEY,
                body       TEXT NOT NULL,
                tags       TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS files (
                name       TEXT PRIMARY KEY,
                mime_type  TEXT NOT NULL,
                tags       TEXT NOT NULL DEFAULT '[]',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS note_embeddings (
                key       TEXT PRIMARY KEY,
                embedding BLOB NOT NULL
            );
        """)


def _raw_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connect() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager that yields a connection, commits on success,
    rolls back on exception, and always closes.

    Usage::

        with db.connect() as conn:
            conn.execute("INSERT INTO notes ...")
    """
    conn = _raw_connect()
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
