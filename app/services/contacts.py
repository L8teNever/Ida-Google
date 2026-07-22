"""Google Kontakte (People API) -- lesen, erstellen, Details abrufen.

API-Doku: https://developers.google.com/people/api/rest
"""

from __future__ import annotations

from app.google_client import GoogleApiClient, confirm_or_explain

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

    @mcp.tool()
    def google_kontakt_aktualisieren(
        resource_name: str, vorname: str = "", nachname: str = "", email: str = "", telefon: str = ""
    ) -> dict:
        """Aendert einzelne Felder eines bestehenden Kontakts (nur angegebene
        Felder werden ersetzt, leere Parameter bleiben unangetastet).

        resource_name: aus google_kontakte_liste()/google_kontakt_details().
        """
        aktuell = client.request(
            "GET", f"{_BASE}/{resource_name}", params={"personFields": _PERSON_FIELDS}
        )
        person: dict = {"etag": aktuell["etag"]}
        update_felder = []

        if vorname or nachname:
            bisheriger_name = (aktuell.get("names") or [{}])[0]
            person["names"] = [
                {
                    "givenName": vorname or bisheriger_name.get("givenName", ""),
                    "familyName": nachname or bisheriger_name.get("familyName", ""),
                }
            ]
            update_felder.append("names")
        if email:
            person["emailAddresses"] = [{"value": email}]
            update_felder.append("emailAddresses")
        if telefon:
            person["phoneNumbers"] = [{"value": telefon}]
            update_felder.append("phoneNumbers")

        data = client.request(
            "PATCH",
            f"{_BASE}/{resource_name}:updateContact",
            params={"updatePersonFields": ",".join(update_felder), "personFields": _PERSON_FIELDS},
            json_body=person,
        )
        return _kontakt_kurz(data)

    @mcp.tool()
    def google_kontakt_loeschen(resource_name: str, bestaetigt: bool = False) -> dict:
        """Loescht einen Kontakt unwiderruflich -- braucht bestaetigt=True.

        resource_name: aus google_kontakte_liste()/google_kontakt_details().
        Erst beim Nutzer nachfragen, dann mit bestaetigt=True wiederholen.
        """
        guard = confirm_or_explain(bestaetigt, f"Kontakt {resource_name} endgueltig loeschen")
        if guard:
            return guard
        client.request("DELETE", f"{_BASE}/{resource_name}:deleteContact")
        return {"ausgefuehrt": True}
