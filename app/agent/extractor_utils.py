from __future__ import annotations

import json
from typing import Any, AsyncGenerator
import re
from datetime import date

def _normalize_tags(tags: Any) -> list[str]:
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            if isinstance(parsed, list):
                tags = parsed
            else:
                tags = [parsed]
        except json.JSONDecodeError:
            tags = [part.strip() for part in tags.split(',') if part.strip()]
    elif not isinstance(tags, list):
        tags = [tags] if tags is not None else []

    normalized = []
    for tag in tags:
        text = str(tag).strip()
        if text:
            normalized.append(text)
    return normalized[:5]


def _normalize_extracted_chunks(raw: Any, fallback_content: str = "") -> list[dict[str, Any]]:
    """Parse the extractor LLM output into a list of raw (non-summarized) per-week chunks."""
    payload: Any = None
    if isinstance(raw, str):
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            payload = None
    elif isinstance(raw, (list, dict)):
        payload = raw

    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        payload = []

    today = date.today().isoformat()
    chunks: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        week = str(item.get("week") or "").strip()
        if not week or week.lower() in ("unspecified", "unknown", "n/a"):
            week = today
        title = str(item.get("title") or "Progress report").strip() or "Progress report"
        tags = _normalize_tags(item.get("tags", ["report", "progress"]))
        if not tags:
            tags = ["report", "progress"]
        content = str(item.get("content") or "").strip()
        if content:
            chunks.append({"week": week, "title": title, "tags": tags, "content": content})

    # If the LLM produced nothing usable, fall back to a single chunk with the raw input text.
    if not chunks and fallback_content.strip():
        chunks.append({
            "week": today,
            "title": "Progress report",
            "tags": ["report", "progress"],
            "content": fallback_content.strip(),
        })
    return chunks
