"""Google Docs -- Dokumente erstellen/lesen/Text anhaengen.

API-Doku: https://developers.google.com/docs/api/reference/rest

endOfSegmentLocation statt manueller Index-Berechnung fuers Anhaengen --
robuster als selbst die letzte Index-Position des Dokuments auszurechnen.
"""

from __future__ import annotations

from app.google_client import GoogleApiClient

SCOPES = ["https://www.googleapis.com/auth/documents"]

_BASE = "https://docs.googleapis.com/v1/documents"


def _extract_text(document: dict) -> str:
    """Liest den Fliesstext aus der verschachtelten Docs-Struktur
    (body.content[].paragraph.elements[].textRun.content)."""
    parts: list[str] = []
    for element in (document.get("body") or {}).get("content", []):
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        for pe in paragraph.get("elements", []):
            text_run = pe.get("textRun")
            if text_run:
                parts.append(text_run.get("content", ""))
    return "".join(parts)


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_doc_erstellen(titel: str, text: str = "") -> dict:
        """Legt ein neues Google Doc an, optional mit initialem Text.

        titel: Dokumenttitel. text: optionaler Anfangsinhalt.
        """
        data = client.request("POST", _BASE, json_body={"title": titel})
        document_id = data["documentId"]
        if text:
            client.request(
                "POST",
                f"{_BASE}/{document_id}:batchUpdate",
                json_body={"requests": [{"insertText": {"text": text, "endOfSegmentLocation": {}}}]},
            )
        return {"document_id": document_id, "titel": titel}

    @mcp.tool()
    def google_doc_lesen(document_id: str) -> dict:
        """Gibt Titel und kompletten Fliesstext eines Google Docs zurueck.

        document_id: aus google_doc_erstellen() oder einer Google-Docs-URL
        (der Teil nach "/d/" und vor "/edit").
        """
        data = client.request("GET", f"{_BASE}/{document_id}")
        return {"document_id": document_id, "titel": data.get("title", ""), "text": _extract_text(data)}

    @mcp.tool()
    def google_doc_text_anhaengen(document_id: str, text: str) -> dict:
        """Haengt Text an das Ende eines bestehenden Google Docs an.

        document_id: aus google_doc_erstellen()/google_doc_lesen().
        """
        client.request(
            "POST",
            f"{_BASE}/{document_id}:batchUpdate",
            json_body={"requests": [{"insertText": {"text": text, "endOfSegmentLocation": {}}}]},
        )
        return {"document_id": document_id, "angehaengt": True}
