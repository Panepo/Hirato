from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.core.config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteSessionStore:
    def __init__(self) -> None:
        self._db_path = settings.SESSIONS_DB_PATH

    async def init_db(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id         TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title      TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id         TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role       TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    timestamp  TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id, updated_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp ASC)"
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def create_session(self, project_id: str) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO sessions(id, project_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
                (session_id, project_id, None, now, now),
            )
            await db.commit()
        return {"id": session_id, "project_id": project_id, "title": None, "created_at": now, "updated_at": now}

    async def list_sessions(self, project_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, project_id, title, created_at, updated_at FROM sessions WHERE project_id=? ORDER BY updated_at DESC",
                (project_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, project_id, title, created_at, updated_at FROM sessions WHERE id=?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return None
            session = dict(row)
            async with db.execute(
                "SELECT id, session_id, role, content, timestamp FROM messages WHERE session_id=? ORDER BY timestamp ASC",
                (session_id,),
            ) as cursor:
                msgs = await cursor.fetchall()
        session["messages"] = [dict(m) for m in msgs]
        return session

    async def delete_session(self, session_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            await db.commit()
        return cursor.rowcount > 0

    async def update_title(self, session_id: str, title: str) -> None:
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
                (title, now, session_id),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def add_message(self, session_id: str, role: str, content: str) -> dict[str, Any]:
        msg_id = str(uuid.uuid4())
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO messages(id, session_id, role, content, timestamp) VALUES (?,?,?,?,?)",
                (msg_id, session_id, role, content, now),
            )
            await db.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (now, session_id),
            )
            await db.commit()
        return {"id": msg_id, "session_id": session_id, "role": role, "content": content, "timestamp": now}

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, session_id, role, content, timestamp FROM messages WHERE session_id=? ORDER BY timestamp ASC",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(r) for r in rows]


sessions_store = SQLiteSessionStore()
