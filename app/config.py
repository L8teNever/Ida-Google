"""Konfiguration des Ida-Google MCP Servers, komplett über Umgebungsvariablen."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Umgebungsvariable {name} fehlt oder ist leer.")
    return value


def _optional(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Postfach:
    """Ein zusaetzliches, NICHT-Google-Postfach per IMAP/SMTP (z.B. GMX,
    Web.de, Outlook, eine eigene Domain) -- unabhaengig vom einen
    Google-Account, den dieser Server sonst per OAuth verwaltet."""

    name: str
    email: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    username: str
    password: str


_MAILBOX_VAR_PATTERN = re.compile(
    r"^MAILBOX_(\d+)_(NAME|EMAIL|IMAP_HOST|IMAP_PORT|SMTP_HOST|SMTP_PORT|USERNAME|PASSWORD)$"
)


def _postfaecher_aus_umgebung_lesen() -> dict[str, Postfach]:
    """Scannt die Umgebung selbst nach MAILBOX_<N>_*-Variablen -- kein fester
    Deckel, wie viele zusaetzliche Postfaecher es gibt (analog zu Ida-Reminders
    REMINDER_SLOT_<N>_*-Muster). Komplett optional: ohne eine einzige
    MAILBOX_1_*-Variable bleibt das Feature einfach abgeschaltet, bestehende
    Ida-Google-Deployments ohne dieses Feature brauchen keine Aenderung."""
    gefunden: dict[int, dict[str, str]] = {}
    for env_name, value in os.environ.items():
        match = _MAILBOX_VAR_PATTERN.match(env_name)
        if not match:
            continue
        wert = value.strip()
        if not wert:
            continue
        nummer = int(match.group(1))
        gefunden.setdefault(nummer, {})[match.group(2)] = wert

    postfaecher: dict[str, Postfach] = {}
    namen_gesehen: set[str] = set()
    for nummer, werte in sorted(gefunden.items()):
        fehlend = [
            feld for feld in ("NAME", "EMAIL", "IMAP_HOST", "SMTP_HOST", "PASSWORD")
            if not werte.get(feld)
        ]
        if fehlend:
            raise ConfigError(
                f"MAILBOX_{nummer}_*: {', '.join('MAILBOX_' + str(nummer) + '_' + f for f in fehlend)} "
                "fehlt -- NAME/EMAIL/IMAP_HOST/SMTP_HOST/PASSWORD sind Pflicht, "
                "IMAP_PORT/SMTP_PORT/USERNAME sind optional."
            )
        name = werte["NAME"]
        if name in namen_gesehen:
            raise ConfigError(
                f"MAILBOX_{nummer}_NAME={name!r} ist nicht eindeutig -- jeder "
                "Postfach-Name muss einmalig sein, er wird als postfach-Parameter benutzt."
            )
        namen_gesehen.add(name)
        postfaecher[name] = Postfach(
            name=name,
            email=werte["EMAIL"],
            imap_host=werte["IMAP_HOST"],
            imap_port=int(werte.get("IMAP_PORT", "993")),
            smtp_host=werte["SMTP_HOST"],
            smtp_port=int(werte.get("SMTP_PORT", "587")),
            username=werte.get("USERNAME", werte["EMAIL"]),
            password=werte["PASSWORD"],
        )
    return postfaecher


def _require_min_length(name: str, min_length: int) -> str:
    value = _require(name)
    if len(value) < min_length:
        raise ConfigError(
            f"{name} ist zu kurz (mind. {min_length} Zeichen). "
            "Erzeuge z.B. mit: openssl rand -hex 32"
        )
    return value


@dataclass(frozen=True)
class Settings:
    # OAuth-Client, in der Google Cloud Console angelegt (Typ "Web
    # Application"). google_redirect_uri muss dort 1:1 als "Autorisierte
    # Weiterleitungs-URI" eingetragen sein.
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str

    # MCP-Port: die eigentlichen Google-Werkzeuge, per Bearer-Token
    # abgesichert wie bei Ida-Untis/Ida-Telegram/Ida-Memory.
    mcp_auth_token: str
    mcp_host: str
    mcp_port: int

    # Auth-Port: nur fuer den einmaligen (oder bei neuen Scopes erneuten)
    # Google-Anmelde-Flow. Gedacht, um zusaetzlich hinter Cloudflare Zero
    # Trust Access zu liegen -- auth_token ist nur ein zusaetzliches,
    # kostenloses Sicherheitsnetz, falls das mal nicht greift.
    auth_host: str
    auth_port: int
    auth_token: str

    # Wo der Google-Refresh-Token dauerhaft gespeichert wird (Docker-Volume).
    token_file_path: str

    # Zusaetzliche, NICHT-Google-Postfaecher per IMAP/SMTP -- optional,
    # Schluessel ist der Postfach-Name (MAILBOX_<N>_NAME).
    postfaecher: dict[str, Postfach]


def load_settings() -> Settings:
    try:
        mcp_auth_token = _require_min_length("MCP_AUTH_TOKEN", 16)
        auth_token = _require_min_length("AUTH_TOKEN", 16)

        settings = Settings(
            google_client_id=_require("GOOGLE_CLIENT_ID"),
            google_client_secret=_require("GOOGLE_CLIENT_SECRET"),
            google_redirect_uri=_require("GOOGLE_REDIRECT_URI"),
            mcp_auth_token=mcp_auth_token,
            mcp_host=_optional("MCP_HOST", "0.0.0.0"),
            mcp_port=int(_optional("MCP_PORT", "4569")),
            auth_host=_optional("AUTH_HOST", "0.0.0.0"),
            auth_port=int(_optional("AUTH_PORT", "4570")),
            auth_token=auth_token,
            token_file_path=_optional("GOOGLE_TOKEN_FILE_PATH", "/data/google_token.json"),
            postfaecher=_postfaecher_aus_umgebung_lesen(),
        )
    except ConfigError as exc:
        print(f"[Ida-Google] Konfigurationsfehler: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    return settings
