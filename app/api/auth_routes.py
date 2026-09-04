from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import AuthUser, get_current_user, is_site_admin, shiratsuyu_login
from app.memory.auth_store import auth_store

router = APIRouter(prefix="/api/auth")


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest) -> dict:
    result = await shiratsuyu_login(body.email, body.password)

    # Shiratsuyu's exact response shape is unconfirmed; support both a nested
    # "user" object and flat top-level fields until verified against the real API.
    user_data = result.get("user", result)
    user_id = str(user_data.get("id") or user_data.get("_id") or user_data.get("sub"))
    name = user_data.get("name", "")
    usergroups = user_data.get("usergroups", [])

    await auth_store.upsert_user(user_id, name, usergroups)
    return result


@router.get("/me")
async def me(user: AuthUser = Depends(get_current_user)) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "usergroups": user.usergroups,
        "is_site_admin": is_site_admin(user),
    }
