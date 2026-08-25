"""Konfiguration des Ida-Google MCP Servers, komplett über Umgebungsvariablen."""

from __future__ import annotations

import os
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
        )
    except ConfigError as exc:
        print(f"[Ida-Google] Konfigurationsfehler: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    return settings
