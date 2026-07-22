"""OAuth-Kern fuer Google: einmaliger (oder bei neuen Scopes erneuter)
Anmelde-Flow auf dem Auth-Port, danach automatisches Token-Refresh fuer alle
Google-Tools auf dem MCP-Port. Ein Account, ein gespeicherter Refresh-Token
-- kein Multi-User-Handling noetig, dieser Server ist wie alle anderen
Ida-*-Projekte strukturell auf genau eine Person/einen Account ausgelegt.

Ablauf:
1. GET /authorize -> Weiterleitung zu Googles Consent-Screen mit allen
   aktuell benoetigten Scopes (siehe app/services/*.py).
2. Google leitet zu GET /oauth/callback?code=...&state=... zurueck.
3. state wird gegen den beim Schritt 1 gemerkten Wert geprueft (CSRF-Schutz
   fuer den OAuth-Redirect selbst -- unabhaengig davon, wer den Auth-Port
   ueberhaupt erreichen darf).
4. code wird gegen einen Refresh-Token getauscht und dauerhaft gespeichert
   (GOOGLE_TOKEN_FILE_PATH).
5. Alle Google-Tools auf dem MCP-Port rufen get_access_token() auf, das
   automatisch mit dem gespeicherten Refresh-Token einen frischen
   Access-Token besorgt (und ihn bis kurz vor Ablauf im Speicher cached,
   statt bei jedem Tool-Aufruf neu zu holen).

access_type=offline + prompt=consent auf der Authorize-URL sorgen dafuer,
dass Google IMMER einen Refresh-Token mitschickt -- auch bei einem erneuten
Durchlauf (z.B. weil ein neuer Google-Dienst neue Scopes braucht).
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from app.config import Settings

_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_STATE_TTL_SECONDS = 600
# Sicherheitsabstand vor dem tatsaechlichen Ablauf, um Race Conditions
# zwischen "Token gilt noch" und "Google lehnt ihn inzwischen ab" zu vermeiden.
_TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS = 60


class GoogleAuthError(RuntimeError):
    """Fehler, die 1:1 als verständliche Meldung an den MCP-Client zurückgehen sollen."""


class GoogleAuthManager:
    def __init__(self, settings: Settings, scopes: list[str]) -> None:
        self._settings = settings
        self._scopes = scopes
        self._path = Path(settings.token_file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._pending_states: dict[str, float] = {}

        # In-Memory-Cache fuer den aktuellen Access-Token, damit nicht bei
        # jedem Tool-Aufruf gegen Google getauscht werden muss.
        self._access_token: str | None = None
        self._access_token_expiry: float = 0.0

    # -- Schritt 1: Authorize-URL --------------------------------------

    def generate_state(self) -> str:
        state = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            # Abgelaufene States bei der Gelegenheit gleich mit aufraeumen.
            expired = [s for s, exp in self._pending_states.items() if exp < now]
            for s in expired:
                del self._pending_states[s]
            self._pending_states[state] = now + _STATE_TTL_SECONDS
        return state

    def build_authorize_url(self, state: str) -> str:
        params = {
            "client_id": self._settings.google_client_id,
            "redirect_uri": self._settings.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_AUTHORIZE_URL}?{urlencode(params)}"

    # -- Schritt 2/3: Callback -------------------------------------------

    def consume_state(self, state: str) -> bool:
        """Einmalig gueltig -- nach dem Aufruf (egal ob gueltig oder nicht)
        ist derselbe state-Wert kein zweites Mal akzeptabel."""
        now = time.monotonic()
        with self._lock:
            expiry = self._pending_states.pop(state, None)
        return expiry is not None and expiry >= now

    # -- Schritt 4: Code-Tausch --------------------------------------------

    def exchange_code(self, code: str) -> None:
        response = requests.post(
            _TOKEN_URL,
            data={
                "code": code,
                "client_id": self._settings.google_client_id,
                "client_secret": self._settings.google_client_secret,
                "redirect_uri": self._settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        data = self._parse_token_response(response)

        refresh_token = data.get("refresh_token")
        if not refresh_token:
            raise GoogleAuthError(
                "Google hat keinen Refresh-Token geliefert. Das passiert z.B., "
                "wenn schon vorher zugestimmt wurde, ohne dass Google erneut "
                "gefragt hat -- unter https://myaccount.google.com/permissions "
                "den Zugriff dieser App entfernen und /authorize erneut aufrufen."
            )

        with self._lock:
            self._save({"refresh_token": refresh_token, "granted_scopes": self._scopes})
            self._access_token = data.get("access_token")
            self._access_token_expiry = time.monotonic() + float(data.get("expires_in", 0))

    # -- Schritt 5: Access-Token fuer Tool-Aufrufe -------------------------

    def is_connected(self) -> bool:
        with self._lock:
            return self._load() is not None

    def get_access_token(self) -> str:
        with self._lock:
            if self._access_token and time.monotonic() < self._access_token_expiry:
                return self._access_token

            stored = self._load()
            if stored is None:
                raise GoogleAuthError(
                    "Noch nicht mit Google verbunden -- einmalig die "
                    "/authorize-Seite des Auth-Ports aufrufen und Zugriff "
                    "erlauben."
                )

            response = requests.post(
                _TOKEN_URL,
                data={
                    "refresh_token": stored["refresh_token"],
                    "client_id": self._settings.google_client_id,
                    "client_secret": self._settings.google_client_secret,
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )
            data = self._parse_token_response(response)

            self._access_token = data["access_token"]
            self._access_token_expiry = time.monotonic() + float(data.get("expires_in", 0)) - _TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS
            return self._access_token

    # -- Intern -------------------------------------------------------------

    def _parse_token_response(self, response: requests.Response) -> dict:
        try:
            data = response.json()
        except ValueError as exc:
            raise GoogleAuthError(
                f"Google hat keine gueltige Antwort geliefert (HTTP {response.status_code})."
            ) from exc

        if response.status_code >= 300:
            beschreibung = data.get("error_description") or data.get("error", "unbekannter Fehler")
            raise GoogleAuthError(f"Google-OAuth-Fehler: {beschreibung}")

        return data

    def _load(self) -> dict | None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        if not raw.strip():
            return None
        return json.loads(raw)

    def _save(self, data: dict) -> None:
        self._path.write_text(json.dumps(data), encoding="utf-8")
