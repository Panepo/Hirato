from __future__ import annotations

from fastapi import Depends, HTTPException

from app.core.auth import AuthUser, get_current_user, is_site_admin
from app.memory.auth_store import auth_store
from app.memory.store import vector_store

_WRITE_ROLES = {"writer", "manager", "admin"}
_MANAGE_ROLES = {"manager", "admin"}


async def get_effective_role(channel_id: str, user: AuthUser) -> str | None:
    if is_site_admin(user):
        return "admin"
    # Role assignment (via the employee-search "query user" flow) stores the target's
    # empno, not their Shiratsuyu account id, so match on empno first and fall back to
    # id for safety.
    if user.empno:
        role = await auth_store.get_channel_role(channel_id, user.empno)
        if role is not None:
            return role
    return await auth_store.get_channel_role(channel_id, user.id)


async def _check_view(channel_id: str, user: AuthUser) -> None:
    """404s for a missing channel or a closed channel the user has no role in, hiding existence either way."""
    if channel_id not in vector_store.list_channels():
        raise HTTPException(status_code=404, detail="Channel not found")
    if await auth_store.is_channel_open(channel_id):
        return
    if await get_effective_role(channel_id, user) is None:
        raise HTTPException(status_code=404, detail="Channel not found")


async def require_channel_view(channel_id: str, user: AuthUser = Depends(get_current_user)) -> AuthUser:
    await _check_view(channel_id, user)
    return user


async def require_channel_write(channel_id: str, user: AuthUser = Depends(get_current_user)) -> AuthUser:
    await _check_view(channel_id, user)
    role = await get_effective_role(channel_id, user)
    if role not in _WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Write access required")
    return user


async def require_channel_manage(channel_id: str, user: AuthUser = Depends(get_current_user)) -> AuthUser:
    await _check_view(channel_id, user)
    role = await get_effective_role(channel_id, user)
    if role not in _MANAGE_ROLES:
        raise HTTPException(status_code=403, detail="Manage access required")
    return user
