"""Google Keep -- Notizen lesen/erstellen/loeschen.

API-Doku: https://developers.google.com/workspace/keep/api/reference/rest
Ungewoehnliches Schema (gegen die echte Doku geprueft, nicht geraten):
eine Notiz hat "title" und "body", wobei body entweder {"text": {"text": ...}}
(Fliesstext) oder {"list": {"listItems": [...]}} (Checkliste) ist. Diese
erste Ausbaustufe unterstuetzt nur Fliesstext-Notizen -- Checklisten kommen
bei Bedarf dazu.
"""

from __future__ import annotations

from app.google_client import GoogleApiClient, confirm_or_explain

SCOPES = ["https://www.googleapis.com/auth/keep"]

_BASE = "https://keep.googleapis.com/v1"


def _notiz_kurz(note: dict) -> dict:
    body = note.get("body") or {}
    text = (body.get("text") or {}).get("text", "")
    return {
        "name": note.get("name", ""),
        "titel": note.get("title", ""),
        "text": text,
        "geloescht": bool(note.get("trashed")),
    }


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_notizen_liste(max_ergebnisse: int = 20) -> list[dict]:
        """Gibt Google Keep-Notizen zurueck (Titel + Text, keine Checklisten).

        max_ergebnisse: 1-100, Standard 20.
        """
        data = client.request(
            "GET", f"{_BASE}/notes", params={"pageSize": max(1, min(max_ergebnisse, 100))}
        )
        return [_notiz_kurz(n) for n in (data or {}).get("notes", [])]

    @mcp.tool()
    def google_notiz_erstellen(titel: str, text: str) -> dict:
        """Legt eine neue Fliesstext-Notiz in Google Keep an.

        titel: Titel der Notiz (kann leer sein).
        text: Inhalt, max. 20.000 Zeichen.
        """
        data = client.request(
            "POST",
            f"{_BASE}/notes",
            json_body={"title": titel, "body": {"text": {"text": text}}},
        )
        return _notiz_kurz(data)

    @mcp.tool()
    def google_notiz_loeschen(name: str, bestaetigt: bool = False) -> dict:
        """Loescht eine Notiz unwiderruflich -- braucht bestaetigt=True.

        name: aus google_notizen_liste() (Feld "name", z.B. "notes/abc123").
        Erst beim Nutzer nachfragen, dann mit bestaetigt=True wiederholen.
        """
        guard = confirm_or_explain(bestaetigt, f"Notiz {name} endgueltig loeschen")
        if guard:
            return guard
        client.request("DELETE", f"{_BASE}/{name}")
        return {"ausgefuehrt": True}
