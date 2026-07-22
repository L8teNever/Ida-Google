"""Gmail -- suchen/lesen/senden.

API-Doku: https://developers.google.com/gmail/api/reference/rest

Bewusst NUR gmail.readonly + gmail.send als Scopes (nicht gmail.modify oder
gar den vollen gmail-Scope) -- lesen und senden ist alles, was hier gebraucht
wird, Labels/Loeschen/Filter-Verwaltung nicht. Der offizielle claude.ai
Gmail-Connector kann lesen und Entwuerfe anlegen, aber nicht senden -- genau
diese Luecke deckt google_mail_senden.

Gmails "raw"-Format fuer send ist eine komplette RFC2822-Nachricht,
base64url-kodiert -- dafuer wird Pythons email-Standardbibliothek benutzt
(korrektes Encoding von Kopfzeilen/Umlauten inklusive), keine
selbstgestrickte String-Verkettung. Beim Lesen ist es umgekehrt: die
Nachricht kommt als (moeglicherweise verschachtelte) MIME-Struktur mit
base64url-kodierten Teilen zurueck -- wird rekursiv nach dem ersten
text/plain-Teil durchsucht.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage

from app.google_client import GoogleApiClient

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _header(headers: list[dict], name: str) -> str:
    for h in headers or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _find_plain_text(payload: dict) -> str | None:
    if payload.get("mimeType") == "text/plain":
        data = (payload.get("body") or {}).get("data")
        return _decode_base64url(data) if data else ""

    for part in payload.get("parts") or []:
        found = _find_plain_text(part)
        if found is not None:
            return found
    return None


def _build_raw_message(an: str, betreff: str, text: str) -> str:
    msg = EmailMessage()
    msg["To"] = an
    msg["Subject"] = betreff
    msg.set_content(text)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_mails_suchen(query: str = "", max_ergebnisse: int = 10) -> list[dict]:
        """Durchsucht Gmail (Gmail-Suchsyntax, z.B. "is:unread", "from:x@y.com").

        query: leer = keine Einschraenkung (ueber alle Mails). max_ergebnisse:
        1-25, Standard 10 -- pro Treffer ist ein zusaetzlicher API-Aufruf fuer
        die Kopfzeilen noetig, deshalb bewusst klein gehalten.
        """
        max_ergebnisse = max(1, min(max_ergebnisse, 25))
        liste = client.request(
            "GET", f"{_BASE}/messages", params={"q": query, "maxResults": max_ergebnisse}
        )
        ergebnisse = []
        for eintrag in (liste or {}).get("messages", []):
            msg = client.request(
                "GET",
                f"{_BASE}/messages/{eintrag['id']}",
                params={
                    "format": "metadata",
                    "metadataHeaders": ["Subject", "From", "Date"],
                },
            )
            headers = (msg.get("payload") or {}).get("headers", [])
            ergebnisse.append(
                {
                    "id": msg["id"],
                    "betreff": _header(headers, "Subject"),
                    "von": _header(headers, "From"),
                    "datum": _header(headers, "Date"),
                    "vorschau": msg.get("snippet", ""),
                }
            )
        return ergebnisse

    @mcp.tool()
    def google_mail_lesen(message_id: str) -> dict:
        """Gibt eine einzelne Mail vollstaendig zurueck (Kopfzeilen + Text).

        message_id: aus google_mails_suchen().
        Wenn keine reine Textversion existiert (z.B. eine reine HTML-Mail),
        steht das im Feld "text" statt eines geratenen/kaputten Auszugs.
        """
        msg = client.request("GET", f"{_BASE}/messages/{message_id}", params={"format": "full"})
        payload = msg.get("payload") or {}
        headers = payload.get("headers", [])
        text = _find_plain_text(payload)

        return {
            "id": msg["id"],
            "betreff": _header(headers, "Subject"),
            "von": _header(headers, "From"),
            "an": _header(headers, "To"),
            "datum": _header(headers, "Date"),
            "text": text if text is not None else "(keine reine Textversion gefunden -- evtl. nur HTML)",
        }

    @mcp.tool()
    def google_mail_senden(an: str, betreff: str, text: str) -> dict:
        """Sendet eine neue Text-E-Mail (kein Reply/Thread, keine Anhaenge).

        an: Empfaenger-E-Mail-Adresse. betreff/text: Betreff und Nachrichtentext.
        """
        raw = _build_raw_message(an, betreff, text)
        data = client.request("POST", f"{_BASE}/messages/send", json_body={"raw": raw})
        return {"gesendet": True, "message_id": data.get("id", "")}
