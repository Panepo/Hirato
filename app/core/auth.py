from __future__ import annotations

from datetime import datetime, timezone

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


async def shiratsuyu_get_user_data(user_data_id: str) -> list[dict]:
    """GET /user/data/ from Shiratsuyu; unlike GET /user/:id, this is where name/empno actually live."""
    async with httpx.AsyncClient(base_url=settings.SHIRATSUYU_BASE_URL, timeout=settings.SERVER_TIMEOUT) as client:
        try:
            resp = await client.request(
                "GET",
                "/user/data/",
                headers={"Authorization": f"Bearer {settings.SHIRATSUYU_TOKEN}"},
                json={"where": {"id": user_data_id}, "select": {"name": True, "empno": True}},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Shiratsuyu user data lookup unreachable: {exc}") from exc

    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Shiratsuyu user data lookup failed: {resp.status_code}")

    return resp.json()


async def shiratsuyu_get_user_by_id(user_id: str) -> dict:
    """GET /user/:id from Shiratsuyu using the configured SHIRATSUYU_TOKEN."""
    async with httpx.AsyncClient(base_url=settings.SHIRATSUYU_BASE_URL, timeout=settings.SERVER_TIMEOUT) as client:
        try:
            resp = await client.get(f"/user/{user_id}", headers={"Authorization": f"Bearer {settings.SHIRATSUYU_TOKEN}"})
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Shiratsuyu user lookup unreachable: {exc}") from exc

    if resp.status_code == 404:
        raise HTTPException(status_code=401, detail="Unknown Shiratsuyu user") from None
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Shiratsuyu user lookup failed: {resp.status_code}")

    return resp.json()


class McpTokenValidation(BaseModel):
    """Shape of Shiratsuyu's `POST /mcp/validate` response (see MCP-AUTH-INTEGRATION.md)."""

    valid: bool
    userId: str = ""
    scopes: list[str] = []
    expiresAt: str | None = None
    revoked: bool = False


async def shiratsuyu_validate_mcp_token(token: str, required_scopes: list[str] | None = None) -> McpTokenValidation:
    """POST /mcp/validate to Shiratsuyu to verify an MCP API key issued by Shiratsuyu."""
    async with httpx.AsyncClient(base_url=settings.SHIRATSUYU_BASE_URL, timeout=settings.SERVER_TIMEOUT) as client:
        try:
            resp = await client.post(
                "/mcp/validate",
                json={"token": token, "requiredScopes": required_scopes or []},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Shiratsuyu token validation unreachable: {exc}") from exc

    if resp.status_code >= 400:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    return McpTokenValidation.model_validate(resp.json())


async def resolve_mcp_api_key(api_key: str) -> AuthUser:
    """Verify an MCP API key against Shiratsuyu and resolve the associated user.

    Every call round-trips to Shiratsuyu's `/mcp/validate` (no local token decoding) so
    revocation/expiry are always checked live, per MCP-AUTH-INTEGRATION.md. The key itself
    carries no profile data — only a `userId` — so name/usergroups/empno are looked up (and
    cached in auth_store, refreshed on every successful validation) via Shiratsuyu's user APIs.
    """
    required_scopes = [settings.SHIRATSUYU_SERVER_NAME]
    validation = await shiratsuyu_validate_mcp_token(api_key, required_scopes)

    if not validation.valid or validation.revoked:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    if validation.expiresAt:
        expires_at = datetime.fromisoformat(validation.expiresAt.replace("Z", "+00:00"))
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="API key expired")
    if not all(scope in validation.scopes for scope in required_scopes):
        raise HTTPException(status_code=403, detail="API key missing required scope")
    if not validation.userId:
        raise HTTPException(status_code=401, detail="API key not associated with a user")

    user_record = await shiratsuyu_get_user_by_id(validation.userId)
    usergroups = user_record.get("usergroups", [])
    name = user_record.get("email", "")
    empno = ""
    user_data_id = user_record.get("userDataId")
    if user_data_id:
        records = await shiratsuyu_get_user_data(user_data_id)
        if records:
            name = records[0].get("name") or name
            empno = records[0].get("empno") or ""

    await auth_store.upsert_user(validation.userId, name, usergroups, empno)
    return AuthUser(id=validation.userId, name=name, usergroups=usergroups, empno=empno)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


async def resolve_bearer_token(token: str) -> AuthUser:
    """Decode a bearer JWT and look up the cached user — shared by REST and MCP header auth."""
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    cached = await auth_store.get_user(str(user_id))
    if cached is None:
        raise HTTPException(status_code=401, detail="Unknown user, please log in again")

    return AuthUser(id=cached["id"], name=cached["name"], usergroups=cached["usergroups"], empno=cached.get("empno", ""))


async def get_current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    return await resolve_bearer_token(token)


def is_site_admin(user: AuthUser) -> bool:
    return settings.SITE_ADMIN_ROLE_ID in user.usergroups


def is_site_manager(user: AuthUser) -> bool:
    return settings.SITE_MANAGER_ROLE_ID in user.usergroups


async def require_site_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if not is_site_admin(user):
        raise HTTPException(status_code=403, detail="Site admin access required")
    return user


async def require_channel_creator(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """Site admins and site managers can create channels; site managers get no other special privileges."""
    if not is_site_admin(user) and not is_site_manager(user):
        raise HTTPException(status_code=403, detail="Site admin or site manager access required")
    return user


async def perform_login(email: str, password: str) -> tuple[dict, AuthUser]:
    """Log in against Shiratsuyu, upsert the local user cache, and return (raw_result, AuthUser).

    The raw dict is Shiratsuyu's original response body (REST callers return it as-is);
    the AuthUser is the normalized shape MCP tools and get_current_user() work with.
    """
    result = await shiratsuyu_login(email, password)

    # Shiratsuyu's exact response shape is unconfirmed; support both a nested
    # "user" object and flat top-level fields until verified against the real API.
    user_data = result.get("user", result)
    user_id = str(user_data.get("id") or user_data.get("_id") or user_data.get("sub"))
    name = user_data.get("name", "")
    usergroups = user_data.get("usergroups", [])
    nested_data = user_data.get("data") or {}
    # /auth/GET-user-by-id omit empno; it only lives on the UserData record behind userDataId.
    empno = ""
    user_data_id = user_data.get("userDataId") or nested_data.get("userDataId")
    if user_data_id:
        records = await shiratsuyu_get_user_data(user_data_id)
        if records:
            empno = records[0].get("empno") or ""
    if not empno:
        empno = user_data.get("empno") or nested_data.get("empno") or ""

    await auth_store.upsert_user(user_id, name, usergroups, empno)
    return result, AuthUser(id=user_id, name=name, usergroups=usergroups, empno=empno)
