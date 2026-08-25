"""Duenner IMAP/SMTP-Helfer fuer zusaetzliche, NICHT-Google-Postfaecher
(app/config.py: Postfach, aus MAILBOX_<N>_*-Umgebungsvariablen).

Jeder Aufruf oeffnet eine frische IMAP-/SMTP-Verbindung und schliesst sie
danach wieder -- kein Connection-Pooling ueber Tool-Aufrufe hinweg (analog
zum "frische Verbindung pro Aufruf"-Muster von Ida-SSH). IMAP-Server trennen
inaktive Verbindungen ohnehin nach einer Weile, eine lang lebende Session
waere hier nur zusaetzliche Fehlerquelle ohne echten Vorteil.

Nutzt ausschliesslich die Python-Standardbibliothek (imaplib/smtplib/email)
-- keine neue Abhaengigkeit noetig, dieselbe email-Bibliothek wie
app/services/gmail.py fuer den RFC822-Nachrichtenbau/die MIME-Zerlegung.
"""

from __future__ import annotations

import base64
import imaplib
import re
import smtplib
from email import message_from_bytes
from email.header import decode_header
from email.message import EmailMessage, Message
from typing import Any

from app.config import Postfach


class MailboxError(RuntimeError):
    """Fehler, die 1:1 als verstaendliche Meldung an den MCP-Client zurueckgehen sollen."""


def _header_decode(value: str | None) -> str:
    """Kopfzeilen sind bei Umlauten im Betreff/Anzeigenamen oft RFC2047-kodiert
    (z.B. '=?UTF-8?B?...?=') -- email.header.decode_header loest das auf."""
    if not value:
        return ""
    teile = decode_header(value)
    ergebnis = []
    for text, kodierung in teile:
        if isinstance(text, bytes):
            ergebnis.append(text.decode(kodierung or "utf-8", errors="replace"))
        else:
            ergebnis.append(text)
    return "".join(ergebnis)


def _quote_mailbox(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _imap_connect(postfach: Postfach) -> imaplib.IMAP4_SSL:
    try:
        conn = imaplib.IMAP4_SSL(postfach.imap_host, postfach.imap_port)
        conn.login(postfach.username, postfach.password)
    except (imaplib.IMAP4.error, OSError) as exc:
        raise MailboxError(f"IMAP-Verbindung zu Postfach '{postfach.name}' fehlgeschlagen: {exc}") from exc
    return conn


def _imap_select(conn: imaplib.IMAP4_SSL, postfach: Postfach, ordner: str) -> None:
    status, _ = conn.select(_quote_mailbox(ordner), readonly=True)
    if status != "OK":
        raise MailboxError(f"Ordner '{ordner}' in Postfach '{postfach.name}' nicht gefunden.")


def _smtp_connect(postfach: Postfach) -> smtplib.SMTP:
    try:
        if postfach.smtp_port == 465:
            conn: smtplib.SMTP = smtplib.SMTP_SSL(postfach.smtp_host, postfach.smtp_port, timeout=30)
        else:
            conn = smtplib.SMTP(postfach.smtp_host, postfach.smtp_port, timeout=30)
            conn.starttls()
        conn.login(postfach.username, postfach.password)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailboxError(f"SMTP-Verbindung zu Postfach '{postfach.name}' fehlgeschlagen: {exc}") from exc
    return conn


_LIST_RESPONSE_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.+)$')


def ordner_liste(postfach: Postfach) -> list[str]:
    conn = _imap_connect(postfach)
    try:
        status, daten = conn.list()
        if status != "OK":
            raise MailboxError(f"Ordnerliste von Postfach '{postfach.name}' fehlgeschlagen.")
        ordner = []
        for zeile in daten:
            match = _LIST_RESPONSE_RE.match(zeile.decode("utf-8", errors="replace"))
            if not match:
                continue
            name = match.group("name").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
            ordner.append(name)
        return ordner
    finally:
        conn.logout()


def _uids_suchen(conn: imaplib.IMAP4_SSL, postfach: Postfach, query: str, max_ergebnisse: int) -> list[str]:
    if query:
        # OR-Suche ueber Betreff und Absender -- kein CHARSET-Parameter (nicht
        # jeder Server unterstuetzt UTF-8 dafuer), funktioniert bei den meisten
        # Servern trotzdem auch mit Umlauten in Anfuehrungszeichen.
        kriterium = f'(OR (SUBJECT "{query}") (FROM "{query}"))'
        status, daten = conn.uid("search", None, kriterium)
    else:
        status, daten = conn.uid("search", None, "ALL")
    if status != "OK":
        raise MailboxError(f"Suche in Postfach '{postfach.name}' fehlgeschlagen.")
    uids = [u.decode() for u in daten[0].split()] if daten and daten[0] else []
    uids.reverse()  # IMAP liefert aufsteigend nach UID -- neueste zuerst ist nuetzlicher
    return uids[:max_ergebnisse]


def mails_suchen(postfach: Postfach, query: str, ordner: str, max_ergebnisse: int) -> list[dict]:
    conn = _imap_connect(postfach)
    try:
        _imap_select(conn, postfach, ordner)
        uids = _uids_suchen(conn, postfach, query, max_ergebnisse)
        ergebnisse = []
        for uid in uids:
            status, daten = conn.uid(
                "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)] FLAGS)"
            )
            if status != "OK" or not daten or daten[0] is None:
                continue
            kopf = daten[0]
            roh = kopf[1] if isinstance(kopf, tuple) else b""
            flags_text = kopf[0].decode("utf-8", errors="replace") if isinstance(kopf, tuple) else ""
            nachricht = message_from_bytes(roh)
            ergebnisse.append(
                {
                    "id": uid,
                    "betreff": _header_decode(nachricht.get("Subject", "")),
                    "von": _header_decode(nachricht.get("From", "")),
                    "datum": nachricht.get("Date", ""),
                    "gelesen": "\\Seen" in flags_text,
                }
            )
        return ergebnisse
    finally:
        conn.logout()


def _find_plain_text(msg: Message) -> str | None:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                if payload is not None:
                    zeichensatz = part.get_content_charset() or "utf-8"
                    return payload.decode(zeichensatz, errors="replace")
        return None
    if msg.get_content_type() == "text/plain":
        payload = msg.get_payload(decode=True)
        if payload is None:
            return None
        zeichensatz = msg.get_content_charset() or "utf-8"
        return payload.decode(zeichensatz, errors="replace")
    return None


def _find_attachments(msg: Message) -> list[dict]:
    gefunden = []
    if not msg.is_multipart():
        return gefunden
    for index, part in enumerate(msg.walk()):
        dateiname = part.get_filename()
        if dateiname:
            gefunden.append(
                {
                    "index": index,
                    "dateiname": _header_decode(dateiname),
                    "mimetyp": part.get_content_type(),
                    "groesse_bytes": len(part.get_payload(decode=True) or b""),
                }
            )
    return gefunden


def _mail_holen(postfach: Postfach, mail_id: str, ordner: str) -> Message:
    conn = _imap_connect(postfach)
    try:
        _imap_select(conn, postfach, ordner)
        # BODY.PEEK statt BODY: liest die Mail, OHNE sie als gelesen zu
        # markieren -- Verhalten bewusst analog zu Gmails messages.get, das
        # ebenfalls keine Labels/Flags durch das blosse Lesen aendert.
        status, daten = conn.uid("fetch", mail_id, "(BODY.PEEK[])")
        if status != "OK" or not daten or daten[0] is None:
            raise MailboxError(f"Mail '{mail_id}' in Ordner '{ordner}' (Postfach '{postfach.name}') nicht gefunden.")
        roh = daten[0][1] if isinstance(daten[0], tuple) else b""
        return message_from_bytes(roh)
    finally:
        conn.logout()


def mail_lesen(postfach: Postfach, mail_id: str, ordner: str) -> dict:
    msg = _mail_holen(postfach, mail_id, ordner)
    text = _find_plain_text(msg)
    return {
        "id": mail_id,
        "ordner": ordner,
        "betreff": _header_decode(msg.get("Subject", "")),
        "von": _header_decode(msg.get("From", "")),
        "an": _header_decode(msg.get("To", "")),
        "datum": msg.get("Date", ""),
        "text": text if text is not None else "(keine reine Textversion gefunden -- evtl. nur HTML)",
        "anhaenge": _find_attachments(msg),
    }


def anhang_holen(postfach: Postfach, mail_id: str, index: int, ordner: str) -> tuple[bytes, str, str]:
    """Gibt (rohe Bytes, Dateiname, Mimetyp) zurueck. index kommt aus dem
    Feld "index" der anhaenge-Liste von mail_lesen() -- fuer dieselbe Mail
    stabil, da beide Male derselbe rohe Nachrichteninhalt geparst wird."""
    msg = _mail_holen(postfach, mail_id, ordner)
    if not msg.is_multipart():
        raise MailboxError(f"Mail '{mail_id}' hat keine Anhaenge.")
    for i, part in enumerate(msg.walk()):
        if i == index and part.get_filename():
            inhalt = part.get_payload(decode=True) or b""
            return inhalt, _header_decode(part.get_filename()), part.get_content_type()
    raise MailboxError(f"Kein Anhang mit index={index} in Mail '{mail_id}' gefunden.")


def _build_message(
    postfach: Postfach, an: str, betreff: str, text: str, cc: str, bcc: str,
    anhaenge: list[dict] | None, in_reply_to: str = "", references: str = "",
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = postfach.email
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
    return msg


def _empfaenger_liste(*adressfelder: str) -> list[str]:
    alle = ",".join(feld for feld in adressfelder if feld)
    return [a.strip() for a in alle.split(",") if a.strip()]


def senden(
    postfach: Postfach, an: str, betreff: str, text: str, cc: str, bcc: str,
    anhaenge: list[dict] | None,
) -> None:
    msg = _build_message(postfach, an, betreff, text, cc, bcc, anhaenge)
    empfaenger = _empfaenger_liste(an, cc, bcc)
    conn = _smtp_connect(postfach)
    try:
        conn.send_message(msg, from_addr=postfach.email, to_addrs=empfaenger)
    except smtplib.SMTPException as exc:
        raise MailboxError(f"Senden ueber Postfach '{postfach.name}' fehlgeschlagen: {exc}") from exc
    finally:
        conn.quit()


def antworten(postfach: Postfach, mail_id: str, text: str, an_alle: bool, ordner: str) -> None:
    original = _mail_holen(postfach, mail_id, ordner)

    betreff = _header_decode(original.get("Subject", ""))
    if not betreff.lower().startswith("re:"):
        betreff = f"Re: {betreff}"

    an = original.get("From", "") or ""
    cc = (original.get("Cc", "") or "") if an_alle else ""

    msg = _build_message(
        postfach, an=an, betreff=betreff, text=text, cc=cc, bcc="", anhaenge=None,
        in_reply_to=original.get("Message-ID", "") or "",
    )
    empfaenger = _empfaenger_liste(an, cc)
    conn = _smtp_connect(postfach)
    try:
        conn.send_message(msg, from_addr=postfach.email, to_addrs=empfaenger)
    except smtplib.SMTPException as exc:
        raise MailboxError(f"Antworten ueber Postfach '{postfach.name}' fehlgeschlagen: {exc}") from exc
    finally:
        conn.quit()
