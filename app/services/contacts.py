"""Google Kontakte (People API) -- lesen, erstellen, Details abrufen.

API-Doku: https://developers.google.com/people/api/rest
"""

from __future__ import annotations

from app.google_client import GoogleApiClient

SCOPES = ["https://www.googleapis.com/auth/contacts"]

_BASE = "https://people.googleapis.com/v1"
_PERSON_FIELDS = "names,emailAddresses,phoneNumbers"


def _kontakt_kurz(person: dict) -> dict:
    namen = person.get("names") or [{}]
    emails = person.get("emailAddresses") or []
    telefone = person.get("phoneNumbers") or []
    return {
        "resource_name": person.get("resourceName", ""),
        "name": namen[0].get("displayName", ""),
        "emails": [e.get("value", "") for e in emails],
        "telefonnummern": [t.get("value", "") for t in telefone],
    }


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_kontakte_liste(max_ergebnisse: int = 50) -> list[dict]:
        """Gibt Kontakte zurueck (Name, E-Mails, Telefonnummern).

        max_ergebnisse: 1-1000, Standard 50 -- klein halten, um nicht
        unnoetig viele Tokens fuer einen langen Kontakt-Export zu verbrauchen.
        """
        data = client.request(
            "GET",
            f"{_BASE}/people/me/connections",
            params={
                "personFields": _PERSON_FIELDS,
                "pageSize": max(1, min(max_ergebnisse, 1000)),
            },
        )
        return [_kontakt_kurz(p) for p in (data or {}).get("connections", [])]

    @mcp.tool()
    def google_kontakt_erstellen(vorname: str, nachname: str = "", email: str = "", telefon: str = "") -> dict:
        """Legt einen neuen Kontakt an.

        vorname: Pflicht. nachname/email/telefon: optional.
        """
        person: dict = {"names": [{"givenName": vorname, "familyName": nachname}]}
        if email:
            person["emailAddresses"] = [{"value": email}]
        if telefon:
            person["phoneNumbers"] = [{"value": telefon}]

        data = client.request(
            "POST",
            f"{_BASE}/people:createContact",
            params={"personFields": _PERSON_FIELDS},
            json_body=person,
        )
        return _kontakt_kurz(data)

    @mcp.tool()
    def google_kontakt_details(resource_name: str) -> dict:
        """Gibt Details zu einem Kontakt zurueck.

        resource_name: aus google_kontakte_liste() (Feld "resource_name", z.B. "people/c12345").
        """
        data = client.request(
            "GET",
            f"{_BASE}/{resource_name}",
            params={"personFields": _PERSON_FIELDS},
        )
        return _kontakt_kurz(data)
