"""Startet Auth-Port und MCP-Port zusammen in einem Prozess (ein Container,
zwei Ports -- siehe README fuer die Cloudflare-Tunnel-Aufteilung).

uvicorn.Server().serve() ist die fuer genau diesen Fall vorgesehene
Low-Level-API (im Gegensatz zu uvicorn.run(), das genau einen Server pro
Prozess annimmt) -- asyncio.gather laesst beide ASGI-Apps nebenlaeufig im
selben Event-Loop laufen, inklusive korrektem Lifespan-Start/-Stop fuer den
MCP-Session-Manager auf dem MCP-Port.
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from app.auth_app import build_auth_app
from app.server import build_mcp_app
from app.server import google as google_auth_manager
from app.server import settings

log = logging.getLogger("ida-google")


async def _run() -> None:
    auth_app = build_auth_app(settings, google_auth_manager)
    mcp_app = build_mcp_app()

    # access_log=False: uvicorn wuerde sonst jede Request-Zeile inkl. vollem
    # Pfad loggen -- und damit ein per ?token= mitgeschicktes AUTH_TOKEN/
    # MCP_AUTH_TOKEN im Klartext in die Docker-Logs schreiben.
    auth_server = uvicorn.Server(
        uvicorn.Config(
            auth_app,
            host=settings.auth_host,
            port=settings.auth_port,
            log_level="info",
            access_log=False,
        )
    )
    mcp_server = uvicorn.Server(
        uvicorn.Config(
            mcp_app,
            host=settings.mcp_host,
            port=settings.mcp_port,
            log_level="info",
            access_log=False,
        )
    )

    log.info(
        "Ida-Google startet -- Auth-Port %s:%s (/authorize, /oauth/callback), "
        "MCP-Port %s:%s (/mcp, /healthz)",
        settings.auth_host,
        settings.auth_port,
        settings.mcp_host,
        settings.mcp_port,
    )

    await asyncio.gather(auth_server.serve(), mcp_server.serve())


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
