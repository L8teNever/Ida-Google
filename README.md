# Ida-Google

Ein eigenständiger MCP-Server (Model Context Protocol) für Google-Dienste --
getrennt von Ida-Untis, Ida-Telegram und Ida-Memory, eigenes Repo, eigener
Container. Gibt Claude Werkzeuge für Google Tasks und Google Kontakte, mit
mehr Diensten in kommenden Ausbaustufen (siehe [Fahrplan](#fahrplan) unten).

**Bewusst kein Ersatz für die offiziellen claude.ai-Connectors** für Google
Kalender, Gmail und Google Drive -- die sind bereits vollständig (Kalender
komplett CRUD, Drive inkl. Datei-Erstellung, Gmail lesen/Entwürfe) und lassen
sich genauso an Routinen anhängen. Ida-Google deckt nur das ab, was es dort
nicht gibt.

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
API**, **People API**) -> OAuth-Client vom Typ "Webanwendung" mit der
Redirect-URI `https://auth.deine-domain.de/oauth/callback`.

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

Google-Fehler (fehlender Scope, abgelaufene Berechtigung, API nicht
aktiviert, ...) kommen 1:1 mit Googles eigener Fehlermeldung zurück, statt
geraten zu werden.

## Fahrplan

Aktuell: Google Tasks, Google Kontakte. Geplant, schrittweise mit jeweils
eigener Testrunde: Google Sheets/Docs (Inhalte bearbeiten, nicht nur
Dateien anlegen wie der offizielle Drive-Connector), YouTube, Google Chat,
Google Meet, Apps Script, Gmail-Versand (der offizielle Connector kann nur
lesen/entwerfen, nicht senden). Danach die eingeschränkten Dienste, wenn
das jeweils zutrifft: Google Ads (braucht einen von Google genehmigten
Developer-Token), Workspace Admin SDK (braucht ein bezahltes
Workspace-Konto mit Admin-Rechten), Classroom (braucht echte
Classroom-Nutzung), Google Photos (seit einer Google-Richtlinienänderung
eingeschränkter Lesezugriff für nicht verifizierte Apps).

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
