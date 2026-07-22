"""Web-App fuer den Auth-Port: einmaliger (oder bei neuen Scopes erneuter)
Google-Anmelde-Flow. Gedacht, um zusaetzlich hinter Cloudflare Zero Trust
Access zu liegen (siehe README) -- AUTH_TOKEN als ?token= ist nur ein
zusaetzliches, kostenloses Sicherheitsnetz, kein Ersatz dafuer.

/oauth/callback braucht keinen eigenen Token-Check: Google ruft diese URL
per Redirect selbst auf (kann also keinen eigenen Header/Query-Token
mitschicken) -- der state-Parameter (siehe app/google_auth.py) beweist
stattdessen, dass der Callback zu einem hier selbst gestarteten /authorize-
Aufruf gehoert.
"""

from __future__ import annotations

import hmac
import logging

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from app.config import Settings
from app.google_auth import GoogleAuthError, GoogleAuthManager

log = logging.getLogger("ida-google.auth")


def build_auth_app(settings: Settings, google: GoogleAuthManager) -> Starlette:
    def _token_ok(request: Request) -> bool:
        provided = request.query_params.get("token", "")
        return bool(provided) and hmac.compare_digest(provided, settings.auth_token)

    async def healthz(request: Request):
        return JSONResponse({"status": "ok"})

    async def status(request: Request):
        if not _token_ok(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return JSONResponse({"verbunden": google.is_connected()})

    async def authorize(request: Request):
        if not _token_ok(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        state = google.generate_state()
        return RedirectResponse(google.build_authorize_url(state))

    async def oauth_callback(request: Request):
        error = request.query_params.get("error")
        if error:
            return HTMLResponse(
                f"<h1>Google-Anmeldung abgebrochen</h1><p>{error}</p>", status_code=400
            )

        code = request.query_params.get("code")
        state = request.query_params.get("state", "")
        if not code or not google.consume_state(state):
            return HTMLResponse(
                "<h1>Ungueltiger oder abgelaufener Anmelde-Versuch</h1>"
                "<p>Bitte /authorize erneut aufrufen.</p>",
                status_code=400,
            )

        try:
            google.exchange_code(code)
        except GoogleAuthError as exc:
            log.exception("Google-Code-Tausch fehlgeschlagen")
            return HTMLResponse(f"<h1>Fehler</h1><p>{exc}</p>", status_code=500)

        return HTMLResponse(
            "<h1>Erfolgreich mit Google verbunden</h1>"
            "<p>Dieses Fenster kann geschlossen werden.</p>"
        )

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/status", status, methods=["GET"]),
            Route("/authorize", authorize, methods=["GET"]),
            Route("/oauth/callback", oauth_callback, methods=["GET"]),
        ]
    )
