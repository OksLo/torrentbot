import json
import sqlite3

from google.genai import types

_db_path: str = ""


def init_db(path: str) -> None:
    global _db_path
    _db_path = path
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_history "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "chat_id INTEGER NOT NULL, role TEXT NOT NULL, "
            "parts TEXT NOT NULL, ts DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )


def _parts_to_json(parts) -> str:
    data = []
    for p in parts:
        if isinstance(p, dict):
            data.append(p)
            continue
        if p.text is not None:
            data.append({"text": p.text})
        elif p.function_call is not None:
            fc = p.function_call
            data.append({"function_call": {"name": fc.name, "args": dict(fc.args)}})
        elif p.function_response is not None:
            fr = p.function_response
            data.append({"function_response": {"name": fr.name, "response": dict(fr.response)}})
    return json.dumps(data)


def _json_to_parts(parts_json: str) -> list:
    parts = []
    for p in json.loads(parts_json):
        if "text" in p:
            parts.append(types.Part(text=p["text"]))
        elif "function_call" in p:
            fc = p["function_call"]
            parts.append(types.Part(function_call=types.FunctionCall(name=fc["name"], args=fc["args"])))
        elif "function_response" in p:
            fr = p["function_response"]
            parts.append(types.Part(function_response=types.FunctionResponse(name=fr["name"], response=fr["response"])))
    return parts


def load_history(chat_id: int) -> list:
    if not _db_path:
        return []
    try:
        with sqlite3.connect(_db_path) as conn:
            rows = conn.execute(
                "SELECT role, parts FROM chat_history WHERE chat_id = ? ORDER BY id DESC LIMIT 40",
                (chat_id,),
            ).fetchall()
        return [types.Content(role=row[0], parts=_json_to_parts(row[1])) for row in reversed(rows)]
    except Exception:
        return []


def append_turn(chat_id: int, role: str, parts) -> None:
    with sqlite3.connect(_db_path) as conn:
        conn.execute(
            "INSERT INTO chat_history (chat_id, role, parts) VALUES (?, ?, ?)",
            (chat_id, role, _parts_to_json(parts)),
        )
        conn.execute(
            "DELETE FROM chat_history WHERE chat_id = ? AND id NOT IN "
            "(SELECT id FROM chat_history WHERE chat_id = ? ORDER BY id DESC LIMIT 40)",
            (chat_id, chat_id),
        )


def clear_history(chat_id: int) -> None:
    with sqlite3.connect(_db_path) as conn:
        conn.execute("DELETE FROM chat_history WHERE chat_id = ?", (chat_id,))
