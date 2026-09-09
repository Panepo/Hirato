from __future__ import annotations

import base64
import re
from typing import Any

from fastapi import HTTPException
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.agent.chat_service import run_chat_turn, run_regenerate_turn
from app.core.auth import AuthUser, is_site_admin, is_site_manager, perform_login, shiratsuyu_query_user
from app.core.channel_acl import get_effective_role, require_channel_manage, require_channel_view, require_channel_write
from app.mcp.session import mcp_sessions
from app.memory.auth_store import auth_store
from app.memory.sessions import sessions_store
from app.memory.store import vector_store
from app.services.document_import import import_document_bytes, import_embedded_json_bytes

mcp = MCPServer("Hirato Secretary")


def _session_key(ctx: Context) -> int:
    return id(ctx.session)


def _require_user(ctx: Context) -> AuthUser:
    user = mcp_sessions.get(_session_key(ctx))
    if user is None:
        raise ToolError("Not logged in — call the login tool first.")
    return user


def _detail(exc: Exception) -> str:
    """Prefer HTTPException.detail (human-readable) over the generic str(exc) repr."""
    detail = getattr(exc, "detail", None)
    return str(detail) if detail is not None else str(exc)


async def _require_view(channel_id: str, user: AuthUser) -> None:
    try:
        await require_channel_view(channel_id, user)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc


async def _require_write(channel_id: str, user: AuthUser) -> None:
    try:
        await require_channel_write(channel_id, user)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc


async def _require_manage(channel_id: str, user: AuthUser) -> None:
    try:
        await require_channel_manage(channel_id, user)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc


# ---------------------------------------------------------------------------
# Auth tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def login(email: str, password: str, ctx: Context) -> dict:
    """Log in with Hirato credentials. Must be called before any other tool."""
    try:
        _raw, user = await perform_login(email, password)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc
    mcp_sessions.login(_session_key(ctx), user)
    return {"id": user.id, "name": user.name, "usergroups": user.usergroups}


@mcp.tool()
async def whoami(ctx: Context) -> dict:
    """Return the currently logged-in user's identity and site-level roles."""
    user = _require_user(ctx)
    return {
        "id": user.id,
        "name": user.name,
        "usergroups": user.usergroups,
        "is_site_admin": is_site_admin(user),
        "is_site_manager": is_site_manager(user),
    }


@mcp.tool()
async def logout(ctx: Context) -> dict:
    """Forget the logged-in user for this MCP connection."""
    mcp_sessions.logout(_session_key(ctx))
    return {"ok": True}


@mcp.tool()
async def query_user(identifier: str, ctx: Context) -> list[dict]:
    """Look up a Shiratsuyu employee by identifier (name/email/empno)."""
    _require_user(ctx)
    try:
        return await shiratsuyu_query_user(identifier)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc


# ---------------------------------------------------------------------------
# Channel tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_channels(ctx: Context) -> list[dict[str, Any]]:
    """List channels visible to the logged-in user (open channels, plus any the user has a role in)."""
    user = _require_user(ctx)
    result = []
    for channel_id in vector_store.list_channels():
        is_open = await auth_store.is_channel_open(channel_id)
        role = await get_effective_role(channel_id, user)
        if is_open or role is not None:
            result.append({"channel_id": channel_id, "is_open": is_open, "role": role})
    return result


@mcp.tool()
async def create_channel(name: str, ctx: Context, description: str = "") -> dict[str, str]:
    """Create a new channel. Requires site admin or site manager access."""
    user = _require_user(ctx)
    if not is_site_admin(user) and not is_site_manager(user):
        raise ToolError("Site admin or site manager access required")

    channel_id = re.sub(r"[^a-zA-Z0-9._-]", "_", name.strip())
    channel_id = re.sub(r"_+", "_", channel_id).strip("_.-")
    if len(channel_id) < 3:
        raise ToolError("Channel name too short or contains only invalid characters (min 3 alphanumeric).")

    vector_store.get_or_create_collection(channel_id)
    await auth_store.ensure_channel_settings_row(channel_id)
    return {"channel_id": channel_id, "description": description}


@mcp.tool()
async def delete_channel(channel_id: str, ctx: Context) -> dict[str, bool]:
    """Permanently delete a channel, its sessions, and its settings. Requires site admin access."""
    user = _require_user(ctx)
    if not is_site_admin(user):
        raise ToolError("Site admin access required")
    try:
        vector_store.delete_channel(channel_id)
        await sessions_store.delete_channel_sessions(channel_id)
        await auth_store.delete_channel_settings(channel_id)
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    return {"ok": True}


@mcp.tool()
async def update_channel_settings(channel_id: str, is_open: bool, ctx: Context) -> dict[str, Any]:
    """Set whether a channel is open (visible to everyone) or closed (role-gated). Requires manage access."""
    user = _require_user(ctx)
    await _require_manage(channel_id, user)
    await auth_store.set_channel_open(channel_id, is_open)
    return {"channel_id": channel_id, "is_open": is_open}


@mcp.tool()
async def list_channel_roles(channel_id: str, ctx: Context) -> list[dict[str, Any]]:
    """List all explicit role assignments for a channel. Requires manage access."""
    user = _require_user(ctx)
    await _require_manage(channel_id, user)
    return await auth_store.list_channel_roles(channel_id)


@mcp.tool()
async def add_manager(channel_id: str, user_id: str, ctx: Context, name: str = "") -> dict[str, bool]:
    """Assign the 'manager' role for a channel to a user. Requires site admin access."""
    caller = _require_user(ctx)
    if not is_site_admin(caller):
        raise ToolError("Site admin access required")
    await auth_store.set_channel_role(channel_id, user_id, "manager", name)
    return {"ok": True}


@mcp.tool()
async def remove_manager(channel_id: str, user_id: str, ctx: Context) -> dict[str, bool]:
    """Remove a user's role assignment for a channel. Requires site admin access."""
    caller = _require_user(ctx)
    if not is_site_admin(caller):
        raise ToolError("Site admin access required")
    await auth_store.remove_channel_role(channel_id, user_id)
    return {"ok": True}


@mcp.tool()
async def add_writer(channel_id: str, user_id: str, ctx: Context, name: str = "") -> dict[str, bool]:
    """Assign the 'writer' role for a channel to a user. Requires manage access."""
    caller = _require_user(ctx)
    await _require_manage(channel_id, caller)
    await auth_store.set_channel_role(channel_id, user_id, "writer", name)
    return {"ok": True}


@mcp.tool()
async def remove_writer(channel_id: str, user_id: str, ctx: Context) -> dict[str, bool]:
    """Remove a user's role assignment for a channel. Requires manage access."""
    caller = _require_user(ctx)
    await _require_manage(channel_id, caller)
    await auth_store.remove_channel_role(channel_id, user_id)
    return {"ok": True}


@mcp.tool()
async def add_viewer(channel_id: str, user_id: str, ctx: Context, name: str = "") -> dict[str, bool]:
    """Assign the 'viewer' role for a channel to a user. Requires manage access."""
    caller = _require_user(ctx)
    await _require_manage(channel_id, caller)
    await auth_store.set_channel_role(channel_id, user_id, "viewer", name)
    return {"ok": True}


@mcp.tool()
async def remove_viewer(channel_id: str, user_id: str, ctx: Context) -> dict[str, bool]:
    """Remove a user's role assignment for a channel. Requires manage access."""
    caller = _require_user(ctx)
    await _require_manage(channel_id, caller)
    await auth_store.remove_channel_role(channel_id, user_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_memories(channel_id: str, ctx: Context) -> list[dict]:
    """List all memories (documents) stored in a channel. Requires write access."""
    user = _require_user(ctx)
    await _require_write(channel_id, user)
    return vector_store.list_memories(channel_id)


@mcp.tool()
async def delete_memories(channel_id: str, memory_ids: list[str], ctx: Context) -> dict[str, int]:
    """Bulk-delete memories from a channel by id. Requires write access."""
    user = _require_user(ctx)
    await _require_write(channel_id, user)
    deleted = len([memory_id for memory_id in memory_ids if str(memory_id).strip()])
    if deleted == 0:
        return {"deleted": 0, "ok": True}
    vector_store.delete_memories(channel_id, memory_ids)
    return {"deleted": deleted, "ok": True}


@mcp.tool()
async def delete_memory(channel_id: str, memory_id: str, ctx: Context) -> dict[str, bool]:
    """Delete a single memory from a channel by id. Requires write access."""
    user = _require_user(ctx)
    await _require_write(channel_id, user)
    vector_store.delete_memory(channel_id, memory_id)
    return {"ok": True}


@mcp.tool()
async def update_memory(channel_id: str, memory_id: str, content: str, ctx: Context) -> dict[str, bool]:
    """Replace the content of a single memory (re-embeds the new text). Requires write access."""
    user = _require_user(ctx)
    await _require_write(channel_id, user)
    vector_store.update_memory(channel_id, memory_id, content)
    return {"ok": True}


@mcp.tool()
async def import_memories(channel_id: str, memories: list[dict], ctx: Context) -> dict[str, int]:
    """Bulk-import memories (browser-export format) into a channel. Requires write access."""
    user = _require_user(ctx)
    await _require_write(channel_id, user)
    return vector_store.import_memories(channel_id, memories)


@mcp.tool()
async def import_embedded_json(channel_id: str, filename: str, content_base64: str, ctx: Context) -> dict[str, int]:
    """Import a pre-chunked JSON document (base64-encoded) into a channel. Requires write access."""
    user = _require_user(ctx)
    await _require_write(channel_id, user)
    if not filename.endswith(".json"):
        raise ToolError("Only .json files are accepted.")
    try:
        content = base64.b64decode(content_base64)
    except Exception as exc:
        raise ToolError(f"Invalid base64 content: {exc}") from exc
    return import_embedded_json_bytes(channel_id, content)


@mcp.tool()
async def import_documents(channel_id: str, files: list[dict], ctx: Context) -> dict[str, Any]:
    """Import one or more documents into a channel via the indexer.

    Each item in `files` is {"filename": str, "content_base64": str}. Requires write access.
    """
    user = _require_user(ctx)
    await _require_write(channel_id, user)

    imported_count = 0
    skipped_count = 0
    failed_files: list[dict[str, str]] = []

    for file in files:
        filename = file.get("filename", "")
        if not filename:
            continue
        try:
            content = base64.b64decode(file["content_base64"])
            result = import_document_bytes(channel_id, filename, content)
            imported_count += result.get("imported", 0)
            skipped_count += result.get("skipped", 0)
        except Exception as e:
            failed_files.append({"file": filename, "error": str(e)})

    return {
        "imported": imported_count,
        "skipped": skipped_count,
        "failed_files": failed_files,
    }


# ---------------------------------------------------------------------------
# Session tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_sessions(channel_id: str, ctx: Context) -> list[dict[str, Any]]:
    """List chat sessions for a channel. Requires view access."""
    user = _require_user(ctx)
    await _require_view(channel_id, user)
    return await sessions_store.list_sessions(channel_id)


@mcp.tool()
async def create_session(channel_id: str, ctx: Context) -> dict[str, Any]:
    """Create a new chat session for a channel. Requires view access."""
    user = _require_user(ctx)
    if not channel_id.strip():
        raise ToolError("channel_id is required.")
    await _require_view(channel_id, user)
    return await sessions_store.create_session(channel_id)


@mcp.tool()
async def get_session(session_id: str, ctx: Context) -> dict[str, Any]:
    """Fetch a chat session (including its messages). Requires view access on its channel."""
    user = _require_user(ctx)
    session = await sessions_store.get_session(session_id)
    if session is None:
        raise ToolError("Session not found.")
    await _require_view(session["channel_id"], user)
    return session


@mcp.tool()
async def delete_session(session_id: str, ctx: Context) -> dict[str, bool]:
    """Delete a chat session. Requires view access on its channel."""
    user = _require_user(ctx)
    session = await sessions_store.get_session(session_id)
    if session is None:
        raise ToolError("Session not found.")
    await _require_view(session["channel_id"], user)
    deleted = await sessions_store.delete_session(session_id)
    if not deleted:
        raise ToolError("Session not found.")
    return {"ok": True}


@mcp.tool()
async def rename_session(session_id: str, title: str, ctx: Context) -> dict[str, str]:
    """Rename a chat session's title. Requires view access on its channel."""
    user = _require_user(ctx)
    title = title.strip()
    if not title:
        raise ToolError("title is required.")
    session = await sessions_store.get_session(session_id)
    if session is None:
        raise ToolError("Session not found.")
    await _require_view(session["channel_id"], user)
    await sessions_store.update_title(session_id, title)
    return {"session_id": session_id, "title": title}


# ---------------------------------------------------------------------------
# Chat tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def chat(message: str, channel_id: str, ctx: Context, session_id: str | None = None) -> dict[str, Any]:
    """Send a chat message to a channel and get the complete final answer (no streaming)."""
    user = _require_user(ctx)
    try:
        return await run_chat_turn(channel_id, session_id, message, user)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc


@mcp.tool()
async def chat_regenerate(channel_id: str, session_id: str, ctx: Context) -> dict[str, Any]:
    """Discard the last assistant reply in a session and regenerate it, returning the complete final answer."""
    user = _require_user(ctx)
    try:
        return await run_regenerate_turn(channel_id, session_id, user)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc

