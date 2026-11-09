"""Google Drive -- Dateien, die diese App selbst anlegt (Scope drive.file, kein Zugriff auf fremde Dateien).

Der Scope steht vor allem hier, damit die einmalige Anmeldung ihn mit abdeckt: andere Dienste im Stack (z.B. IDA Docs fuer sein
Backup) nutzen denselben gespeicherten Refresh-Token und holen sich damit selbst einen Access-Token.
"""

from __future__ import annotations

import json

import requests

from app.google_client import GoogleApiClient, GoogleApiError

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

_BASE = "https://www.googleapis.com/drive/v3"
_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_drive_dateien_liste(ordner_id: str = "", maximal: int = 50) -> list[dict]:
        """Listet Dateien in Drive, die ueber diese Verbindung angelegt wurden (id, name, typ, geaendert).

        ordner_id: optional -- nur Dateien in diesem Ordner.
        """
        q = "trashed = false" + (f" and '{ordner_id}' in parents" if ordner_id else "")
        data = client.request(
            "GET", f"{_BASE}/files",
            params={"q": q, "pageSize": min(max(maximal, 1), 200), "fields": "files(id,name,mimeType,modifiedTime)", "orderBy": "modifiedTime desc"},
            scopes=SCOPES,
        )
        return [{"id": f["id"], "name": f["name"], "typ": f["mimeType"], "geaendert": f.get("modifiedTime")} for f in (data or {}).get("files", [])]

    @mcp.tool()
    def google_drive_textdatei_hochladen(name: str, inhalt: str, ordner_id: str = "", mime_typ: str = "text/plain") -> dict:
        """Legt eine neue Textdatei in Drive an (z.B. .md oder .json).

        name: Dateiname inkl. Endung. ordner_id: optional -- Zielordner. Gibt id und name zurueck.
        """
        meta: dict = {"name": name}
        if ordner_id:
            meta["parents"] = [ordner_id]
        boundary = "ida-google-b"
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
                f"--{boundary}\r\nContent-Type: {mime_typ}\r\n\r\n{inhalt}\r\n--{boundary}--").encode("utf-8")
        token = client._google.get_access_token(SCOPES)
        r = requests.post(f"{_UPLOAD}?uploadType=multipart&fields=id,name", timeout=30, data=body,
                          headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/related; boundary={boundary}"})
        if r.status_code >= 300:
            raise GoogleApiError(f"Google-API-Fehler: {r.text[:200]}")
        return r.json()
