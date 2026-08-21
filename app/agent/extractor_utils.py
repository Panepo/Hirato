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


def _normalize_extracted_summary(raw: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if isinstance(raw, str):
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            pass
    elif isinstance(raw, dict):
        payload = raw

    payload.setdefault("title", "Progress report")
    payload.setdefault("week", date.today().isoformat())
    payload["tags"] = _normalize_tags(payload.get("tags", ["report", "progress"]))
    if not payload["tags"]:
        payload["tags"] = ["report", "progress"]
    return payload


def _render_summary_text(extracted: dict[str, Any]) -> str:
    sections: list[str] = []
    for key, label in [
        ("accomplishments", "Accomplishments"),
        ("blockers", "Blockers"),
        ("next_steps", "Next steps"),
    ]:
        values = extracted.get(key, [])
        if isinstance(values, str):
            values = [values]
        if not values:
            continue
        lines = []
        for item in values:
            text = str(item).strip()
            if text:
                lines.append(f"- {text}")
        if lines:
            sections.append(f"{label}:\n" + "\n".join(lines))
    if sections:
        return "\n\n".join(sections)
    return str(extracted.get("summary") or extracted.get("content") or extracted.get("title", "")).strip()
