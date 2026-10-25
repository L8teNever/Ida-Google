#!/usr/bin/env python3
"""Huawei-Health-Export -> CSV-Archiv + Import in Google Health ueber Ida-Google (MCP).

Zwei Schritte:

  export  Liest den (verschluesselten) Huawei-Health-ZIP-Export, schreibt ALLE
          Daten als CSV-Archiv (Schlaf, Puls, Ruhepuls, SpO2, Stress, Schritte,
          Trainings, Gewicht, Groesse, Wasser, ...) und baut einen Import-Plan
          (import_plan.jsonl) fuer die Typen, die Google Health schreiben laesst.

  import  Schreibt den Import-Plan per MCP an den Ida-Google-Server
          (Tools google_health_schlaf_schreiben / google_health_datenpunkt_schreiben).
          Bereits vorhandene Datenpunkte werden vorher gelesen und uebersprungen,
          ein Statusfile erlaubt Fortsetzen nach Abbruch.

Was Google Health von Drittanbietern schreiben laesst (getestet 25.10.2026):
  sleep, exercise, weight, height, hydration-log (+ body-fat, nutrition-log).
NICHT schreibbar ("Create is not supported"): heart-rate, oxygen-saturation,
  steps, distance, daily-resting-heart-rate, active-energy-burned. Diese Daten
  landen nur im CSV-Archiv.

Beispiele:
  python huawei_import.py export HUAWEI_HEALTH_xxx.zip --passwort '...' --ziel ./huawei_out
  python huawei_import.py import ./huawei_out --mcp-url http://10.7.0.1:4569/mcp --token "$MCP_AUTH_TOKEN"
  python huawei_import.py import ./huawei_out ... --typen sleep exercise --von 2024-01-01 --trocken

Abhaengigkeiten: pyzipper (export, nur fuer verschluesselte ZIPs), mcp<2 (import).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Hilfen: Zeit
# ---------------------------------------------------------------------------


def _tz(tz_text: str | None) -> timezone:
    """Huawei-Zeitzone '+0100' / '-0700' -> timezone."""
    t = (tz_text or "+0000").strip().strip('"').strip()
    sign = -1 if t.startswith("-") else 1
    t = t.lstrip("+-").replace(":", "")
    h, m = int(t[:2] or 0), int(t[2:4] or 0)
    return timezone(sign * timedelta(hours=h, minutes=m))


def iso(ms: int, tz_text: str | None) -> str:
    """Millisekunden + Huawei-Zeitzone -> ISO 8601 mit Offset (sekundengenau)."""
    dt = datetime.fromtimestamp(ms / 1000, _tz(tz_text)).replace(microsecond=0)
    return dt.isoformat()


def utc_und_offset(ms: int, tz_text: str | None) -> tuple[str, str]:
    z = _tz(tz_text)
    off = int(z.utcoffset(None).total_seconds())
    utc = datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return utc, f"{off}s"


def utc_key(text: str) -> str:
    """Beliebige ISO-Zeit -> UTC 'YYYY-MM-DDTHH:MM:SS' als Vergleichsschluessel."""
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# Export einlesen
# ---------------------------------------------------------------------------


class Export:
    """Liest Dateien direkt aus der ZIP (auch AES-verschluesselt) oder einem
    bereits entpackten Ordner."""

    def __init__(self, quelle: Path, passwort: str | None) -> None:
        self.quelle = quelle
        self._zip = None
        if quelle.is_file():
            try:
                import pyzipper  # type: ignore

                self._zip = pyzipper.AESZipFile(quelle)
            except ImportError:
                self._zip = zipfile.ZipFile(quelle)
            if passwort:
                self._zip.setpassword(passwort.encode())

    def namen(self) -> list[str]:
        if self._zip:
            return self._zip.namelist()
        return [str(p.relative_to(self.quelle)) for p in self.quelle.rglob("*") if p.is_file()]

    def lesen(self, name: str) -> bytes:
        if self._zip:
            try:
                return self._zip.read(name)
            except RuntimeError as exc:
                raise SystemExit(
                    f"ZIP laesst sich nicht lesen ({exc}). Passwort falsch oder "
                    "'pip install pyzipper' fehlt (Huawei nutzt AES)."
                ) from exc
        return (self.quelle / name).read_bytes()

    def json_dateien(self, ordner_teil: str) -> Iterator[Any]:
        for n in sorted(self.namen()):
            if ordner_teil in n and n.endswith(".json"):
                yield n, json.loads(self.lesen(n))


def lade_health(ex: Export) -> dict[int, list[dict]]:
    """Alle 'Health detail data'-Eintraege, gruppiert nach Huawei-Typnummer."""
    daten: dict[int, list[dict]] = defaultdict(list)
    for _, inhalt in ex.json_dateien("Health detail data"):
        for r in inhalt:
            daten[r.get("type")].append(r)
    return daten


def _wert(p: dict) -> Any:
    v = p.get("value", "")
    try:
        return json.loads(v) if isinstance(v, str) and v[:1] in "{[" else float(v)
    except (ValueError, TypeError):
        return v


# ---------------------------------------------------------------------------
# Konvertierung
# ---------------------------------------------------------------------------

SCHLAF_PHASE = {"DEEP": "DEEP", "SHALLOW": "LIGHT", "DREAM": "REM", "WAKE": "AWAKE"}
SESSION_LUECKE_MS = 60 * 60 * 1000  # >60 min Pause = neue Schlafsitzung
MIN_SESSION_MS = 10 * 60 * 1000

# Huawei-Sporttypen (summaryData.sportType) -> Google exerciseType
SPORT = {
    257: ("WALKING", "Gehen"),
    258: ("RUNNING", "Laufen"),
    259: ("OUTDOOR_BIKE", "Radfahren"),
    260: ("CLIMBING", "Bergsteigen"),
    262: ("SWIMMING_POOL", "Schwimmen (Becken)"),
    264: ("TREADMILL", "Laufband"),
    265: ("STATIONARY_BIKE", "Indoor-Radfahren"),
    266: ("SWIMMING_OPEN_WATER", "Freiwasserschwimmen"),
    273: ("ELLIPTICAL", "Crosstrainer"),
    274: ("ROWING_MACHINE", "Rudergeraet"),
    279: ("WORKOUT", "Freies Training"),
    281: ("WALKING", "Indoor-Gehen"),
}


def schlaf_sitzungen(daten: dict[int, list[dict]]) -> tuple[list[dict], list[dict]]:
    """Minutensegmente (Typ 9) -> Schlafsitzungen mit Phasen + Nickerchen."""
    segs: dict[tuple[int, int], tuple[str, str]] = {}
    for r in daten.get(9, []):
        tz = r.get("timeZone")
        for p in r.get("samplePoints", []):
            k = p.get("key", "").replace("PROFESSIONAL_SLEEP_", "")
            segs[(p["startTime"], p["endTime"])] = (k, tz)
    alle = sorted((s, e, k, tz) for (s, e), (k, tz) in segs.items())

    def gruppieren(liste):
        gruppen, akt = [], []
        for seg in liste:
            if akt and seg[0] - akt[-1][1] > SESSION_LUECKE_MS:
                gruppen.append(akt)
                akt = []
            # Ueberlappung abschneiden
            if akt and seg[0] < akt[-1][1]:
                seg = (akt[-1][1], seg[1], seg[2], seg[3])
                if seg[0] >= seg[1]:
                    continue
            akt.append(seg)
        if akt:
            gruppen.append(akt)
        return gruppen

    sitzungen = []
    for g in gruppieren([x for x in alle if x[2] in SCHLAF_PHASE]):
        if g[-1][1] - g[0][0] < MIN_SESSION_MS:
            continue
        phasen: list[list] = []
        for s, e, k, tz in g:
            typ = SCHLAF_PHASE[k]
            if phasen and s > phasen[-1][1]:  # kleine Luecke innerhalb der Nacht -> wach
                phasen.append([phasen[-1][1], s, "AWAKE", tz])
            if phasen and phasen[-1][2] == typ and phasen[-1][1] == s:
                phasen[-1][1] = e
            else:
                phasen.append([s, e, typ, tz])
        tz0 = g[0][3]
        sitzungen.append(
            {
                "start": iso(g[0][0], tz0),
                "ende": iso(g[-1][1], g[-1][3]),
                "stufen": [{"start": iso(s, tz), "ende": iso(e, tz), "typ": t} for s, e, t, tz in phasen],
            }
        )

    nickerchen = []
    for g in gruppieren([x for x in alle if x[2] == "NOON"]):
        if g[-1][1] - g[0][0] < MIN_SESSION_MS:
            continue
        nickerchen.append({"start": iso(g[0][0], g[0][3]), "ende": iso(g[-1][1], g[-1][3]), "stufen": None})
    return sitzungen, nickerchen


def trainings(ex: Export) -> list[dict]:
    aus, gesehen = [], set()
    for _, inhalt in ex.json_dateien("Motion path detail data"):
        for r in inhalt:
            rid = r.get("recordId") or (r["startTime"], r["endTime"])
            if rid in gesehen:
                continue
            gesehen.add(rid)
            try:
                s = json.loads(r.get("summaryData") or "{}")
            except ValueError:
                s = {}
            aus.append({"r": r, "s": s})
    return aus


def training_datenpunkt(t: dict) -> dict:
    r, s = t["r"], t["s"]
    tz = r.get("timeZone")
    gtyp, name = SPORT.get(s.get("sportType"), ("OTHER", f"Training {s.get('sportType')}"))
    s_utc, s_off = utc_und_offset(r["startTime"], tz)
    e_utc, e_off = utc_und_offset(r["endTime"], tz)
    metriken: dict[str, Any] = {}
    if s.get("totalCalories"):
        metriken["caloriesKcal"] = round(s["totalCalories"] / 1000, 1)
    if s.get("totalDistance"):
        metriken["distanceMillimeters"] = int(s["totalDistance"]) * 1000
    if s.get("totalSteps"):
        metriken["steps"] = str(int(s["totalSteps"]))
    if s.get("avgHeartRate"):
        metriken["averageHeartRateBeatsPerMinute"] = str(int(s["avgHeartRate"]))
    ex: dict[str, Any] = {
        "interval": {"startTime": s_utc, "startUtcOffset": s_off, "endTime": e_utc, "endUtcOffset": e_off},
        "exerciseType": gtyp,
        "displayName": f"{name} (Huawei)",
    }
    if s.get("totalTime"):
        ex["activeDuration"] = f"{int(s['totalTime'] // 1000)}s"
    if metriken:
        ex["metricsSummary"] = metriken
    return {"exercise": ex}


def probe_datenpunkt(feld: str, ms: int, tz: str | None, wert_feld: str, wert: Any) -> dict:
    utc, off = utc_und_offset(ms, tz)
    return {feld: {"sampleTime": {"physicalTime": utc, "utcOffset": off}, wert_feld: wert}}


# ---------------------------------------------------------------------------
# export-Befehl
# ---------------------------------------------------------------------------


def _csv(pfad: Path, kopf: list[str], zeilen) -> int:
    n = 0
    with pfad.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(kopf)
        for z in zeilen:
            w.writerow(z)
            n += 1
    return n


def cmd_export(args) -> None:
    ex = Export(Path(args.quelle), args.passwort)
    ziel = Path(args.ziel)
    (ziel / "csv").mkdir(parents=True, exist_ok=True)
    print("Lese Export ...", flush=True)
    d = lade_health(ex)
    stat: dict[str, int] = {}

    def punkte(typen, key=None):
        for t in typen:
            for r in d.get(t, []):
                for p in r.get("samplePoints", []):
                    if key is None or p.get("key") == key:
                        yield r, p

    # Puls (Typ 7 + 500023, dedupe ueber Zeit)
    puls = {}
    for r, p in punkte([7, 500023]):
        v = _wert(p)
        bpm = v.get("bpm") if isinstance(v, dict) else v
        if p.get("key") in ("DATA_POINT_DYNAMIC_HEARTRATE", "DYNAMIC_HEART_RATE") and bpm:
            puls[p["startTime"]] = (r.get("timeZone"), int(bpm))
        elif p.get("key") == "DATA_POINT_NEW_REST_HEARTRATE" and bpm:
            pass
    stat["puls"] = _csv(ziel / "csv/puls.csv", ["zeit", "bpm"],
                        ((iso(ms, tz), b) for ms, (tz, b) in sorted(puls.items())))

    ruhe = {}
    for r, p in punkte([500024, 7]):
        v = _wert(p)
        if p.get("key") == "RESTING_HEART_RATE" and isinstance(v, dict):
            ruhe[p["startTime"]] = (r.get("timeZone"), v.get("restBpm"))
        elif p.get("key") == "DATA_POINT_NEW_REST_HEARTRATE":
            ruhe.setdefault(p["startTime"], (r.get("timeZone"), int(v) if isinstance(v, float) else v))
    stat["ruhepuls"] = _csv(ziel / "csv/ruhepuls.csv", ["zeit", "bpm"],
                            ((iso(ms, tz), b) for ms, (tz, b) in sorted(ruhe.items())))

    spo2 = {}
    for r, p in punkte([400021, 16]):
        v = _wert(p)
        if isinstance(v, dict):
            spo2[p["startTime"]] = (r.get("timeZone"), v.get("spo2", v.get("avgSaturation")))
    stat["spo2"] = _csv(ziel / "csv/spo2.csv", ["zeit", "prozent"],
                        ((iso(ms, tz), w) for ms, (tz, w) in sorted(spo2.items())))

    stress = {}
    for r, p in punkte([11]):
        v = _wert(p)
        if isinstance(v, dict):
            stress[p["startTime"]] = (r.get("timeZone"), v.get("score"), v.get("grade"))
    stat["stress"] = _csv(ziel / "csv/stress.csv", ["zeit", "score", "stufe"],
                          ((iso(ms, tz), s, g) for ms, (tz, s, g) in sorted(stress.items())))

    stat["schlaf_phasen"] = _csv(
        ziel / "csv/schlaf_phasen.csv", ["start", "ende", "phase"],
        ((iso(p["startTime"], r.get("timeZone")), iso(p["endTime"], r.get("timeZone")),
          p.get("key", "").replace("PROFESSIONAL_SLEEP_", ""))
         for r, p in sorted(punkte([9]), key=lambda x: x[1]["startTime"])))

    bett = []
    for r, p in punkte([500010]):
        v = _wert(p)
        if isinstance(v, dict):
            bett.append((iso(p["startTime"], r.get("timeZone")),
                         iso(v["bedTime"], r.get("timeZone")) if v.get("bedTime") else "",
                         iso(v["risingTime"], r.get("timeZone")) if v.get("risingTime") else ""))
    stat["bettzeiten"] = _csv(ziel / "csv/bettzeiten.csv", ["eintrag", "zu_bett", "aufgestanden"], sorted(bett))

    alarme = [(iso(p["startTime"], r.get("timeZone")), iso(p["endTime"], r.get("timeZone")),
               max((x.get("heartRate", 0) for x in (_wert(p) or {}).get("details", [])), default=""))
              for r, p in punkte([13])]
    stat["hoher_puls_alarme"] = _csv(ziel / "csv/hoher_puls_alarme.csv", ["start", "ende", "max_bpm"], sorted(alarme))

    gewicht = {}
    for r, p in punkte([8, 10006]):
        v = _wert(p)
        if isinstance(v, dict) and 20 <= float(v.get("bodyWeight", 0)) <= 300:
            gewicht[p["startTime"]] = (r.get("timeZone"), float(v["bodyWeight"]), v.get("bodyFatRate"))
    stat["gewicht"] = _csv(ziel / "csv/gewicht.csv", ["zeit", "kg", "koerperfett_prozent"],
                           ((iso(ms, tz), kg, bf or "") for ms, (tz, kg, bf) in sorted(gewicht.items())))

    # Huawei speichert Groessen-Eintraege teils mit falscher Zeitzone (+0800);
    # deshalb die Zeitzone des zeitlich naechsten Ruhepuls-Eintrags nehmen.
    import bisect

    tz_ref = sorted((ms, tz) for ms, (tz, _) in ruhe.items())
    tz_ms = [x[0] for x in tz_ref]

    def tz_nahe(ms: int, fallback: str | None) -> str | None:
        if not tz_ref:
            return fallback
        i = min(bisect.bisect_left(tz_ms, ms), len(tz_ref) - 1)
        if i > 0 and abs(tz_ms[i - 1] - ms) < abs(tz_ms[i] - ms):
            i -= 1
        return tz_ref[i][1]

    groesse = {}
    for r, p in punkte([400027]):
        v = _wert(p)
        if isinstance(v, dict) and 100 <= float(v.get("userHeight", 0)) <= 250:
            groesse[p["startTime"]] = (tz_nahe(p["startTime"], r.get("timeZone")), float(v["userHeight"]))
    # Google behaelt bei kurz aufeinanderfolgenden Groessen nur einen Wert --
    # pro Tag nur den letzten Eintrag (Korrekturen wie 184 -> 179 cm) behalten.
    pro_tag: dict[str, int] = {}
    for ms, (tz, _) in sorted(groesse.items()):
        pro_tag[iso(ms, tz)[:10]] = ms
    groesse = {ms: groesse[ms] for ms in pro_tag.values()}
    stat["groesse"] = _csv(ziel / "csv/groesse.csv", ["zeit", "cm"],
                           ((iso(ms, tz), cm) for ms, (tz, cm) in sorted(groesse.items())))

    wasser = {}
    for r, p in punkte([200004]):
        v = _wert(p)
        if isinstance(v, dict) and v.get("drinkWater"):
            wasser[p["startTime"]] = (r.get("timeZone"), int(v["drinkWater"]))
    stat["wasser"] = _csv(ziel / "csv/wasser.csv", ["zeit", "ml"],
                          ((iso(ms, tz), ml) for ms, (tz, ml) in sorted(wasser.items())))

    # Aktivitaet pro Minute + Tagessummen
    minuten, tage = [], defaultdict(lambda: [0, 0, 0.0])
    for _, inhalt in ex.json_dateien("Sport per minute merged data"):
        for tag in inhalt:
            for r in tag.get("sportDataUserData", []):
                for b in r.get("sportBasicInfos", []):
                    minuten.append((r["startTime"], r.get("timeZone"), r.get("sportType"), b.get("steps", 0),
                                    b.get("distance", 0), b.get("calorie", 0)))
                    t = tage[tag["recordDay"]]
                    t[0] += b.get("steps", 0)
                    t[1] += b.get("distance", 0)
                    t[2] += b.get("calorie", 0) / 1000
    minuten.sort()
    stat["aktivitaet_minuten"] = _csv(ziel / "csv/aktivitaet_minuten.csv",
                                      ["zeit", "huawei_sporttyp", "schritte", "meter", "kalorien_kcal"],
                                      ((iso(ms, tz), st, s, m, round(c / 1000, 3)) for ms, tz, st, s, m, c in minuten))
    stat["aktivitaet_tage"] = _csv(ziel / "csv/aktivitaet_tage.csv", ["tag", "schritte", "meter", "kalorien_kcal"],
                                   ((f"{k // 10000:04d}-{k // 100 % 100:02d}-{k % 100:02d}", *v[:2], round(v[2], 1))
                                    for k, v in sorted(tage.items())))

    tr = trainings(ex)
    stat["trainings"] = _csv(
        ziel / "csv/trainings.csv",
        ["start", "ende", "huawei_sporttyp", "google_typ", "dauer_s", "meter", "schritte", "kcal", "puls_avg", "puls_max"],
        ((iso(t["r"]["startTime"], t["r"].get("timeZone")), iso(t["r"]["endTime"], t["r"].get("timeZone")),
          t["s"].get("sportType"), SPORT.get(t["s"].get("sportType"), ("OTHER",))[0],
          int(t["s"].get("totalTime", 0) // 1000), t["s"].get("totalDistance"), t["s"].get("totalSteps"),
          round((t["s"].get("totalCalories") or 0) / 1000, 1), t["s"].get("avgHeartRate"), t["s"].get("maxHeartRate"))
         for t in sorted(tr, key=lambda x: x["r"]["startTime"])))

    sitzungen, naps = schlaf_sitzungen(d)
    stat["schlaf_naechte"] = _csv(
        ziel / "csv/schlaf_naechte.csv", ["start", "ende", "tief_min", "leicht_min", "rem_min", "wach_min"],
        ((s["start"], s["ende"], *(
            sum((datetime.fromisoformat(x["ende"]) - datetime.fromisoformat(x["start"])).seconds // 60
                for x in s["stufen"] if x["typ"] == t) for t in ("DEEP", "LIGHT", "REM", "AWAKE")))
         for s in sitzungen))
    stat["nickerchen"] = _csv(ziel / "csv/nickerchen.csv", ["start", "ende"], ((n["start"], n["ende"]) for n in naps))

    # Rest roh sichern
    bekannt = {7, 9, 11, 13, 16, 400021, 500010, 500023, 500024, 8, 10006, 400027, 200004}
    with (ziel / "csv/sonstige_rohdaten.jsonl").open("w", encoding="utf-8") as f:
        n = 0
        for t, rs in d.items():
            if t in bekannt:
                continue
            for r in rs:
                f.write(json.dumps({"huawei_typ": t, **{k: v for k, v in r.items() if k != "tr"}}, ensure_ascii=False) + "\n")
                n += 1
        stat["sonstige_rohdaten"] = n

    # --- Import-Plan: nur was Google schreiben laesst ---
    plan = []
    for s in sitzungen:
        plan.append({"typ": "sleep", "schluessel": utc_key(s["start"]), "zeit": s["start"], "schlaf": s})
    for n in naps:
        plan.append({"typ": "sleep", "schluessel": utc_key(n["start"]), "zeit": n["start"], "schlaf": n})
    for t in tr:
        dp = training_datenpunkt(t)
        plan.append({"typ": "exercise", "schluessel": utc_key(dp["exercise"]["interval"]["startTime"]),
                     "zeit": iso(t["r"]["startTime"], t["r"].get("timeZone")), "datenpunkt": dp})
    for ms, (tz, kg, _bf) in sorted(gewicht.items()):
        dp = probe_datenpunkt("weight", ms, tz, "weightGrams", int(round(kg * 1000)))
        plan.append({"typ": "weight", "schluessel": utc_key(dp["weight"]["sampleTime"]["physicalTime"]),
                     "zeit": iso(ms, tz), "datenpunkt": dp})
    for ms, (tz, cm) in sorted(groesse.items()):
        dp = probe_datenpunkt("height", ms, tz, "heightMillimeters", str(int(round(cm * 10))))
        plan.append({"typ": "height", "schluessel": utc_key(dp["height"]["sampleTime"]["physicalTime"]),
                     "zeit": iso(ms, tz), "datenpunkt": dp})
    for ms, (tz, ml) in sorted(wasser.items()):
        s_utc, off = utc_und_offset(ms, tz)
        e_utc, _ = utc_und_offset(ms + 1000, tz)
        dp = {"hydrationLog": {"interval": {"startTime": s_utc, "startUtcOffset": off, "endTime": e_utc,
                                            "endUtcOffset": off}, "amountConsumed": {"milliliters": ml}}}
        plan.append({"typ": "hydration-log", "schluessel": utc_key(s_utc), "zeit": iso(ms, tz), "datenpunkt": dp})

    with (ziel / "import_plan.jsonl").open("w", encoding="utf-8") as f:
        for p in plan:
            f.write(json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "\n")

    print("\nCSV-Archiv (Zeilen):")
    for k, v in stat.items():
        print(f"  {k:22} {v}")
    zaehl = defaultdict(int)
    for p in plan:
        zaehl[p["typ"]] += 1
    print("\nImport-Plan fuer Google Health:", dict(zaehl))
    print(f"Ausgabe: {ziel.resolve()}")


# ---------------------------------------------------------------------------
# import-Befehl (MCP)
# ---------------------------------------------------------------------------


def _tool_ergebnis(res) -> tuple[bool, Any]:
    text = "".join(getattr(c, "text", "") for c in (res.content or []))
    daten = getattr(res, "structuredContent", None)
    if daten is None:
        try:
            daten = json.loads(text) if text else None
        except ValueError:
            daten = text
    if isinstance(daten, dict) and set(daten) == {"result"}:
        daten = daten["result"]
    return (not res.isError), (daten if not res.isError else text)


class Mcp:
    def __init__(self, session) -> None:
        self.s = session

    async def rufen(self, name: str, args: dict, versuche: int = 4) -> Any:
        letzter = None
        for i in range(versuche):
            try:
                res = await self.s.call_tool(name, args)
                ok, daten = _tool_ergebnis(res)
                if ok:
                    return daten
                letzter = str(daten)
                # Nur voruebergehende Fehler wiederholen (Quota, 5xx, Netz)
                voruebergehend = ("429", "resource_exhausted", "unavailable", "http 5", "timeout",
                                  "timed out", "rate", "quota", "internal", "deadline", "backend")
                if not any(x in letzter.lower() for x in voruebergehend):
                    break
            except Exception as exc:  # Netzwerk/Session
                letzter = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(2 * (i + 1))
        raise RuntimeError(letzter)


async def vorhandene_schluessel(mcp: Mcp, typ: str, von: str | None) -> set[str]:
    """Liest vorhandene Datenpunkte (bei sleep alle Quellen, sonst nur eigene)."""
    feld = {"sleep": "sleep", "exercise": "exercise", "weight": "weight", "height": "height",
            "hydration-log": "hydrationLog"}[typ]
    args: dict[str, Any] = {"datentyp": typ}
    if typ == "sleep":
        if von:
            args["filter"] = f'sleep.interval.end_time >= "{von}T00:00:00Z"'
    else:
        args["quelle"] = "self-sources"
        args["seitengroesse"] = 25 if typ == "exercise" else 10000
    schluessel, token = set(), ""
    while True:
        if token:
            args["seitentoken"] = token
        daten = await mcp.rufen("google_health_daten_lesen", args)
        for dp in (daten or {}).get("dataPoints", []):
            inhalt = dp.get(feld, {})
            t = (inhalt.get("interval") or {}).get("startTime") or (inhalt.get("sampleTime") or {}).get("physicalTime")
            if t:
                schluessel.add(utc_key(t))
        token = (daten or {}).get("nextPageToken", "")
        if not token:
            return schluessel


async def _import(args) -> None:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        raise SystemExit("Fuer import: pip install 'mcp>=1.28,<2'")

    ordner = Path(args.ordner)
    plan = [json.loads(z) for z in (ordner / "import_plan.jsonl").read_text(encoding="utf-8").splitlines() if z]
    if args.typen:
        plan = [p for p in plan if p["typ"] in args.typen]
    if args.von:
        plan = [p for p in plan if p["zeit"][:10] >= args.von]
    if args.bis:
        plan = [p for p in plan if p["zeit"][:10] <= args.bis]
    if args.max:
        plan = plan[: args.max]

    status_pfad = ordner / "import_status.json"
    try:
        erledigt = set(json.loads(status_pfad.read_text())["erledigt"])
    except (FileNotFoundError, ValueError, KeyError):
        erledigt = set()

    token = args.token or os.environ.get("MCP_AUTH_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    fehler_log = (ordner / "import_fehler.jsonl").open("a", encoding="utf-8")

    async with streamablehttp_client(args.mcp_url, headers=headers, timeout=60) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            mcp = Mcp(session)

            vorhanden: dict[str, set[str]] = {}
            for typ in sorted({p["typ"] for p in plan}):
                print(f"Lese vorhandene Daten: {typ} ...", flush=True)
                vorhanden[typ] = await vorhandene_schluessel(mcp, typ, args.von)
                print(f"  {len(vorhanden[typ])} vorhanden", flush=True)

            offen = [p for p in plan
                     if f'{p["typ"]}|{p["schluessel"]}' not in erledigt
                     and p["schluessel"] not in vorhanden.get(p["typ"], set())]
            print(f"\n{len(plan)} im Plan, {len(plan) - len(offen)} schon vorhanden/erledigt, {len(offen)} zu schreiben.")
            if args.trocken:
                for p in offen[:10]:
                    print("  wuerde schreiben:", p["typ"], p["zeit"])
                return

            ok = fehler = 0
            start = time.monotonic()
            sem = asyncio.Semaphore(args.parallel)

            async def schreiben(p):
                nonlocal ok, fehler
                async with sem:
                    try:
                        if p["typ"] == "sleep":
                            a = {"start": p["schlaf"]["start"], "ende": p["schlaf"]["ende"]}
                            if p["schlaf"].get("stufen"):
                                a["stufen"] = p["schlaf"]["stufen"]
                            await mcp.rufen("google_health_schlaf_schreiben", a)
                        else:
                            await mcp.rufen("google_health_datenpunkt_schreiben",
                                            {"datentyp": p["typ"], "datenpunkt": json.dumps(p["datenpunkt"])})
                        erledigt.add(f'{p["typ"]}|{p["schluessel"]}')
                        ok += 1
                    except Exception as exc:
                        fehler += 1
                        fehler_log.write(json.dumps({"typ": p["typ"], "zeit": p["zeit"], "fehler": str(exc)[:500]},
                                                    ensure_ascii=False) + "\n")
                        fehler_log.flush()
                    fertig = ok + fehler
                    if fertig % 25 == 0 or fertig == len(offen):
                        status_pfad.write_text(json.dumps({"erledigt": sorted(erledigt)}))
                        rate = fertig / max(time.monotonic() - start, 1e-6)
                        print(f"  {fertig}/{len(offen)}  ok={ok} fehler={fehler}  ~{rate:.1f}/s", flush=True)

            await asyncio.gather(*(schreiben(p) for p in offen))
            status_pfad.write_text(json.dumps({"erledigt": sorted(erledigt)}))
            print(f"\nFertig: {ok} geschrieben, {fehler} Fehler"
                  + (f" (Details: {ordner / 'import_fehler.jsonl'})" if fehler else ""))
    fehler_log.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="befehl", required=True)

    e = sub.add_parser("export", help="ZIP lesen, CSV-Archiv + Import-Plan schreiben")
    e.add_argument("quelle", help="Huawei-ZIP oder entpackter Ordner")
    e.add_argument("--passwort", default=os.environ.get("HUAWEI_ZIP_PASSWORT"))
    e.add_argument("--ziel", default="huawei_out")

    i = sub.add_parser("import", help="Import-Plan per MCP an Ida-Google schreiben")
    i.add_argument("ordner", help="Ausgabeordner von 'export'")
    i.add_argument("--mcp-url", required=True, help="z.B. http://10.7.0.1:4569/mcp")
    i.add_argument("--token", help="Bearer-Token (sonst Umgebungsvariable MCP_AUTH_TOKEN)")
    i.add_argument("--typen", nargs="*", choices=["sleep", "exercise", "weight", "height", "hydration-log"])
    i.add_argument("--von", help="YYYY-MM-DD (lokales Datum)")
    i.add_argument("--bis", help="YYYY-MM-DD (lokales Datum)")
    i.add_argument("--max", type=int, help="hoechstens so viele schreiben (Test)")
    i.add_argument("--parallel", type=int, default=3)
    i.add_argument("--trocken", action="store_true", help="nur anzeigen, nichts schreiben")

    args = ap.parse_args()
    if args.befehl == "export":
        cmd_export(args)
    else:
        asyncio.run(_import(args))


if __name__ == "__main__":
    main()
