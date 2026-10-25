"""Google Health API (Nachfolger der Fitbit Web API) -- Gesundheitsdaten lesen,
schreiben, aendern und loeschen.

API-Doku: https://developers.google.com/health/reference/rest
Basis-URL: https://health.googleapis.com/v4

Datenpunkte liegen unter users/me/dataTypes/{datentyp}/dataPoints. Die
Datentyp-IDs (z.B. "sleep", "heart-rate", "steps", "weight") stehen in
google_health_datentypen(). Jedes Tool reicht Googles Antwort moeglichst
unveraendert durch, damit die KI die echten Feldnamen sieht.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.google_client import GoogleApiClient, GoogleApiError, confirm_or_explain

_SCOPE_PREFIX = "https://www.googleapis.com/auth/googlehealth."
SCOPES = [
    _SCOPE_PREFIX + f"{bereich}.{art}"
    for bereich in (
        "sleep",
        "activity_and_fitness",
        "health_metrics_and_measurements",
        "nutrition",
        "profile",
        "settings",
    )
    for art in ("readonly", "writeonly")
]

_BASE = "https://health.googleapis.com/v4"

# Quelle: https://developers.google.com/health/data-types
DATENTYPEN: dict[str, list[str]] = {
    "Aktivitaet und Fitness": [
        "active-energy-burned", "active-minutes", "active-zone-minutes",
        "activity-level", "altitude", "calories-in-heart-rate-zone",
        "daily-vo2-max", "distance", "exercise", "floors", "run-vo2-max",
        "sedentary-period", "steps", "swim-lengths-data",
        "time-in-heart-rate-zone", "total-calories", "vo2-max",
    ],
    "Gesundheitswerte und Messungen": [
        "blood-glucose", "body-fat", "core-body-temperature",
        "daily-heart-rate-variability", "daily-heart-rate-zones",
        "daily-oxygen-saturation", "daily-respiratory-rate",
        "daily-resting-heart-rate", "daily-sleep-temperature-derivations",
        "heart-rate", "heart-rate-variability", "height", "oxygen-saturation",
        "respiratory-rate-sleep-summary", "weight",
    ],
    "Ernaehrung und Trinken": [
        "food", "food-measurement-unit", "hydration-log", "nutrition-log",
    ],
    "Schlaf": ["sleep"],
    "Nur lesbar (eigene Scopes, hier nicht freigeschaltet)": [
        "electrocardiogram", "irregular-rhythm-notification",
    ],
    "Nur schreibbar (hier nicht freigeschaltet)": [
        "menstrual-period", "ovulation-test", "moods", "symptoms",
    ],
}

_STUFEN = {"LIGHT", "DEEP", "REM", "AWAKE"}


def _utc_und_offset(zeit: str) -> tuple[str, str]:
    """ISO-8601-Zeit MIT Zeitzone (z.B. 2024-10-31T01:55:00+01:00 oder ...Z)
    -> (UTC-Zeitstempel mit Z, Offset in Sekunden als "3600s").

    Die Health API will bei Schreibzugriffen UTC-Zeit plus separaten Offset."""
    text = zeit.strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GoogleApiError(
            f"Ungueltige Zeit '{zeit}'. Erwartet ISO 8601 mit Zeitzone, "
            "z.B. 2024-10-31T01:55:00+01:00."
        ) from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise GoogleApiError(
            f"Zeit '{zeit}' hat keine Zeitzone. Bitte mit Offset angeben, "
            "z.B. 2024-10-31T01:55:00+01:00."
        )
    offset = int(dt.utcoffset().total_seconds())
    utc = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return utc, f"{offset}s"


def _intervall(start: str, ende: str) -> dict:
    s_utc, s_off = _utc_und_offset(start)
    e_utc, e_off = _utc_und_offset(ende)
    return {
        "startTime": s_utc,
        "startUtcOffset": s_off,
        "endTime": e_utc,
        "endUtcOffset": e_off,
    }


def baue_schlaf_datenpunkt(start: str, ende: str, stufen: list[dict] | None) -> dict:
    """Baut den Request-Body fuer dataTypes/sleep/dataPoints (Create)."""
    schlaf: dict[str, Any] = {"interval": _intervall(start, ende)}
    if stufen:
        liste = []
        for nr, stufe in enumerate(stufen, start=1):
            typ = str(stufe.get("typ", "")).upper()
            if typ not in _STUFEN:
                raise GoogleApiError(
                    f"Stufe {nr}: typ '{typ}' ungueltig, erlaubt: "
                    f"{', '.join(sorted(_STUFEN))}."
                )
            if "start" not in stufe or "ende" not in stufe:
                raise GoogleApiError(f"Stufe {nr}: 'start' und 'ende' fehlen.")
            liste.append({**_intervall(stufe["start"], stufe["ende"]), "type": typ})
        schlaf["type"] = "STAGES"
        schlaf["stages"] = liste
    return {"sleep": schlaf}


def _pfad(datentyp: str) -> str:
    datentyp = datentyp.strip().strip("/")
    if not datentyp or "/" in datentyp:
        raise GoogleApiError(
            "datentyp muss eine ID wie 'sleep' oder 'heart-rate' sein "
            "(siehe google_health_datentypen)."
        )
    return f"{_BASE}/users/me/dataTypes/{datentyp}/dataPoints"


def _anfrage(client: GoogleApiClient, methode: str, url: str, **kwargs: Any) -> Any:
    """Die Health API lehnt Tokens ab, die auch fremde Scopes (Gmail, Kalender,
    ...) enthalten ("DISALLOWED_OAUTH_SCOPES"). Deshalb immer ein Token nur mit
    den Health-Scopes benutzen."""
    return client.request(methode, url, scopes=SCOPES, **kwargs)


def register_tools(mcp, client: GoogleApiClient) -> None:
    @mcp.tool()
    def google_health_datentypen() -> dict:
        """Listet die IDs aller Datentypen der Google Health API (z.B. 'sleep',
        'heart-rate', 'steps', 'weight'), gruppiert nach Bereich.

        Die ID wird als datentyp in den anderen google_health_*-Tools benutzt.
        """
        return DATENTYPEN

    @mcp.tool()
    def google_health_daten_lesen(
        datentyp: str,
        filter: str = "",
        seitengroesse: int = 0,
        seitentoken: str = "",
        quelle: str = "",
    ) -> dict:
        """Liest Datenpunkte eines Typs aus Google Health (neueste zuerst).

        datentyp: ID aus google_health_datentypen(), z.B. 'sleep'.
        filter: optionaler Googles-AIP-160-Filter, nur mit >=, < und AND.
          Beispiele:
          steps.interval.civil_start_time >= "2026-10-01" AND steps.interval.civil_start_time < "2026-10-02"
          heart-rate: heartRate.sample_time.civil_time >= "2026-10-24T00:00:00"
          sleep.interval.end_time >= "2026-10-24T00:00:00Z" AND sleep.interval.end_time < "2026-10-25T00:00:00Z"
          (Feldnamen im Filter sind camelCase des Typs wie in der Antwort;
          bei Fehlermeldungen von Google dort nachlesen.)
        seitengroesse: 0 = Standard (1440; bei sleep/exercise 25), max 10000.
        seitentoken: nextPageToken der vorherigen Antwort fuer die naechste Seite.
        quelle: optional 'alle', 'google-wearables', 'google-sources' oder
          'self-sources' (nicht fuer sleep/food -- dort google_health_schlaf_abgleich).
        """
        params: dict[str, Any] = {}
        if filter:
            params["filter"] = filter
        if seitengroesse:
            params["pageSize"] = seitengroesse
        if seitentoken:
            params["pageToken"] = seitentoken
        if quelle and quelle != "alle":
            params["dataSourceFamily"] = f"users/me/dataSourceFamilies/{quelle}"
        return _anfrage(client, "GET", _pfad(datentyp), params=params) or {}

    @mcp.tool()
    def google_health_datenpunkt_lesen(name: str) -> dict:
        """Liest einen einzelnen Datenpunkt.

        name: voller Name aus einer Antwort, z.B.
          users/me/dataTypes/sleep/dataPoints/<id>
        """
        name = name.strip().lstrip("/")
        if not name.startswith("users/") or "/dataPoints/" not in name:
            raise GoogleApiError(
                "name muss die Form users/me/dataTypes/<typ>/dataPoints/<id> haben."
            )
        return _anfrage(client, "GET", f"{_BASE}/{name}") or {}

    @mcp.tool()
    def google_health_schlaf_abgleich(filter: str = "", seitengroesse: int = 0, seitentoken: str = "") -> dict:
        """Liest Schlaf zusammengefuehrt ueber alle Quellen (dataPoints:reconcile).

        Fuer Schlaf ist das der empfohlene Weg, wenn mehrere Quellen
        (Tracker, Handy, manuell) Daten liefern. filter wie bei
        google_health_daten_lesen, z.B.
        sleep.interval.end_time >= "2026-10-24T00:00:00Z"
        """
        params: dict[str, Any] = {}
        if filter:
            params["filter"] = filter
        if seitengroesse:
            params["pageSize"] = seitengroesse
        if seitentoken:
            params["pageToken"] = seitentoken
        url = f"{_pfad('sleep')}:reconcile"
        return _anfrage(client, "GET", url, params=params) or {}

    @mcp.tool()
    def google_health_schlaf_schreiben(start: str, ende: str, stufen: list[dict] | None = None) -> dict:
        """Traegt eine Schlaf-Sitzung in Google Health ein.

        start/ende: ISO 8601 MIT Zeitzone, z.B. 2024-10-31T01:55:00+01:00
          (UTC-Umrechnung und Offset macht das Tool selbst).
        stufen: optionale Liste von Schlafphasen, jede als
          {"start": "...", "ende": "...", "typ": "LIGHT|DEEP|REM|AWAKE"}
          mit Zeiten im selben Format. Ohne stufen wird nur das Intervall
          geschrieben. Phasen sollten lueckenlos im Intervall liegen.
        Hinweis: vorher beim Nutzer bestaetigen lassen, das veraendert
        seine Gesundheitsdaten. Antwort enthaelt eine Operation von Google.
        """
        body = baue_schlaf_datenpunkt(start, ende, stufen)
        return _anfrage(client, "POST", _pfad("sleep"), json_body=body) or {}

    @mcp.tool()
    def google_health_datenpunkt_schreiben(datentyp: str, datenpunkt: str) -> dict:
        """Legt einen Datenpunkt beliebigen Typs an (dataPoints.create).

        datentyp: ID aus google_health_datentypen(), z.B. 'weight'.
        datenpunkt: JSON-Text des DataPoint, mit dem typspezifischen Feld
          als Schluessel, z.B. fuer Schlaf {"sleep": {...}}. Die genaue
          Struktur steht in der Doku unter
          https://developers.google.com/health/data-types/<typ>
          (z.B. /weight, /vitals, /steps, /nutrition). Fuer Schlaf besser
          google_health_schlaf_schreiben benutzen.
        Vorher beim Nutzer bestaetigen lassen.
        """
        try:
            body = json.loads(datenpunkt)
        except ValueError as exc:
            raise GoogleApiError(f"datenpunkt ist kein gueltiges JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise GoogleApiError("datenpunkt muss ein JSON-Objekt sein.")
        return _anfrage(client, "POST", _pfad(datentyp), json_body=body) or {}

    @mcp.tool()
    def google_health_datenpunkt_aendern(name: str, datenpunkt: str) -> dict:
        """Aendert einen selbst geschriebenen Datenpunkt (dataPoints.patch).

        name: voller Name users/me/dataTypes/<typ>/dataPoints/<id>.
        datenpunkt: JSON-Text des DataPoint mit den neuen Werten (gleiche
          Struktur wie beim Anlegen).
        Aenderbar sind nur Daten, die dieser OAuth-Client selbst geschrieben
        hat. Vorher beim Nutzer bestaetigen lassen.
        """
        name = name.strip().lstrip("/")
        if not name.startswith("users/") or "/dataPoints/" not in name:
            raise GoogleApiError(
                "name muss die Form users/me/dataTypes/<typ>/dataPoints/<id> haben."
            )
        try:
            body = json.loads(datenpunkt)
        except ValueError as exc:
            raise GoogleApiError(f"datenpunkt ist kein gueltiges JSON: {exc}") from exc
        return _anfrage(client, "PATCH", f"{_BASE}/{name}", json_body=body) or {}

    @mcp.tool()
    def google_health_datenpunkte_loeschen(datentyp: str, namen: list[str], bestaetigt: bool = False) -> dict:
        """Loescht selbst geschriebene Datenpunkte unwiderruflich -- braucht bestaetigt=True.

        datentyp: ID wie 'sleep'.
        namen: volle Namen (users/me/dataTypes/<typ>/dataPoints/<id>), max. 10000.
        Erst beim Nutzer nachfragen, dann mit bestaetigt=True wiederholen.
        """
        guard = confirm_or_explain(
            bestaetigt, f"{len(namen)} Google-Health-Datenpunkt(e) vom Typ {datentyp} endgueltig loeschen"
        )
        if guard:
            return guard
        if not namen:
            raise GoogleApiError("namen ist leer.")
        url = f"{_pfad(datentyp)}:batchDelete"
        return _anfrage(client, "POST", url, json_body={"names": namen}) or {"ausgefuehrt": True}

    @mcp.tool()
    def google_health_api_aufruf(methode: str, pfad: str, params: str = "", body: str = "", bestaetigt: bool = False) -> dict:
        """Allgemeiner Zugriff auf die Google Health API v4 fuer alles, was
        die anderen Tools nicht abdecken (z.B. users/me/profile,
        users/me/pairedDevices, dataPoints:rollUp, :dailyRollUp).

        methode: GET, POST, PATCH oder DELETE.
        pfad: relativ zu https://health.googleapis.com/v4/, z.B.
          'users/me/dataTypes/steps/dataPoints:dailyRollUp' oder 'users/me/profile'.
        params: optional JSON-Objekt als Text mit Query-Parametern.
        body: optional JSON-Text als Request-Body.
        Nur GET laeuft ohne Rueckfrage; alles andere braucht bestaetigt=True
        (vorher beim Nutzer nachfragen). Referenz:
        https://developers.google.com/health/reference/rest
        """
        methode = methode.strip().upper()
        if methode not in {"GET", "POST", "PATCH", "DELETE"}:
            raise GoogleApiError("methode muss GET, POST, PATCH oder DELETE sein.")
        pfad = pfad.strip().lstrip("/")
        if pfad.startswith("http") or ".." in pfad:
            raise GoogleApiError("pfad muss relativ zur v4-Basis-URL sein.")
        if methode != "GET":
            guard = confirm_or_explain(bestaetigt, f"{methode} auf {pfad} ausfuehren")
            if guard:
                return guard
        try:
            query = json.loads(params) if params else None
            payload = json.loads(body) if body else None
        except ValueError as exc:
            raise GoogleApiError(f"params/body ist kein gueltiges JSON: {exc}") from exc
        return _anfrage(client, methode, f"{_BASE}/{pfad}", params=query, json_body=payload) or {"ausgefuehrt": True}
