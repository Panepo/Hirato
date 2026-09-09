from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import AuthUser, get_current_user, is_site_admin, is_site_manager, perform_login
from app.memory.auth_store import auth_store

router = APIRouter(prefix="/api/auth")


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest) -> dict:
    result, _user = await perform_login(body.email, body.password)
    return result


@router.get("/me")
async def me(user: AuthUser = Depends(get_current_user)) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "usergroups": user.usergroups,
        "is_site_admin": is_site_admin(user),
        "is_site_manager": is_site_manager(user),
    }
