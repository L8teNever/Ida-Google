"""Google Tasks -- Aufgabenlisten und Aufgaben lesen/erstellen/erledigen/loeschen.

API-Doku: https://developers.google.com/tasks/reference/rest
"""

from __future__ import annotations

from app.google_client import GoogleApiClient, confirm_or_explain

SCOPES = ["https://www.googleapis.com/auth/tasks"]

_BASE = "https://tasks.googleapis.com/tasks/v1"


def _liste_kurz(liste: dict) -> dict:
    return {"id": liste["id"], "titel": liste.get("title", "")}


def _aufgabe_kurz(task: dict) -> dict:
    return {
        "id": task["id"],
        "titel": task.get("title", ""),
        "notizen": task.get("notes", ""),
        "status": task.get("status", "needsAction"),
        "faellig": task.get("due"),
    }


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_aufgabenlisten() -> list[dict]:
        """Gibt alle Google Tasks-Aufgabenlisten zurueck (id + titel).

        Die id wird fuer google_aufgaben_liste/google_aufgabe_erstellen gebraucht.
        """
        data = client.request("GET", f"{_BASE}/users/@me/lists")
        return [_liste_kurz(l) for l in (data or {}).get("items", [])]

    @mcp.tool()
    def google_aufgaben_liste(tasklist_id: str, nur_offene: bool = True) -> list[dict]:
        """Gibt die Aufgaben einer Liste zurueck.

        tasklist_id: id aus google_aufgabenlisten().
        nur_offene: bei True (Standard) werden erledigte Aufgaben ausgeblendet.
        """
        data = client.request(
            "GET",
            f"{_BASE}/lists/{tasklist_id}/tasks",
            params={"showCompleted": not nur_offene, "showHidden": not nur_offene},
        )
        return [_aufgabe_kurz(t) for t in (data or {}).get("items", [])]

    @mcp.tool()
    def google_aufgabe_erstellen(tasklist_id: str, titel: str, notizen: str = "", faellig: str = "") -> dict:
        """Legt eine neue Aufgabe an.

        tasklist_id: id aus google_aufgabenlisten().
        titel: Aufgabentext.
        notizen: optionale Beschreibung.
        faellig: optionales Faelligkeitsdatum als "YYYY-MM-DD" (wird zu RFC3339 ergaenzt).
        """
        body: dict = {"title": titel}
        if notizen:
            body["notes"] = notizen
        if faellig:
            body["due"] = f"{faellig}T00:00:00.000Z"
        data = client.request("POST", f"{_BASE}/lists/{tasklist_id}/tasks", json_body=body)
        return _aufgabe_kurz(data)

    @mcp.tool()
    def google_aufgabe_erledigt(tasklist_id: str, task_id: str) -> dict:
        """Markiert eine Aufgabe als erledigt.

        tasklist_id/task_id: aus google_aufgabenlisten()/google_aufgaben_liste().
        """
        data = client.request(
            "PATCH",
            f"{_BASE}/lists/{tasklist_id}/tasks/{task_id}",
            json_body={"status": "completed"},
        )
        return _aufgabe_kurz(data)

    @mcp.tool()
    def google_aufgabe_loeschen(tasklist_id: str, task_id: str, bestaetigt: bool = False) -> dict:
        """Loescht eine Aufgabe unwiderruflich -- braucht bestaetigt=True.

        tasklist_id/task_id: aus google_aufgabenlisten()/google_aufgaben_liste().
        Erst beim Nutzer nachfragen, dann mit bestaetigt=True wiederholen.
        """
        guard = confirm_or_explain(bestaetigt, f"Aufgabe {task_id} endgueltig loeschen")
        if guard:
            return guard
        client.request("DELETE", f"{_BASE}/lists/{tasklist_id}/tasks/{task_id}")
        return {"ausgefuehrt": True}
