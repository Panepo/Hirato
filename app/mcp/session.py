from __future__ import annotations

from app.core.auth import AuthUser


class McpAuthSessionManager:
    """In-memory map of MCP connection identity -> logged-in AuthUser.

    Keyed by id(ctx.session) (the ServerSession object is stable for the lifetime of an
    MCP connection; the SDK doesn't expose a simpler stable identity attribute).
    Not persisted: MCP client connections are inherently ephemeral, same as REST bearer tokens.
    """

    def __init__(self) -> None:
        self._sessions: dict[int, AuthUser] = {}

    def login(self, key: int, user: AuthUser) -> None:
        self._sessions[key] = user

    def get(self, key: int) -> AuthUser | None:
        return self._sessions.get(key)

    def logout(self, key: int) -> None:
        self._sessions.pop(key, None)


mcp_sessions = McpAuthSessionManager()
