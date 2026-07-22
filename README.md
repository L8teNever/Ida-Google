# Ida-Google

Ein eigenständiger MCP-Server (Model Context Protocol) für Google-Dienste --
getrennt von Ida-Untis, Ida-Telegram und Ida-Memory, eigenes Repo, eigener
Container. Gibt Claude Werkzeuge für Google Tasks, Kontakte, Kalender, Gmail
und Keep-Notizen, mit mehr Diensten in kommenden Ausbaustufen (siehe
[Fahrplan](#fahrplan) unten).

Bewusst als **ein einziger, einheitlicher Connector** gebaut -- auch dort, wo
es (z.B. für Kalender, Gmail-Lesen, Drive) schon offizielle claude.ai-
Connectors gibt. Eine echte Ergänzung dazu: `google_mail_senden` kann
tatsächlich **senden**, nicht nur lesen/entwerfen wie der offizielle
Gmail-Connector.

## Architektur: zwei Ports, zwei Vertrauenszonen

Google-Zugriff läuft über OAuth: einmalig im Browser bei Google anmelden und
zustimmen, danach läuft alles automatisiert über einen gespeicherten
Refresh-Token. Diese zwei Dinge -- der einmalige Browser-Anmelde-Flow und die
laufenden, automatisierten API-Aufrufe -- laufen bewusst auf zwei getrennten
Ports/Hostnamen mit unterschiedlichem Schutz:

```
Browser (nur du)                    Claude / eine Routine
      |                                     |
      v                                     v
auth.deine-domain.de              google.deine-domain.de
  (Cloudflare Zero Trust Access)     (normaler Cloudflare Tunnel)
      |                                     |
      v                                     v
127.0.0.1:4570 (Auth-Port)        127.0.0.1:4569 (MCP-Port)
  /authorize, /oauth/callback        /mcp (Bearer-Token)
      |                                     |
      +----------------+--------------------+
                        v
         Docker-Container "ida-google-mcp"
                        |
                        v
       /data/google_token.json (Docker-Volume)
```

- **Auth-Port (4570):** nur für den (seltenen) Google-Anmelde-Flow. Diese
  Hostname-Route sollte zusätzlich hinter **Cloudflare Zero Trust Access**
  liegen (eigene Cloudflare-Funktion, verlangt einen Login -- z.B. per
  E-Mail-Code -- bevor die Anfrage überhaupt beim Server ankommt), damit
  wirklich nur du diesen Flow je starten kannst. Ein zweites, kostenloses
  Sicherheitsnetz (`AUTH_TOKEN` als `?token=`) ist zusätzlich eingebaut,
  ersetzt Zero Trust Access aber nicht.
- **MCP-Port (4569):** die eigentlichen Google-Werkzeuge, ganz normal per
  Bearer-Token abgesichert wie bei den anderen drei Ida-*-Projekten -- läuft
  dauerhaft, keine Browser-Interaktion nötig.

Beide Ports laufen im selben Container/Prozess (`app/main.py`) und teilen
sich denselben gespeicherten Refresh-Token.

## Voraussetzungen

- Docker + Docker Compose auf dem Server
- Ein bereits eingerichteter und verbundener Cloudflare Tunnel
- Cloudflare Zero Trust (kostenlos bis 50 Nutzer) für den Auth-Port
- Ein Google-Cloud-Projekt mit OAuth-Client (Anleitung in `.env.example`)

## 1. Google Cloud Console einrichten

Ausführliche Schritt-für-Schritt-Anleitung steht direkt in `.env.example`
(OAuth-Zustimmungsbildschirm, benötigte APIs aktivieren, OAuth-Client
anlegen). Kurzfassung: neues Projekt -> Zustimmungsbildschirm (extern, dich
selbst als Testnutzer) -> benötigte APIs aktivieren (aktuell: **Google Tasks
API**, **People API**, **Google Calendar API**, **Gmail API**, **Google Keep
API**, **Google Docs API**, **Google Sheets API**, **Google Slides API**,
**Google Chat API**, **Google Meet API**) -> OAuth-Client vom Typ
"Webanwendung" mit der Redirect-URI `https://auth.deine-domain.de/oauth/callback`.

**Nach jedem Update, das einen neuen Google-Dienst hinzufügt:** einmal
erneut `/authorize?token=...` aufrufen, damit auch den neuen Scopes
zugestimmt wird -- sonst melden die neu hinzugekommenen Tools "insufficient
authentication scopes". Alte Verbindung/Tools bleiben davon unberührt.

## 2. Einrichten, bauen, starten

```bash
git clone https://github.com/<dein-user>/Ida-Google.git
cd Ida-Google
cp .env.example .env
```

`.env` ausfüllen (siehe Kommentare darin). Image bauen lassen: Bei jedem
Push auf `main` baut `.github/workflows/docker-publish.yml` automatisch nach
`ghcr.io/<dein-user>/ida-google:latest`. Einmalig auf öffentlich stellen
(GitHub -> Profil -> **Packages** -> `ida-google` -> Package settings ->
Change visibility -> Public).

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```

## 3. An den bestehenden Cloudflare Tunnel anbinden -- zwei Hostnamen

```yaml
ingress:
  - hostname: google.deine-domain.de
    service: http://localhost:4569
  - hostname: auth.deine-domain.de
    service: http://localhost:4570
  - service: http_status:404
```

Danach in **Cloudflare Zero Trust** (dash.teams.cloudflare.com) -> Access ->
Applications -> "Add an application" -> Self-hosted -> Domain
`auth.deine-domain.de` -> eine Policy, die nur deine eigene E-Mail-Adresse
zulässt. Ab dann verlangt Cloudflare selbst einen Login, bevor `/authorize`
überhaupt erreichbar ist. **`google.deine-domain.de` (der MCP-Port) braucht
diese Policy nicht** -- der ist ganz normal per Bearer-Token abgesichert und
soll ja von Claude/Routinen erreichbar bleiben.

## 4. Einmalig mit Google verbinden

Im Browser aufrufen (löst den Login bei Cloudflare Access aus, falls
konfiguriert):

```
https://auth.deine-domain.de/authorize?token=<AUTH_TOKEN>
```

Google-Consent-Screen bestätigen ("Nicht verifiziert" ist normal für eine
private App wie diese). Danach zeigt die Seite "Erfolgreich mit Google
verbunden".

## 5. Als claude.ai Connector hinzufügen

claude.ai -> Einstellungen -> Connectors -> Add custom connector -> als URL:

```
https://google.deine-domain.de/mcp?token=<MCP_AUTH_TOKEN>
```

## Verfügbare MCP-Tools

| Tool | Zweck |
|---|---|
| `google_verbindung_status()` | Prüft, ob überhaupt schon einmal mit Google verbunden wurde |
| `google_aufgabenlisten()` | Alle Google Tasks-Listen (id + Titel) |
| `google_aufgaben_liste(tasklist_id, nur_offene=True)` | Aufgaben einer Liste |
| `google_aufgabe_erstellen(tasklist_id, titel, notizen="", faellig="")` | Neue Aufgabe |
| `google_aufgabe_erledigt(tasklist_id, task_id)` | Aufgabe als erledigt markieren |
| `google_aufgabe_loeschen(tasklist_id, task_id)` | Aufgabe löschen |
| `google_kontakte_liste(max_ergebnisse=50)` | Kontakte (Name, E-Mails, Telefonnummern) |
| `google_kontakt_erstellen(vorname, nachname="", email="", telefon="")` | Neuen Kontakt anlegen |
| `google_kontakt_details(resource_name)` | Details zu einem Kontakt |
| `google_termine_liste(von="", bis="", max_ergebnisse=20, kalender_id="primary")` | Termine in einem Zeitraum (Standard: naechste 30 Tage) |
| `google_termin_erstellen(titel, start, ende, beschreibung="", ganztaegig=False, kalender_id="primary")` | Neuen Termin anlegen |
| `google_termin_aktualisieren(event_id, titel="", start="", ende="", beschreibung="", ...)` | Einzelne Felder eines Termins ändern |
| `google_termin_loeschen(event_id, kalender_id="primary")` | Termin löschen |
| `google_mails_suchen(query="", max_ergebnisse=10)` | Gmail durchsuchen (Betreff, Absender, Datum, Vorschau) |
| `google_mail_lesen(message_id)` | Eine Mail vollständig lesen (inkl. Text) |
| `google_mail_senden(an, betreff, text)` | **Verschickt tatsächlich eine Mail** -- unwiderruflich |
| `google_notizen_liste(max_ergebnisse=20)` | Google Keep-Notizen (nur Fließtext, keine Checklisten) |
| `google_notiz_erstellen(titel, text)` | Neue Notiz anlegen |
| `google_notiz_loeschen(name)` | Notiz löschen |
| `google_doc_erstellen(titel, text="")` | Neues Google Doc, optional mit Anfangstext |
| `google_doc_lesen(document_id)` | Titel + kompletter Fließtext eines Docs |
| `google_doc_text_anhaengen(document_id, text)` | Text ans Ende eines Docs anhängen |
| `google_sheet_erstellen(titel)` | Neue Google-Tabelle |
| `google_sheet_lesen(spreadsheet_id, bereich)` | Zellbereich lesen (A1-Notation) |
| `google_sheet_schreiben(spreadsheet_id, bereich, werte)` | Zellbereich überschreiben |
| `google_sheet_zeile_anhaengen(spreadsheet_id, bereich, werte)` | Neue Zeile anhängen |
| `google_praesentation_erstellen(titel)` | Neue Präsentation |
| `google_praesentation_lesen(presentation_id)` | Titel + Text jeder Folie |
| `google_praesentation_folie_hinzufuegen(presentation_id, titel="", text="")` | Neue Titel+Text-Folie |
| `google_chat_raeume_liste()` | Google-Chat-Räume, in denen der Account Mitglied ist |
| `google_chat_nachricht_senden(space_name, text)` | **Verschickt tatsächlich eine Nachricht** -- unwiderruflich |
| `google_chat_nachrichten_liste(space_name, max_ergebnisse=20)` | Letzte Nachrichten eines Raums |
| `google_meet_raum_erstellen()` | Neuer Meet-Raum, gibt den Beitritts-Link zurück |
| `google_meet_raum_details(name)` | Details zu einem bestehenden Meet-Raum |

Google-Fehler (fehlender Scope, abgelaufene Berechtigung, API nicht
aktiviert, ...) kommen 1:1 mit Googles eigener Fehlermeldung zurück, statt
geraten zu werden.

## Fahrplan

Aktuell: Tasks, Kontakte, Kalender, Gmail (lesen + senden), Keep (nur
Fließtext), Docs, Sheets, Slides (einfache Titel+Text-Folien), Chat, Meet
(nur Raum anlegen/abrufen). Geplant, schrittweise mit jeweils eigener
Testrunde: Keep-Checklisten, freieres Slides-Layout, YouTube, Apps Script,
Meet-Teilnehmerlisten/Aufzeichnungen. Danach die eingeschränkten Dienste,
wenn das jeweils zutrifft: Google Ads (braucht einen von Google genehmigten
Developer-Token), Workspace Admin SDK (braucht ein bezahltes
Workspace-Konto mit Admin-Rechten), Classroom (braucht echte
Classroom-Nutzung), Google Photos (seit einer Google-Richtlinienänderung
eingeschränkter Lesezugriff für nicht verifizierte Apps).

**Ob Chat und Meet mit einem normalen privaten Google-Konto (statt einem
bezahlten Workspace-Konto) vollständig funktionieren, ließ sich nicht vorab
zweifelsfrei klären** -- das zeigt sich beim ersten echten Aufruf über
Googles eigene Fehlermeldung, statt hier geraten zu werden.

## Lokal testen ohne Cloudflare

```bash
docker compose up -d
curl "http://127.0.0.1:4570/healthz"
curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" http://127.0.0.1:4569/healthz
```

## Troubleshooting

- **Container startet nicht**: `docker compose logs` -- meist fehlt eine
  Pflichtvariable in `.env` (`GOOGLE_CLIENT_ID`/`_SECRET`/`GOOGLE_REDIRECT_URI`).
- **Tool meldet "Noch nicht mit Google verbunden"**: Schritt 4 (einmaliger
  Anmelde-Flow) noch nicht gemacht, oder der Container wurde ohne das
  `/data`-Volume neu gestartet (`docker compose down -v` löscht auch den
  gespeicherten Token -- ohne `-v` starten).
- **"Google hat keinen Refresh-Token geliefert"**: Google gibt nur beim
  ersten Zustimmen (oder mit `prompt=consent`, was hier immer gesetzt ist)
  einen Refresh-Token zurück. Falls es trotzdem passiert: unter
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
  den Zugriff dieser App entfernen und `/authorize` erneut aufrufen.
- **Google-API-Fehler "insufficient authentication scopes" o.ä.**: Nach
  einem Update, das einen neuen Google-Dienst hinzufügt, muss `/authorize`
  erneut aufgerufen werden, damit die neuen Scopes mit zugestimmt werden.
- **Claude/eine KI bekommt 401 auf dem MCP-Port**: Token in
  Client-Konfiguration und `.env` vergleichen.
