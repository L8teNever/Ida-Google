"""Bearer-Token-Absicherung fuer den MCP-Port (nicht den Auth-Port -- der
hat sein eigenes, einfacheres Schutzschema, siehe app/auth_app.py)."""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

PUBLIC_PATHS = {"/healthz"}


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    api_key_header = request.headers.get("x-api-key")
    if api_key_header:
        return api_key_header.strip()

    return request.query_params.get("token")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        provided = _extract_token(request)
        if not provided or not hmac.compare_digest(provided, self._token):
            return JSONResponse(
                {"error": "unauthorized", "message": "Gültigen Token via Authorization: Bearer <token>, X-API-Key oder ?token= mitschicken."},
                status_code=401,
            )

        return await call_next(request)
