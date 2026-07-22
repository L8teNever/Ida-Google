"""Google Docs -- Dokumente erstellen/lesen/Text anhaengen.

API-Doku: https://developers.google.com/docs/api/reference/rest

endOfSegmentLocation statt manueller Index-Berechnung fuers Anhaengen --
robuster als selbst die letzte Index-Position des Dokuments auszurechnen.
"""

from __future__ import annotations

from app.google_client import GoogleApiClient, confirm_or_explain

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

    @mcp.tool()
    def google_doc_text_einfuegen(document_id: str, text: str, index: int) -> dict:
        """Fuegt Text an einer bestimmten Position ein (nicht nur am Ende).

        document_id: aus google_doc_erstellen()/google_doc_lesen(). index:
        Zeichenposition -- Index 1 ist der Dokumentanfang (0 ist reserviert).
        """
        client.request(
            "POST",
            f"{_BASE}/{document_id}:batchUpdate",
            json_body={"requests": [{"insertText": {"text": text, "location": {"index": index}}}]},
        )
        return {"document_id": document_id, "eingefuegt": True}

    @mcp.tool()
    def google_doc_text_loeschen(document_id: str, start_index: int, end_index: int, bestaetigt: bool = False) -> dict:
        """Loescht den Text zwischen zwei Positionen unwiderruflich --
        braucht bestaetigt=True.

        document_id/Indizes: start_index/end_index z.B. aus vorherigem
        google_doc_lesen() (Position im Fliesstext abzaehlen). Erst beim
        Nutzer nachfragen, dann mit bestaetigt=True wiederholen.
        """
        guard = confirm_or_explain(
            bestaetigt, f"Text von Position {start_index} bis {end_index} in Dokument {document_id} loeschen"
        )
        if guard:
            return guard
        client.request(
            "POST",
            f"{_BASE}/{document_id}:batchUpdate",
            json_body={
                "requests": [
                    {"deleteContentRange": {"range": {"startIndex": start_index, "endIndex": end_index}}}
                ]
            },
        )
        return {"ausgefuehrt": True}

    @mcp.tool()
    def google_doc_text_ersetzen(document_id: str, suchtext: str, ersatztext: str, gross_klein_beachten: bool = True) -> dict:
        """Ersetzt alle Vorkommen eines Textes im Dokument (Suchen & Ersetzen).

        document_id: aus google_doc_erstellen()/google_doc_lesen().
        """
        data = client.request(
            "POST",
            f"{_BASE}/{document_id}:batchUpdate",
            json_body={
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {"text": suchtext, "matchCase": gross_klein_beachten},
                            "replaceText": ersatztext,
                        }
                    }
                ]
            },
        )
        anzahl = (data.get("replies") or [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
        return {"document_id": document_id, "ersetzungen": anzahl}

    @mcp.tool()
    def google_doc_formatieren(
        document_id: str, start_index: int, end_index: int,
        fett: bool = False, kursiv: bool = False, unterstrichen: bool = False,
    ) -> dict:
        """Wendet einfache Textformatierung auf einen Bereich an.

        Indizes wie bei google_doc_text_loeschen. Nur die auf True gesetzten
        Formatierungen werden angewendet, andere Formatierung im Bereich
        bleibt unangetastet.
        """
        text_style: dict = {}
        fields = []
        if fett:
            text_style["bold"] = True
            fields.append("bold")
        if kursiv:
            text_style["italic"] = True
            fields.append("italic")
        if unterstrichen:
            text_style["underline"] = True
            fields.append("underline")

        client.request(
            "POST",
            f"{_BASE}/{document_id}:batchUpdate",
            json_body={
                "requests": [
                    {
                        "updateTextStyle": {
                            "range": {"startIndex": start_index, "endIndex": end_index},
                            "textStyle": text_style,
                            "fields": ",".join(fields) if fields else "*",
                        }
                    }
                ]
            },
        )
        return {"document_id": document_id, "formatiert": True}
