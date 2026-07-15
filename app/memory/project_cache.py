from __future__ import annotations

import asyncio
import difflib
import time
from typing import Any

import httpx

from app.core.config import settings

_TTL = 300  # seconds — refresh project list every 5 minutes


class _ProjectCache:
    def __init__(self) -> None:
        self._projects: list[dict[str, str]] = []
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        if not settings.SHIRATSUYU_BEARER:
            return
        url = settings.SHIRATSUYU_URL.rstrip("/") + "/project/"
        headers = {"Authorization": f"Bearer {settings.SHIRATSUYU_BEARER}"}
        try:
            async with httpx.AsyncClient(verify=False) as client:
                r = await client.get(url, headers=headers, timeout=15.0)
                r.raise_for_status()
                raw: list[dict[str, Any]] = r.json()
            self._projects = [
                {
                    "code": str(p.get("code", "") or ""),
                    "name": str(p.get("name", "") or ""),
                }
                for p in raw
            ]
        except Exception:
            pass  # keep stale cache on error; don't crash the agent

    async def _ensure_fresh(self) -> None:
        if time.monotonic() - self._fetched_at < _TTL:
            return
        async with self._lock:
            # Double-checked locking
            if time.monotonic() - self._fetched_at < _TTL:
                return
            await self._refresh()
            self._fetched_at = time.monotonic()

    async def resolve(self, hint: str) -> dict[str, str] | None:
        """Fuzzy-match *hint* against cached project codes and names.

        Returns ``{"code": ..., "name": ...}`` when a confident match is found,
        or ``None`` when nothing passes the 0.75 similarity threshold.
        """
        if not hint:
            return None
        await self._ensure_fresh()
        query = hint.strip().lower()
        best_score = 0.0
        best: dict[str, str] | None = None
        for proj in self._projects:
            code_lower = proj["code"].lower()
            name_lower = proj["name"].lower()
            combined = f"{code_lower} {name_lower}"

            # Exact / substring match wins immediately
            if query == code_lower or query == name_lower or query in combined:
                score = 1.0
            else:
                score = max(
                    difflib.SequenceMatcher(None, query, code_lower).ratio(),
                    difflib.SequenceMatcher(None, query, name_lower).ratio(),
                    difflib.SequenceMatcher(None, query, combined).ratio(),
                )

            if score > best_score:
                best_score = score
                best = proj

        if best and best_score >= 0.75:
            return best
        return None

    async def all_projects(self) -> list[dict[str, str]]:
        """Return all cached projects (code + name)."""
        await self._ensure_fresh()
        return list(self._projects)

    def invalidate(self) -> None:
        """Force a refresh on the next call (e.g. after creating a new project)."""
        self._fetched_at = 0.0


project_cache = _ProjectCache()
