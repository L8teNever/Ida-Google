"""Google Kalender -- Termine lesen/erstellen/aktualisieren/loeschen.

API-Doku: https://developers.google.com/calendar/api/v3/reference

Hinweis: der offizielle claude.ai Google-Calendar-Connector deckt das
bereits vollstaendig ab -- dieses Modul existiert trotzdem, weil explizit
gewuenscht (ein einziger einheitlicher Connector statt mehrerer).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.google_client import GoogleApiClient

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_BASE = "https://www.googleapis.com/calendar/v3"
_STANDARD_ZEITRAUM_TAGE = 30


def _termin_kurz(event: dict) -> dict:
    start = event.get("start") or {}
    end = event.get("end") or {}
    return {
        "id": event.get("id", ""),
        "titel": event.get("summary", ""),
        "beschreibung": event.get("description", ""),
        "start": start.get("dateTime") or start.get("date"),
        "ende": end.get("dateTime") or end.get("date"),
        "ort": event.get("location", ""),
    }


def _zeitfeld(wert: str, ganztaegig: bool) -> dict:
    return {"date": wert} if ganztaegig else {"dateTime": wert}


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_termine_liste(
        von: str = "",
        bis: str = "",
        max_ergebnisse: int = 20,
        kalender_id: str = "primary",
    ) -> list[dict]:
        """Gibt Kalendertermine in einem Zeitraum zurueck, chronologisch sortiert.

        von/bis: ISO 8601 (z.B. "2026-07-22T00:00:00Z"). Leer -> von jetzt an,
        die naechsten 30 Tage.
        kalender_id: "primary" (Standard) oder eine andere Kalender-ID.
        """
        now = datetime.now(timezone.utc)
        time_min = von or now.isoformat()
        time_max = bis or (now + timedelta(days=_STANDARD_ZEITRAUM_TAGE)).isoformat()

        data = client.request(
            "GET",
            f"{_BASE}/calendars/{kalender_id}/events",
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": max(1, min(max_ergebnisse, 250)),
                "singleEvents": True,
                "orderBy": "startTime",
            },
        )
        return [_termin_kurz(e) for e in (data or {}).get("items", [])]

    @mcp.tool()
    def google_termin_erstellen(
        titel: str,
        start: str,
        ende: str,
        beschreibung: str = "",
        ganztaegig: bool = False,
        kalender_id: str = "primary",
    ) -> dict:
        """Legt einen neuen Kalendertermin an.

        start/ende: bei ganztaegig=False ISO 8601 mit Zeitzone (z.B.
        "2026-07-22T14:00:00+02:00"), bei ganztaegig=True nur "YYYY-MM-DD".
        """
        body = {
            "summary": titel,
            "description": beschreibung,
            "start": _zeitfeld(start, ganztaegig),
            "end": _zeitfeld(ende, ganztaegig),
        }
        data = client.request("POST", f"{_BASE}/calendars/{kalender_id}/events", json_body=body)
        return _termin_kurz(data)

    @mcp.tool()
    def google_termin_aktualisieren(
        event_id: str,
        titel: str = "",
        start: str = "",
        ende: str = "",
        beschreibung: str = "",
        ganztaegig: bool = False,
        kalender_id: str = "primary",
    ) -> dict:
        """Aendert einzelne Felder eines bestehenden Termins (nur angegebene
        Felder werden veraendert, leere Parameter bleiben unangetastet).

        event_id: aus google_termine_liste().
        """
        body: dict = {}
        if titel:
            body["summary"] = titel
        if beschreibung:
            body["description"] = beschreibung
        if start:
            body["start"] = _zeitfeld(start, ganztaegig)
        if ende:
            body["end"] = _zeitfeld(ende, ganztaegig)

        data = client.request(
            "PATCH", f"{_BASE}/calendars/{kalender_id}/events/{event_id}", json_body=body
        )
        return _termin_kurz(data)

    @mcp.tool()
    def google_termin_loeschen(event_id: str, kalender_id: str = "primary") -> str:
        """Loescht einen Termin unwiderruflich.

        event_id: aus google_termine_liste().
        """
        client.request("DELETE", f"{_BASE}/calendars/{kalender_id}/events/{event_id}")
        return "Termin geloescht."
