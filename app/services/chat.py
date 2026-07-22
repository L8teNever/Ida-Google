"""Google Chat -- Raeume auflisten, Nachrichten senden/lesen.

API-Doku: https://developers.google.com/workspace/chat/api/reference/rest

Unklar (nicht ohne echten Account vorab verifizierbar), ob Google Chat mit
einem normalen privaten Google-Konto vollstaendig nutzbar ist oder ein
Workspace-Konto braucht -- kommt beim ersten echten Aufruf als Googles
eigene Fehlermeldung durch (siehe app/google_client.py), statt hier geraten
zu werden.
"""

from __future__ import annotations

from app.google_client import GoogleApiClient

SCOPES = [
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.messages",
]

_BASE = "https://chat.googleapis.com/v1"


def _raum_kurz(space: dict) -> dict:
    return {
        "name": space.get("name", ""),
        "anzeigename": space.get("displayName", ""),
        "typ": space.get("spaceType", ""),
    }


def _nachricht_kurz(message: dict) -> dict:
    return {
        "name": message.get("name", ""),
        "text": message.get("text", ""),
        "erstellt": message.get("createTime", ""),
        "absender": (message.get("sender") or {}).get("name", ""),
    }


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_chat_raeume_liste() -> list[dict]:
        """Gibt die Google-Chat-Raeume zurueck, in denen der Account Mitglied ist.

        Einzelchats/Gruppen tauchen laut Google erst auf, nachdem die erste
        Nachricht darin geschickt wurde.
        """
        data = client.request("GET", f"{_BASE}/spaces")
        return [_raum_kurz(s) for s in (data or {}).get("spaces", [])]

    @mcp.tool()
    def google_chat_nachricht_senden(space_name: str, text: str) -> dict:
        """Sendet eine Textnachricht in einen Google-Chat-Raum.

        space_name: aus google_chat_raeume_liste() (Feld "name", z.B. "spaces/AAAA").
        """
        data = client.request("POST", f"{_BASE}/{space_name}/messages", json_body={"text": text})
        return _nachricht_kurz(data)

    @mcp.tool()
    def google_chat_nachrichten_liste(space_name: str, max_ergebnisse: int = 20) -> list[dict]:
        """Gibt die letzten Nachrichten eines Google-Chat-Raums zurueck.

        space_name: aus google_chat_raeume_liste().
        """
        data = client.request(
            "GET",
            f"{_BASE}/{space_name}/messages",
            params={"pageSize": max(1, min(max_ergebnisse, 100))},
        )
        return [_nachricht_kurz(m) for m in (data or {}).get("messages", [])]
