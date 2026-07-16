from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from app.core.config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TelegramSessionManager:
    def __init__(self) -> None:
        self._db_path = settings.SESSIONS_DB_PATH

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_auth (
                    chat_id   INTEGER PRIMARY KEY,
                    authed_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_chat_states (
                    chat_id    INTEGER PRIMARY KEY,
                    channel_id TEXT,
                    session_id TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (chat_id) REFERENCES telegram_auth(chat_id) ON DELETE CASCADE
                )
                """
            )
            # Migration: rename project_id -> channel_id if old schema exists
            async with db.execute("PRAGMA table_info(telegram_chat_states)") as cursor:
                tcs_columns = {row[1] for row in await cursor.fetchall()}
            if "project_id" in tcs_columns and "channel_id" not in tcs_columns:
                await db.execute(
                    """
                    CREATE TABLE telegram_chat_states_migrated (
                        chat_id    INTEGER PRIMARY KEY,
                        channel_id TEXT,
                        session_id TEXT,
                        updated_at TEXT,
                        FOREIGN KEY (chat_id) REFERENCES telegram_auth(chat_id) ON DELETE CASCADE
                    )
                    """
                )
                await db.execute(
                    """
                    INSERT INTO telegram_chat_states_migrated(chat_id, channel_id, session_id, updated_at)
                    SELECT chat_id, project_id, session_id, updated_at
                    FROM telegram_chat_states
                    """
                )
                await db.execute("DROP TABLE telegram_chat_states")
                await db.execute("ALTER TABLE telegram_chat_states_migrated RENAME TO telegram_chat_states")
            await db.commit()

    async def is_authed(self, chat_id: int) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT 1 FROM telegram_auth WHERE chat_id=?", (chat_id,)
            ) as cursor:
                row = await cursor.fetchone()
        return row is not None

    async def grant_auth(self, chat_id: int) -> None:
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO telegram_auth(chat_id, authed_at) VALUES (?,?)",
                (chat_id, now),
            )
            await db.commit()

    async def revoke_auth(self, chat_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM telegram_auth WHERE chat_id=?", (chat_id,)
            )
            await db.commit()

    async def get_state(self, chat_id: int) -> dict | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT chat_id, channel_id, session_id, updated_at FROM telegram_chat_states WHERE chat_id=?",
                (chat_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def set_state(self, chat_id: int, channel_id: str, session_id: str) -> None:
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO telegram_chat_states(chat_id, channel_id, session_id, updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    channel_id=excluded.channel_id,
                    session_id=excluded.session_id,
                    updated_at=excluded.updated_at
                """,
                (chat_id, channel_id, session_id, now),
            )
            await db.commit()

    async def clear_session(self, chat_id: int) -> None:
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE telegram_chat_states SET session_id=NULL, updated_at=? WHERE chat_id=?",
                (now, chat_id),
            )
            await db.commit()


telegram_session_manager = TelegramSessionManager()
