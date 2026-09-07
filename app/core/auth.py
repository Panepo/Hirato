from __future__ import annotations

import httpx
import jwt
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.memory.auth_store import auth_store


class AuthUser(BaseModel):
    id: str
    name: str
    usergroups: list[int]
    empno: str = ""


async def shiratsuyu_login(email: str, password: str) -> dict:
    """POST credentials to Shiratsuyu's /auth endpoint, mapping upstream errors to HTTPException."""
    async with httpx.AsyncClient(base_url=settings.SHIRATSUYU_BASE_URL, timeout=settings.SERVER_TIMEOUT) as client:
        try:
            resp = await client.post(
                "/auth",
                json={"email": email, "password": password, "server": settings.SHIRATSUYU_SERVER_NAME},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Shiratsuyu login unreachable: {exc}") from exc

    if resp.status_code in (400, 401, 404):
        raise HTTPException(status_code=resp.status_code, detail="Invalid credentials")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Shiratsuyu login failed: {resp.status_code}")

    return resp.json()


async def shiratsuyu_query_user(identifier: str) -> list[dict]:
    """GET /user/query/:identifier from Shiratsuyu using the configured SHIRATSUYU_TOKEN."""
    async with httpx.AsyncClient(base_url=settings.SHIRATSUYU_BASE_URL, timeout=settings.SERVER_TIMEOUT) as client:
        try:
            resp = await client.get(f"/user/query/{identifier}", headers={"Authorization": f"Bearer {settings.SHIRATSUYU_TOKEN}"})
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Shiratsuyu query unreachable: {exc}") from exc

    if resp.status_code == 400:
        raise HTTPException(status_code=400, detail="identifier is required")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Shiratsuyu query failed: {resp.status_code}")

    return resp.json()


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


async def get_current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    cached = await auth_store.get_user(str(user_id))
    if cached is None:
        raise HTTPException(status_code=401, detail="Unknown user, please log in again")

    return AuthUser(id=cached["id"], name=cached["name"], usergroups=cached["usergroups"], empno=cached.get("empno", ""))


def is_site_admin(user: AuthUser) -> bool:
    return settings.SITE_ADMIN_ROLE_ID in user.usergroups


async def require_site_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if not is_site_admin(user):
        raise HTTPException(status_code=403, detail="Site admin access required")
    return user
