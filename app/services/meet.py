"""Google Meet -- Meeting-Raeume erstellen/abrufen.

API-Doku: https://developers.google.com/workspace/meet/api/guides/overview

Baut bewusst nur das Anlegen eines Meeting-Links (der haeufigste
Anwendungsfall, z.B. um ihn in eine Kalendereinladung zu packen) --
Teilnehmerlisten, Aufzeichnungen/Transkripte (conferenceRecords) kommen bei
Bedarf spaeter dazu.
"""

from __future__ import annotations

from app.google_client import GoogleApiClient

SCOPES = ["https://www.googleapis.com/auth/meetings.space.created"]

_BASE = "https://meet.googleapis.com/v2"


def _raum_kurz(space: dict) -> dict:
    return {
        "name": space.get("name", ""),
        "meeting_uri": space.get("meetingUri", ""),
        "meeting_code": space.get("meetingCode", ""),
    }


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_meet_raum_erstellen() -> dict:
        """Legt einen neuen Google-Meet-Raum an und gibt den Beitritts-Link zurueck.

        Kein Titel/Zeitpunkt -- ein Meet-Raum ist einfach ein dauerhaft
        gueltiger Link, der z.B. per google_termin_erstellen in einen
        Kalendertermin (Beschreibung/Ort) eingefuegt werden kann.
        """
        data = client.request("POST", f"{_BASE}/spaces", json_body={})
        return _raum_kurz(data)

    @mcp.tool()
    def google_meet_raum_details(name: str) -> dict:
        """Gibt Details zu einem bestehenden Meet-Raum zurueck.

        name: aus google_meet_raum_erstellen() (Feld "name", z.B. "spaces/abc-defg-hij").
        """
        data = client.request("GET", f"{_BASE}/{name}")
        return _raum_kurz(data)
