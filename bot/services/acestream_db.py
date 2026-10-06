import sqlite3
from datetime import datetime, timezone

_db_path: str = ""


def init_db(path: str) -> None:
    global _db_path
    _db_path = path
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS channels "
            "(name TEXT PRIMARY KEY, content_id TEXT NOT NULL, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )


def add_channel(name: str, content_id: str) -> None:
    if content_id.startswith("acestream://"):
        content_id = content_id[len("acestream://"):]
    with sqlite3.connect(_db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO channels (name, content_id, created_at) VALUES (?, ?, ?)",
            (name, content_id, datetime.now(timezone.utc).isoformat()),
        )


def remove_channel(name: str) -> bool:
    with sqlite3.connect(_db_path) as conn:
        cursor = conn.execute("DELETE FROM channels WHERE name = ?", (name,))
    return cursor.rowcount > 0


def list_channels() -> list[dict]:
    with sqlite3.connect(_db_path) as conn:
        rows = conn.execute(
            "SELECT name, content_id, created_at FROM channels ORDER BY name"
        ).fetchall()
    return [{"name": r[0], "content_id": r[1], "created_at": r[2]} for r in rows]
