from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.core.config import settings

_VALID_ROLES = {"viewer", "writer", "manager"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthStore:
    def __init__(self) -> None:
        self._db_path = settings.AUTH_DB_PATH

    async def init_db(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id         TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    usergroups TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS channel_settings (
                    channel_id TEXT PRIMARY KEY,
                    is_open    INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS channel_roles (
                    channel_id TEXT NOT NULL,
                    user_id    TEXT NOT NULL,
                    role       TEXT NOT NULL CHECK (role IN ('viewer','writer','manager')),
                    name       TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (channel_id, user_id)
                )
                """
            )
            async with db.execute("PRAGMA table_info(channel_roles)") as cursor:
                columns = {row[1] async for row in cursor}
            if "name" not in columns:
                await db.execute("ALTER TABLE channel_roles ADD COLUMN name TEXT NOT NULL DEFAULT ''")
            await db.commit()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    async def upsert_user(self, user_id: str, name: str, usergroups: list[int]) -> None:
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO users(id, name, usergroups, updated_at) VALUES (?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, usergroups=excluded.usergroups, updated_at=excluded.updated_at
                """,
                (user_id, name, json.dumps(usergroups), now),
            )
            await db.commit()

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, usergroups, updated_at FROM users WHERE id=?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        user = dict(row)
        user["usergroups"] = json.loads(user["usergroups"])
        return user

    # ------------------------------------------------------------------
    # Channel settings (open/closed)
    # ------------------------------------------------------------------

    async def ensure_channel_settings_row(self, channel_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO channel_settings(channel_id, is_open, created_at) VALUES (?,1,?)",
                (channel_id, _now_iso()),
            )
            await db.commit()

    async def delete_channel_settings(self, channel_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM channel_settings WHERE channel_id=?", (channel_id,))
            await db.execute("DELETE FROM channel_roles WHERE channel_id=?", (channel_id,))
            await db.commit()

    async def is_channel_open(self, channel_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT is_open FROM channel_settings WHERE channel_id=?", (channel_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return True  # default open if no row exists yet
        return bool(row[0])

    async def set_channel_open(self, channel_id: str, is_open: bool) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO channel_settings(channel_id, is_open, created_at) VALUES (?,?,?)
                ON CONFLICT(channel_id) DO UPDATE SET is_open=excluded.is_open
                """,
                (channel_id, int(is_open), _now_iso()),
            )
            await db.commit()

    async def list_open_channel_ids(self) -> set[str]:
        """Channel ids explicitly marked open. Callers must treat missing rows as open too."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT channel_id FROM channel_settings WHERE is_open=1"
            ) as cursor:
                rows = await cursor.fetchall()
        return {r[0] for r in rows}

    async def list_closed_channel_ids(self) -> set[str]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT channel_id FROM channel_settings WHERE is_open=0"
            ) as cursor:
                rows = await cursor.fetchall()
        return {r[0] for r in rows}

    # ------------------------------------------------------------------
    # Channel roles
    # ------------------------------------------------------------------

    async def get_channel_role(self, channel_id: str, user_id: str) -> str | None:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT role FROM channel_roles WHERE channel_id=? AND user_id=?",
                (channel_id, user_id),
            ) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else None

    async def set_channel_role(self, channel_id: str, user_id: str, role: str, name: str = "") -> None:
        if role not in _VALID_ROLES:
            raise ValueError(f"invalid role: {role}")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO channel_roles(channel_id, user_id, role, name) VALUES (?,?,?,?)
                ON CONFLICT(channel_id, user_id) DO UPDATE SET role=excluded.role, name=excluded.name
                """,
                (channel_id, user_id, role, name),
            )
            await db.commit()

    async def remove_channel_role(self, channel_id: str, user_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM channel_roles WHERE channel_id=? AND user_id=?",
                (channel_id, user_id),
            )
            await db.commit()

    async def list_channel_roles(self, channel_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT channel_id, user_id, role, name FROM channel_roles WHERE channel_id=?",
                (channel_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(r) for r in rows]


auth_store = AuthStore()
