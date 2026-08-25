"""Ida-Google MCP Server (MCP-Port).

Werkzeuge fuer Google-Dienste (Tasks, Kontakte, ... -- waechst schrittweise,
siehe app/services/), abgesichert per Bearer-Token wie bei
Ida-Untis/Ida-Telegram/Ida-Memory. Die eigentliche Google-Anmeldung passiert
NICHT hier, sondern einmalig auf dem separaten Auth-Port (app/auth_app.py,
gedacht fuer Cloudflare Zero Trust Access) -- dieser Port hier braucht dafuer
nur den bereits gespeicherten Refresh-Token (app/google_auth.py) und einen
Bearer-Token pro Anfrage, genau wie die anderen drei Ida-*-MCP-Server.

Neue Google-Dienste kommen als eigenes Modul unter app/services/ dazu --
jedes definiert seine eigenen SCOPES (fuer die Authorize-URL) und eine
register_tools(mcp, client)-Funktion. server.py sammelt nur ein.
"""

from __future__ import annotations

import logging

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from app.auth import BearerAuthMiddleware
from app.config import load_settings
from app.google_auth import GoogleAuthManager
from app.google_client import GoogleApiClient
from app.services import calendar, chat, contacts, docs, gmail, meet, sheets, slides, tasks

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("ida-google")

# notes (Google Keep) bewusst NICHT eingehaengt: Googles eigene Doku
# beschreibt die Keep API als fuer Unternehmensumgebungen gedacht, und ein
# echter Authorize-Versuch mit einem privaten Google-Konto wurde von Google
# mit "invalid_scope" abgelehnt -- der Scope laesst sich fuer ein normales
# Konto offenbar strukturell nicht vergeben. Da alle Scopes in einer
# Anfrage zusammen angefordert werden, blockierte der eine kaputte Scope
# die Anmeldung fuer alle anderen Dienste gleich mit. Modul bleibt im Code
# (app/services/notes.py) fuer den Fall, dass sich das aendert (z.B. mit
# einem Workspace-Konto) -- dann hier wieder eintragen.
_SERVICE_MODULES = [tasks, contacts, calendar, gmail, docs, sheets, slides, chat, meet]
ALL_SCOPES = sorted({scope for module in _SERVICE_MODULES for scope in module.SCOPES})

settings = load_settings()
google = GoogleAuthManager(settings, ALL_SCOPES)
client = GoogleApiClient(google)

mcp = FastMCP(
    "Ida-Google",
    instructions=(
        "Werkzeuge fuer Google-Dienste (Tasks, Kontakte, Kalender, Gmail, "
        "Docs, Sheets, Slides, Chat, Meet -- weitere kommen dazu) -- alle "
        "fuer genau den einen Google-Account, der einmalig ueber den "
        "separaten Auth-Port verbunden wurde. google_verbindung_status "
        "zuerst aufrufen, wenn ein Tool einen Verbindungsfehler meldet -- "
        "zeigt, ob die Google-Anmeldung ueberhaupt schon gemacht wurde. "
        "google_mail_senden, google_mail_antworten, google_mail_entwurf_senden "
        "und google_chat_nachricht_senden verschicken sofort und "
        "unwiderruflich -- vor dem Senden immer den Inhalt mit dem Nutzer "
        "bestaetigen, nicht eigenmaechtig senden. "
        "LOESCHEN: Alle Tools, die Daten unwiderruflich entfernen (Name "
        "endet auf '_loeschen', dazu google_mail_papierkorb und "
        "google_sheet_bereich_leeren), haben einen bestaetigt-Parameter "
        "(Standard False) -- ohne bestaetigt=True passiert nichts, sie "
        "geben nur einen Hinweis zurueck. Immer zuerst beim Nutzer im Chat "
        "nachfragen und explizit bestaetigen lassen, danach den Aufruf mit "
        "bestaetigt=True wiederholen. AUSNAHME: google_termin_loeschen "
        "(Kalender) braucht keine Bestaetigung und darf direkt ausgefuehrt "
        "werden -- das ist so gewuenscht, damit Terminaenderungen schnell "
        "gehen."
    ),
    host=settings.mcp_host,
    port=settings.mcp_port,
)


@mcp.tool()
def google_verbindung_status() -> dict:
    """Prueft, ob dieser Server bereits mit einem Google-Account verbunden ist.

    Sagt nichts ueber einzelne Dienste/Scopes aus -- nur ob ueberhaupt ein
    Refresh-Token gespeichert ist. Wenn nicht: der Kontoinhaber muss einmalig
    die /authorize-Seite des separaten Auth-Ports aufrufen.
    """
    return {"verbunden": google.is_connected()}


for _module in _SERVICE_MODULES:
    _module.register_tools(mcp, client)


async def healthz(request):
    return JSONResponse({"status": "ok"})


def build_mcp_app():
    app = mcp.streamable_http_app()
    app.add_route("/healthz", healthz, methods=["GET"])
    app.add_middleware(BearerAuthMiddleware, token=settings.mcp_auth_token)
    return app


def main() -> None:
    """Nur fuer lokale Einzel-Tests (z.B. Tool-Liste pruefen) -- im Container
    startet app/main.py beide Ports zusammen in einem Prozess."""
    app = build_mcp_app()
    uvicorn.run(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
