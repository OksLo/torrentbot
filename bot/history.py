import sqlite3

from google.genai import types
from pydantic import TypeAdapter

from config import settings

_parts = TypeAdapter(list[types.Part])


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(settings.history_db_path)


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_history "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "chat_id INTEGER NOT NULL, role TEXT NOT NULL, "
            "parts TEXT NOT NULL, ts DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )


def load(chat_id: int) -> list[types.Content]:
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT role, parts FROM chat_history WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (chat_id, settings.history_limit),
            ).fetchall()
        hist = [types.Content(role=role, parts=_parts.validate_json(parts)) for role, parts in reversed(rows)]
    except Exception:
        return []
    # trim leading orphaned turns: history_limit truncation can cut the function_call
    # that a leading function_response belongs to; Gemini requires them to be adjacent
    while hist and not (hist[0].role == "user" and any(p.text is not None for p in hist[0].parts)):
        hist.pop(0)
    # trim trailing incomplete tool-call cycles (e.g. the tool-call limit was reached)
    while hist and any(p.function_call or p.function_response for p in hist[-1].parts):
        hist.pop()
    return hist


def save(chat_id: int, turns: list[types.Content]) -> None:
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO chat_history (chat_id, role, parts) VALUES (?, ?, ?)",
            [(chat_id, turn.role, _parts.dump_json(turn.parts or [], exclude_none=True).decode()) for turn in turns],
        )
        conn.execute(
            "DELETE FROM chat_history WHERE chat_id = ? AND id NOT IN "
            "(SELECT id FROM chat_history WHERE chat_id = ? ORDER BY id DESC LIMIT ?)",
            (chat_id, chat_id, settings.history_limit),
        )
