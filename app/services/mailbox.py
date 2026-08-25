"""Zusaetzliche, NICHT-Google-Postfaecher per IMAP/SMTP (z.B. GMX, Web.de,
Outlook/Office365, eine eigene Domain) -- unabhaengig vom einen
Google-Account, den dieser Server sonst per OAuth verwaltet. Konfiguriert
ueber MAILBOX_<N>_*-Umgebungsvariablen (siehe app/config.py), komplett
optional -- ohne konfiguriertes Postfach werden hier keine Tools registriert.

Bewusst NICHT unter app/services/ mit den anderen Google-Diensten registriert
(server.py's _SERVICE_MODULES-Schleife) -- die dortigen Module teilen sich
alle denselben GoogleApiClient, dieses Modul braucht stattdessen die
Postfach-Konfiguration und wird deshalb separat eingehaengt.

Tool-Namen bewusst mit postfach_ statt google_ prefixed, um klar zu machen:
das hat NICHTS mit dem Google-Account zu tun. Funktionsumfang orientiert
sich an den Gmail-Tools (suchen/lesen/senden/antworten), aber ohne
Labels/Entwuerfe/Papierkorb -- das sind Gmail-spezifische Konzepte ohne
sauberes, universelles IMAP-Aequivalent und wurden nicht angefragt.
"""

from __future__ import annotations

from mcp.server.fastmcp import Image

from app.config import Postfach
from app.mailbox_client import MailboxError, anhang_holen, antworten, mail_lesen, mails_suchen, ordner_liste, senden

SCOPES: list[str] = []  # kein Google-Scope -- IMAP/SMTP braucht kein OAuth


def _postfach_holen(postfaecher: dict[str, Postfach], name: str) -> Postfach:
    postfach = postfaecher.get(name)
    if postfach is None:
        verfuegbar = ", ".join(sorted(postfaecher)) or "keine konfiguriert"
        raise ValueError(f"Unbekanntes Postfach '{name}'. Verfuegbar: {verfuegbar}.")
    return postfach


def register_tools(mcp, postfaecher: dict[str, Postfach]) -> None:
    if not postfaecher:
        return  # kein MAILBOX_1_* konfiguriert -- Feature bleibt komplett abgeschaltet

    @mcp.tool()
    def postfach_liste() -> list[dict]:
        """Zeigt alle konfigurierten externen Postfaecher (Name + Adresse,
        keine Zugangsdaten) -- der Name ist der postfach-Parameter fuer alle
        anderen postfach_*-Tools."""
        return [{"name": p.name, "email": p.email} for p in postfaecher.values()]

    @mcp.tool()
    def postfach_ordner_liste(postfach: str) -> list[str]:
        """Zeigt alle IMAP-Ordner eines Postfachs (Namen sind je nach Anbieter
        unterschiedlich, z.B. "INBOX", "Sent", "Gesendet", "Trash" -- deshalb
        vor postfach_mails_suchen/postfach_mail_lesen mit unbekanntem ordner
        einmal hier nachschauen)."""
        try:
            return ordner_liste(_postfach_holen(postfaecher, postfach))
        except MailboxError as exc:
            raise ValueError(str(exc)) from exc

    @mcp.tool()
    def postfach_mails_suchen(postfach: str, query: str = "", ordner: str = "INBOX", max_ergebnisse: int = 10) -> list[dict]:
        """Durchsucht Betreff und Absender eines IMAP-Ordners (einfache
        Textsuche, kein Vorschautext wie bei Gmail -- dafuer postfach_mail_lesen).

        query: leer = keine Einschraenkung (alle Mails im Ordner).
        max_ergebnisse: 1-25, Standard 10, neueste zuerst.
        """
        max_ergebnisse = max(1, min(max_ergebnisse, 25))
        try:
            return mails_suchen(_postfach_holen(postfaecher, postfach), query, ordner, max_ergebnisse)
        except MailboxError as exc:
            raise ValueError(str(exc)) from exc

    @mcp.tool()
    def postfach_mail_lesen(postfach: str, mail_id: str, ordner: str = "INBOX") -> dict:
        """Gibt eine einzelne Mail vollstaendig zurueck (Kopfzeilen + Text +
        Anhang-Liste). Markiert die Mail NICHT als gelesen.

        mail_id: aus postfach_mails_suchen(). Wenn keine reine Textversion
        existiert (z.B. eine reine HTML-Mail), steht das im Feld "text" statt
        eines geratenen/kaputten Auszugs. Anhaenge stehen nur als Metadaten da
        (Name/Groesse/mimetyp/index) -- den Inhalt liefert postfach_anhang_herunterladen.
        """
        try:
            return mail_lesen(_postfach_holen(postfaecher, postfach), mail_id, ordner)
        except MailboxError as exc:
            raise ValueError(str(exc)) from exc

    @mcp.tool()
    def postfach_anhang_herunterladen(postfach: str, mail_id: str, index: int, ordner: str = "INBOX") -> list:
        """Laedt einen Mail-Anhang herunter -- Bilder als echten Bildinhalt,
        alles andere nur als Metadaten-Hinweis (der Inhalt laesst sich hier
        nicht anzeigen).

        mail_id/index: aus postfach_mail_lesen() (Feld "anhaenge", index dort).
        """
        try:
            rohdaten, dateiname, mimetyp = anhang_holen(_postfach_holen(postfaecher, postfach), mail_id, index, ordner)
        except MailboxError as exc:
            raise ValueError(str(exc)) from exc

        endung = dateiname.rsplit(".", 1)[-1].lower() if "." in dateiname else ""
        if endung in ("jpg", "jpeg", "png", "gif", "webp"):
            bildformat = "jpeg" if endung == "jpg" else endung
            return [Image(data=rohdaten, format=bildformat)]
        return [f"Anhang '{dateiname or index}' ist kein Bild ({len(rohdaten)} Bytes) -- Inhalt kann hier nicht angezeigt werden."]

    @mcp.tool()
    def postfach_senden(
        postfach: str, an: str, betreff: str, text: str, cc: str = "", bcc: str = "",
        anhaenge: list[dict] | None = None,
    ) -> dict:
        """Sendet eine neue E-Mail ueber ein konfiguriertes externes Postfach
        per SMTP (kein Reply -- dafuer postfach_antworten).

        postfach: Name aus postfach_liste(). an/cc/bcc: E-Mail-Adressen,
        mehrere durch Komma getrennt. anhaenge: optionale Liste von
        {"dateiname": str, "mimetyp": str, "inhalt_base64": str}.
        Verschickt sofort und unwiderruflich -- vor dem Aufruf immer den
        Inhalt mit dem Nutzer bestaetigen.
        """
        try:
            senden(_postfach_holen(postfaecher, postfach), an, betreff, text, cc, bcc, anhaenge)
        except MailboxError as exc:
            raise ValueError(str(exc)) from exc
        return {"gesendet": True}

    @mcp.tool()
    def postfach_antworten(postfach: str, mail_id: str, text: str, an_alle: bool = False, ordner: str = "INBOX") -> dict:
        """Antwortet auf eine bestehende Mail (mit korrekten
        In-Reply-To/References-Kopfzeilen, erscheint beim Empfaenger als
        Antwort in derselben Unterhaltung statt als neue Mail).

        mail_id: aus postfach_mails_suchen()/postfach_mail_lesen().
        an_alle: bei True geht auch das urspruengliche Cc mit.
        Verschickt sofort und unwiderruflich -- vor dem Aufruf immer den
        Inhalt mit dem Nutzer bestaetigen.
        """
        try:
            antworten(_postfach_holen(postfaecher, postfach), mail_id, text, an_alle, ordner)
        except MailboxError as exc:
            raise ValueError(str(exc)) from exc
        return {"gesendet": True}
