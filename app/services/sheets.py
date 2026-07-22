"""Google Sheets -- Tabellen erstellen, Bereiche lesen/schreiben/anhaengen.

API-Doku: https://developers.google.com/sheets/api/reference/rest
"""

from __future__ import annotations

from app.google_client import GoogleApiClient

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_sheet_erstellen(titel: str) -> dict:
        """Legt eine neue Google-Tabelle an.

        titel: Titel der Tabelle.
        """
        data = client.request("POST", _BASE, json_body={"properties": {"title": titel}})
        return {"spreadsheet_id": data["spreadsheetId"], "titel": titel}

    @mcp.tool()
    def google_sheet_lesen(spreadsheet_id: str, bereich: str) -> list[list]:
        """Liest einen Zellbereich als Liste von Zeilen.

        spreadsheet_id: aus google_sheet_erstellen() oder einer Sheets-URL.
        bereich: A1-Notation, z.B. "Tabelle1!A1:D10".
        """
        data = client.request("GET", f"{_BASE}/{spreadsheet_id}/values/{bereich}")
        return (data or {}).get("values", [])

    @mcp.tool()
    def google_sheet_schreiben(spreadsheet_id: str, bereich: str, werte: list[list]) -> dict:
        """Ueberschreibt einen Zellbereich mit neuen Werten.

        bereich: A1-Notation, z.B. "Tabelle1!A1:B2".
        werte: Liste von Zeilen, jede Zeile eine Liste von Zellwerten.
        """
        client.request(
            "PUT",
            f"{_BASE}/{spreadsheet_id}/values/{bereich}",
            params={"valueInputOption": "USER_ENTERED"},
            json_body={"values": werte},
        )
        return {"spreadsheet_id": spreadsheet_id, "geschrieben": True}

    @mcp.tool()
    def google_sheet_zeile_anhaengen(spreadsheet_id: str, bereich: str, werte: list) -> dict:
        """Haengt eine neue Zeile am Ende eines Bereichs an.

        bereich: A1-Notation, z.B. "Tabelle1!A:D" (Tabellenname reicht meist).
        werte: die Zellwerte der neuen Zeile als flache Liste.
        """
        client.request(
            "POST",
            f"{_BASE}/{spreadsheet_id}/values/{bereich}:append",
            params={"valueInputOption": "USER_ENTERED"},
            json_body={"values": [werte]},
        )
        return {"spreadsheet_id": spreadsheet_id, "angehaengt": True}
