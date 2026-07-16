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
                    channel_id TEXT NOT NULL,
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
            # Migration: inspect current columns
            async with db.execute("PRAGMA table_info(sessions)") as cursor:
                columns = {row[1] for row in await cursor.fetchall()}

            # Migration: add channel_id column if it was created without it
            if "channel_id" not in columns:
                await db.execute("ALTER TABLE sessions ADD COLUMN channel_id TEXT NOT NULL DEFAULT ''")

            # Migration: drop legacy project_id column (NOT NULL constraint breaks inserts)
            if "project_id" in columns:
                await db.execute(
                    """
                    CREATE TABLE sessions_migrated (
                        id         TEXT PRIMARY KEY,
                        channel_id TEXT NOT NULL,
                        title      TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                await db.execute(
                    """
                    INSERT INTO sessions_migrated(id, channel_id, title, created_at, updated_at)
                    SELECT id,
                           CASE WHEN channel_id IS NOT NULL AND channel_id != '' THEN channel_id ELSE project_id END,
                           title, created_at, updated_at
                    FROM sessions
                    """
                )
                await db.execute("DROP TABLE sessions")
                await db.execute("ALTER TABLE sessions_migrated RENAME TO sessions")

            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_channel ON sessions(channel_id, updated_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp ASC)"
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def create_session(self, channel_id: str) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO sessions(id, channel_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
                (session_id, channel_id, None, now, now),
            )
            await db.commit()
        return {"id": session_id, "channel_id": channel_id, "title": None, "created_at": now, "updated_at": now}

    async def list_sessions(self, channel_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, channel_id, title, created_at, updated_at FROM sessions WHERE channel_id=? ORDER BY updated_at DESC",
                (channel_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, channel_id, title, created_at, updated_at FROM sessions WHERE id=?",
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
