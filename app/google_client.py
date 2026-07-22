"""Duenner HTTP-Helfer fuer Google-APIs: haengt den aktuellen Access-Token an
und wandelt Fehlerantworten in verstaendliche Meldungen um. Jedes
app/services/*.py-Modul benutzt das fuer seine eigenen Endpunkte, statt
Token-Handling und Fehler-Parsing zu wiederholen.

Wichtig: Google-Fehlermeldungen werden 1:1 durchgereicht (nicht durch eigene
Vermutungen ersetzt) -- z.B. zeigt sich eine fehlende Berechtigung
(Workspace-only-API mit einem privaten Konto, fehlender Scope, fehlender
Ads-Developer-Token) dann als Googles eigene, genaue Fehlermeldung statt
eines geratenen Textes."""

from __future__ import annotations

from typing import Any

import requests

from app.google_auth import GoogleAuthError, GoogleAuthManager


class GoogleApiError(RuntimeError):
    """Fehler, die 1:1 als verständliche Meldung an den MCP-Client zurückgehen sollen."""


class GoogleApiClient:
    def __init__(self, google: GoogleAuthManager) -> None:
        self._google = google

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        try:
            access_token = self._google.get_access_token()
        except GoogleAuthError as exc:
            raise GoogleApiError(str(exc)) from exc

        response = requests.request(
            method,
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            json=json_body,
            timeout=30,
        )

        if response.status_code == 204:
            return None

        try:
            data = response.json() if response.content else None
        except ValueError:
            data = None

        if response.status_code >= 300:
            beschreibung = None
            if isinstance(data, dict):
                beschreibung = (data.get("error") or {}).get("message")
            beschreibung = beschreibung or f"HTTP {response.status_code}"
            raise GoogleApiError(f"Google-API-Fehler: {beschreibung}")

        return data
