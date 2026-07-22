"""Gmail -- suchen/lesen/senden/antworten/Labels/Papierkorb.

API-Doku: https://developers.google.com/gmail/api/reference/rest

Scope bewusst nur gmail.modify (deckt lesen/schreiben/senden/Labels/
Papierkorb ab) statt der sehr viel breiteren https://mail.google.com/ --
gmail.modify erlaubt laut Googles eigener Beschreibung explizit KEIN
endgueltiges Loeschen an der Papierkorb vorbei. "Loeschen" ist hier deshalb
als Verschieben in den Papierkorb umgesetzt (30 Tage lang erholbar), nicht
als sofortige, unwiderrufliche Vernichtung -- und braucht trotzdem
bestaetigt=True wie die anderen Loesch-Tools.

Gmails "raw"-Format fuer send ist eine komplette RFC2822-Nachricht,
base64url-kodiert -- dafuer wird Pythons email-Standardbibliothek benutzt
(korrektes Encoding von Kopfzeilen/Umlauten/Anhaengen inklusive), keine
selbstgestrickte String-Verkettung. Beim Lesen ist es umgekehrt: die
Nachricht kommt als (moeglicherweise verschachtelte) MIME-Struktur mit
base64url-kodierten Teilen zurueck -- wird rekursiv nach dem ersten
text/plain-Teil durchsucht.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage

from mcp.server.fastmcp import Image

from app.google_client import GoogleApiClient, confirm_or_explain

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

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


def _find_attachments(payload: dict, gefunden: list[dict] | None = None) -> list[dict]:
    if gefunden is None:
        gefunden = []
    body = payload.get("body") or {}
    if payload.get("filename") and body.get("attachmentId"):
        gefunden.append(
            {
                "attachment_id": body["attachmentId"],
                "dateiname": payload["filename"],
                "mimetyp": payload.get("mimeType", ""),
                "groesse_bytes": body.get("size", 0),
            }
        )
    for part in payload.get("parts") or []:
        _find_attachments(part, gefunden)
    return gefunden


def _build_raw_message(
    an: str, betreff: str, text: str, cc: str, bcc: str, anhaenge: list[dict] | None,
    in_reply_to: str = "", references: str = "",
) -> str:
    msg = EmailMessage()
    msg["To"] = an
    msg["Subject"] = betreff
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to
    msg.set_content(text)

    for anhang in anhaenge or []:
        mimetyp = anhang.get("mimetyp", "application/octet-stream")
        haupttyp, _, subtyp = mimetyp.partition("/")
        rohdaten = base64.b64decode(anhang["inhalt_base64"])
        msg.add_attachment(
            rohdaten, maintype=haupttyp or "application", subtype=subtyp or "octet-stream",
            filename=anhang.get("dateiname", "anhang"),
        )

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
        """Gibt eine einzelne Mail vollstaendig zurueck (Kopfzeilen + Text + Anhang-Liste).

        message_id: aus google_mails_suchen().
        Wenn keine reine Textversion existiert (z.B. eine reine HTML-Mail),
        steht das im Feld "text" statt eines geratenen/kaputten Auszugs.
        Anhaenge stehen nur als Metadaten da (Name/Groesse/mimetyp) -- den
        Inhalt liefert google_mail_anhang_herunterladen.
        """
        msg = client.request("GET", f"{_BASE}/messages/{message_id}", params={"format": "full"})
        payload = msg.get("payload") or {}
        headers = payload.get("headers", [])
        text = _find_plain_text(payload)

        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId", ""),
            "betreff": _header(headers, "Subject"),
            "von": _header(headers, "From"),
            "an": _header(headers, "To"),
            "datum": _header(headers, "Date"),
            "text": text if text is not None else "(keine reine Textversion gefunden -- evtl. nur HTML)",
            "anhaenge": _find_attachments(payload),
        }

    @mcp.tool()
    def google_mail_anhang_herunterladen(message_id: str, attachment_id: str, dateiname: str = "") -> list:
        """Laedt einen Mail-Anhang herunter -- Bilder als echten Bildinhalt,
        alles andere nur als Metadaten-Hinweis (der Inhalt laesst sich hier
        nicht anzeigen).

        message_id/attachment_id: aus google_mail_lesen() (Feld "anhaenge").
        """
        data = client.request(
            "GET", f"{_BASE}/messages/{message_id}/attachments/{attachment_id}"
        )
        rohbytes = base64.urlsafe_b64decode(data["data"] + "=" * (-len(data["data"]) % 4))

        endung = dateiname.rsplit(".", 1)[-1].lower() if "." in dateiname else ""
        if endung in ("jpg", "jpeg", "png", "gif", "webp"):
            bildformat = "jpeg" if endung == "jpg" else endung
            return [Image(data=rohbytes, format=bildformat)]
        return [f"Anhang '{dateiname or attachment_id}' ist kein Bild ({len(rohbytes)} Bytes) -- Inhalt kann hier nicht angezeigt werden."]

    @mcp.tool()
    def google_mail_senden(
        an: str, betreff: str, text: str, cc: str = "", bcc: str = "", anhaenge: list[dict] | None = None
    ) -> dict:
        """Sendet eine neue E-Mail (kein Reply -- dafuer google_mail_antworten).

        an/cc/bcc: E-Mail-Adressen, mehrere durch Komma getrennt.
        anhaenge: optionale Liste von {"dateiname": str, "mimetyp": str,
        "inhalt_base64": str}.
        """
        raw = _build_raw_message(an, betreff, text, cc, bcc, anhaenge)
        data = client.request("POST", f"{_BASE}/messages/send", json_body={"raw": raw})
        return {"gesendet": True, "message_id": data.get("id", "")}

    @mcp.tool()
    def google_mail_entwurf_erstellen(
        an: str = "", betreff: str = "", text: str = "", cc: str = "", bcc: str = ""
    ) -> dict:
        """Legt einen Mail-Entwurf an, OHNE ihn zu senden -- zum spaeteren
        Fertigstellen/Senden (google_mail_entwurf_senden) oder als reine Notiz.

        Alle Felder optional (auch ein leerer Entwurf ist gueltig).
        """
        raw = _build_raw_message(an, betreff, text, cc, bcc, None)
        data = client.request("POST", f"{_BASE}/drafts", json_body={"message": {"raw": raw}})
        return {"draft_id": data.get("id", "")}

    @mcp.tool()
    def google_mail_entwuerfe_liste(max_ergebnisse: int = 10) -> list[dict]:
        """Gibt bestehende Mail-Entwuerfe zurueck (Betreff, Empfaenger, Vorschau)."""
        max_ergebnisse = max(1, min(max_ergebnisse, 25))
        liste = client.request("GET", f"{_BASE}/drafts", params={"maxResults": max_ergebnisse})
        ergebnisse = []
        for eintrag in (liste or {}).get("drafts", []):
            msg = client.request(
                "GET",
                f"{_BASE}/drafts/{eintrag['id']}",
                params={"format": "metadata", "metadataHeaders": ["Subject", "To"]},
            )
            headers = (msg.get("message") or {}).get("payload", {}).get("headers", [])
            ergebnisse.append(
                {
                    "draft_id": eintrag["id"],
                    "betreff": _header(headers, "Subject"),
                    "an": _header(headers, "To"),
                    "vorschau": (msg.get("message") or {}).get("snippet", ""),
                }
            )
        return ergebnisse

    @mcp.tool()
    def google_mail_entwurf_senden(draft_id: str) -> dict:
        """Sendet einen bestehenden Entwurf -- verschickt sofort und
        unwiderruflich, vor dem Aufruf immer den Inhalt mit dem Nutzer
        bestaetigen (siehe google_mail_entwuerfe_liste).

        draft_id: aus google_mail_entwuerfe_liste()/google_mail_entwurf_erstellen().
        """
        data = client.request("POST", f"{_BASE}/drafts/send", json_body={"id": draft_id})
        return {"gesendet": True, "message_id": data.get("id", "")}

    @mcp.tool()
    def google_mail_antworten(message_id: str, text: str, an_alle: bool = False) -> dict:
        """Antwortet innerhalb eines bestehenden Mail-Threads (mit korrekten
        In-Reply-To/References-Kopfzeilen, erscheint beim Empfaenger als
        Antwort in derselben Unterhaltung statt als neue Mail).

        message_id: aus google_mails_suchen()/google_mail_lesen().
        an_alle: bei True gehen auch die urspruenglichen CC-Empfaenger mit.
        """
        original = client.request(
            "GET",
            f"{_BASE}/messages/{message_id}",
            params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Message-ID", "Cc"]},
        )
        headers = (original.get("payload") or {}).get("headers", [])
        betreff = _header(headers, "Subject")
        if not betreff.lower().startswith("re:"):
            betreff = f"Re: {betreff}"

        raw = _build_raw_message(
            an=_header(headers, "From"),
            betreff=betreff,
            text=text,
            cc=_header(headers, "Cc") if an_alle else "",
            bcc="",
            anhaenge=None,
            in_reply_to=_header(headers, "Message-ID"),
        )
        data = client.request(
            "POST",
            f"{_BASE}/messages/send",
            json_body={"raw": raw, "threadId": original.get("threadId")},
        )
        return {"gesendet": True, "message_id": data.get("id", "")}

    @mcp.tool()
    def google_mail_labels_liste() -> list[dict]:
        """Gibt alle verfuegbaren Gmail-Labels zurueck (Systemlabels wie
        INBOX/UNREAD/STARRED und eigene)."""
        data = client.request("GET", f"{_BASE}/labels")
        return [{"id": l.get("id", ""), "name": l.get("name", "")} for l in (data or {}).get("labels", [])]

    @mcp.tool()
    def google_mail_label_erstellen(name: str) -> dict:
        """Legt ein neues eigenes Gmail-Label an.

        name: Name des neuen Labels (kann mit "/" verschachtelt sein, z.B. "Projekt/Rechnungen").
        """
        data = client.request(
            "POST",
            f"{_BASE}/labels",
            json_body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        )
        return {"id": data.get("id", ""), "name": data.get("name", "")}

    @mcp.tool()
    def google_mail_label_anwenden(message_id: str, label_ids: list[str]) -> dict:
        """Fuegt einer Mail Labels hinzu (z.B. "STARRED" markieren,
        "UNREAD" entfernen ist ein separater Aufruf mit google_mail_label_entfernen).

        label_ids: aus google_mail_labels_liste() (Feld "id").
        """
        client.request(
            "POST", f"{_BASE}/messages/{message_id}/modify", json_body={"addLabelIds": label_ids}
        )
        return {"ausgefuehrt": True}

    @mcp.tool()
    def google_mail_label_entfernen(message_id: str, label_ids: list[str]) -> dict:
        """Entfernt Labels von einer Mail (z.B. "UNREAD" entfernen = als gelesen markieren).

        label_ids: aus google_mail_labels_liste() (Feld "id").
        """
        client.request(
            "POST", f"{_BASE}/messages/{message_id}/modify", json_body={"removeLabelIds": label_ids}
        )
        return {"ausgefuehrt": True}

    @mcp.tool()
    def google_mail_papierkorb(message_id: str, bestaetigt: bool = False) -> dict:
        """Verschiebt eine Mail in den Papierkorb (dort noch 30 Tage
        wiederherstellbar, keine sofortige endgueltige Loeschung) --
        braucht bestaetigt=True.

        message_id: aus google_mails_suchen()/google_mail_lesen().
        Erst beim Nutzer nachfragen, dann mit bestaetigt=True wiederholen.
        """
        guard = confirm_or_explain(bestaetigt, f"Mail {message_id} in den Papierkorb verschieben")
        if guard:
            return guard
        client.request("POST", f"{_BASE}/messages/{message_id}/trash")
        return {"ausgefuehrt": True}
