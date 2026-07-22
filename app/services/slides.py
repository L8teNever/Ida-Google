"""Google Slides -- Praesentationen erstellen/lesen, einfache Text-Folien hinzufuegen.

API-Doku: https://developers.google.com/slides/api/reference/rest

Baut bewusst nur einfache Titel+Text-Folien (Standard-Layout TITLE_AND_BODY)
-- freies Layout-Design (Formen, Bilder, Positionierung) ist mit der
Slides-API zwar moeglich, aber deutlich aufwendiger und hier (noch) nicht
gebaut.
"""

from __future__ import annotations

import uuid

from app.google_client import GoogleApiClient, confirm_or_explain

SCOPES = ["https://www.googleapis.com/auth/presentations"]

_BASE = "https://slides.googleapis.com/v1/presentations"


def _slide_text(slide: dict) -> str:
    parts: list[str] = []
    for pe in slide.get("pageElements", []):
        shape = pe.get("shape")
        if not shape:
            continue
        for te in (shape.get("text") or {}).get("textElements", []):
            text_run = te.get("textRun")
            if text_run:
                parts.append(text_run.get("content", ""))
    return "".join(parts)


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_praesentation_erstellen(titel: str) -> dict:
        """Legt eine neue Praesentation an (startet mit einer Titelfolie).

        titel: Titel der Praesentation.
        """
        data = client.request("POST", _BASE, json_body={"title": titel})
        return {"presentation_id": data["presentationId"], "titel": titel}

    @mcp.tool()
    def google_praesentation_lesen(presentation_id: str) -> dict:
        """Gibt Titel und Text jeder Folie einer Praesentation zurueck.

        presentation_id: aus google_praesentation_erstellen().
        """
        data = client.request("GET", f"{_BASE}/{presentation_id}")
        folien = [
            {"folien_id": s.get("objectId", ""), "text": _slide_text(s)}
            for s in data.get("slides", [])
        ]
        return {"presentation_id": presentation_id, "titel": data.get("title", ""), "folien": folien}

    @mcp.tool()
    def google_praesentation_folie_hinzufuegen(presentation_id: str, titel: str = "", text: str = "") -> dict:
        """Fuegt eine neue Folie mit Titel+Text-Layout hinzu.

        presentation_id: aus google_praesentation_erstellen().
        """
        suffix = uuid.uuid4().hex[:8]
        slide_id = f"slide_{suffix}"
        title_id = f"title_{suffix}"
        body_id = f"body_{suffix}"

        anfragen = [
            {
                "createSlide": {
                    "objectId": slide_id,
                    "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                    "placeholderIdMappings": [
                        {"layoutPlaceholder": {"type": "TITLE"}, "objectId": title_id},
                        {"layoutPlaceholder": {"type": "BODY"}, "objectId": body_id},
                    ],
                }
            }
        ]
        if titel:
            anfragen.append({"insertText": {"objectId": title_id, "text": titel}})
        if text:
            anfragen.append({"insertText": {"objectId": body_id, "text": text}})

        client.request("POST", f"{_BASE}/{presentation_id}:batchUpdate", json_body={"requests": anfragen})
        return {"presentation_id": presentation_id, "folien_id": slide_id}

    @mcp.tool()
    def google_praesentation_folie_loeschen(presentation_id: str, folien_id: str, bestaetigt: bool = False) -> dict:
        """Loescht eine Folie unwiderruflich -- braucht bestaetigt=True.

        folien_id: aus google_praesentation_lesen()/google_praesentation_folie_hinzufuegen().
        Erst beim Nutzer nachfragen, dann mit bestaetigt=True wiederholen.
        """
        guard = confirm_or_explain(bestaetigt, f"Folie {folien_id} in Praesentation {presentation_id} loeschen")
        if guard:
            return guard
        client.request(
            "POST",
            f"{_BASE}/{presentation_id}:batchUpdate",
            json_body={"requests": [{"deleteObject": {"objectId": folien_id}}]},
        )
        return {"ausgefuehrt": True}

    @mcp.tool()
    def google_praesentation_folie_verschieben(presentation_id: str, folien_id: str, neue_position: int) -> dict:
        """Verschiebt eine Folie an eine neue Position (0 = ganz an den Anfang).

        folien_id: aus google_praesentation_lesen(). neue_position: 0-basiert.
        """
        client.request(
            "POST",
            f"{_BASE}/{presentation_id}:batchUpdate",
            json_body={
                "requests": [
                    {"updateSlidesPosition": {"slideObjectIds": [folien_id], "insertionIndex": neue_position}}
                ]
            },
        )
        return {"presentation_id": presentation_id, "folien_id": folien_id, "neue_position": neue_position}
