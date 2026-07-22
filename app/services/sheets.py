"""Google Sheets -- Tabellen erstellen, Bereiche lesen/schreiben/anhaengen.

API-Doku: https://developers.google.com/sheets/api/reference/rest
"""

from __future__ import annotations

from app.google_client import GoogleApiClient, confirm_or_explain

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

    @mcp.tool()
    def google_sheet_bereich_leeren(spreadsheet_id: str, bereich: str, bestaetigt: bool = False) -> dict:
        """Loescht den Inhalt eines Zellbereichs (Zellen bleiben, nur der
        Inhalt verschwindet) -- braucht bestaetigt=True.

        bereich: A1-Notation. Erst beim Nutzer nachfragen, dann mit
        bestaetigt=True wiederholen.
        """
        guard = confirm_or_explain(bestaetigt, f"Bereich {bereich} in Tabelle {spreadsheet_id} leeren")
        if guard:
            return guard
        client.request("POST", f"{_BASE}/{spreadsheet_id}/values/{bereich}:clear")
        return {"ausgefuehrt": True}

    @mcp.tool()
    def google_sheet_tabellenblatt_hinzufuegen(spreadsheet_id: str, titel: str) -> dict:
        """Fuegt der Tabelle ein neues Tabellenblatt (Tab) hinzu.

        titel: Name des neuen Tabellenblatts.
        """
        data = client.request(
            "POST",
            f"{_BASE}/{spreadsheet_id}:batchUpdate",
            json_body={"requests": [{"addSheet": {"properties": {"title": titel}}}]},
        )
        sheet_id = data["replies"][0]["addSheet"]["properties"]["sheetId"]
        return {"spreadsheet_id": spreadsheet_id, "sheet_id": sheet_id, "titel": titel}

    @mcp.tool()
    def google_sheet_tabellenblatt_umbenennen(spreadsheet_id: str, sheet_id: int, neuer_titel: str) -> dict:
        """Benennt ein bestehendes Tabellenblatt um.

        sheet_id: aus google_sheet_tabellenblatt_hinzufuegen() oder den
        Tabellen-Eigenschaften (nicht dieselbe id wie spreadsheet_id!).
        """
        client.request(
            "POST",
            f"{_BASE}/{spreadsheet_id}:batchUpdate",
            json_body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": sheet_id, "title": neuer_titel},
                            "fields": "title",
                        }
                    }
                ]
            },
        )
        return {"spreadsheet_id": spreadsheet_id, "sheet_id": sheet_id, "titel": neuer_titel}

    @mcp.tool()
    def google_sheet_tabellenblatt_loeschen(spreadsheet_id: str, sheet_id: int, bestaetigt: bool = False) -> dict:
        """Loescht ein komplettes Tabellenblatt unwiderruflich -- braucht bestaetigt=True.

        sheet_id: NICHT die spreadsheet_id -- die interne Blatt-ID (siehe
        google_sheet_tabellenblatt_hinzufuegen). Erst beim Nutzer
        nachfragen, dann mit bestaetigt=True wiederholen.
        """
        guard = confirm_or_explain(
            bestaetigt, f"Tabellenblatt {sheet_id} in Tabelle {spreadsheet_id} endgueltig loeschen"
        )
        if guard:
            return guard
        client.request(
            "POST",
            f"{_BASE}/{spreadsheet_id}:batchUpdate",
            json_body={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
        )
        return {"ausgefuehrt": True}
