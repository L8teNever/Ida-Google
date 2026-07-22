# Ida-Google

Ein eigenständiger MCP-Server (Model Context Protocol) für Google-Dienste --
getrennt von Ida-Untis, Ida-Telegram und Ida-Memory, eigenes Repo, eigener
Container. Gibt Claude 54 Werkzeuge für Google Tasks, Kontakte, Kalender,
Gmail, Docs, Sheets, Slides, Chat und Meet, mit mehr Diensten in kommenden
Ausbaustufen (siehe [Fahrplan](#fahrplan) unten). Ziel ist, ueber die Zeit
moeglichst alles abzudecken, was die jeweilige Google-API hergibt -- nicht
nur eine kleine Grundauswahl.

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

**Nach jedem Update, das neue Google-Dienste oder zusätzliche Berechtigungen
für bestehende Dienste hinzufügt:** einmal erneut `/authorize?token=...`
aufrufen, damit auch den neuen/erweiterten Scopes zugestimmt wird -- sonst
melden betroffene Tools "insufficient authentication scopes". Bereits
funktionierende Tools sind davon nicht betroffen.

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

## Verfügbare MCP-Tools (54)

Vollständige Parameter/Docstrings direkt im Code (`app/services/*.py`) --
hier nur eine Übersicht nach Dienst gruppiert.

| Dienst | Tools | Kann u.a. |
|---|---|---|
| Verbindung | `google_verbindung_status` | Prüft, ob überhaupt mit Google verbunden |
| **Tasks** | 5 | Listen/Aufgaben lesen, anlegen, erledigt markieren, löschen |
| **Kontakte** | 5 | Lesen, anlegen, **bearbeiten, löschen** |
| **Kalender** | 4 | Termine lesen/anlegen/ändern/löschen, **Teilnehmer einladen** (echte Google-Einladungsmail) |
| **Gmail** | 13 | Suchen, lesen, **senden mit CC/BCC/Anhängen**, **im Thread antworten**, Anhänge herunterladen (Bilder als echtes Bild), Labels lesen/erstellen/anwenden/entfernen, **Entwürfe** anlegen/lesen/senden, in den Papierkorb verschieben |
| **Docs** | 7 | Anlegen, lesen, Text anhängen/an Position einfügen/löschen, **Suchen & Ersetzen**, Fett/Kursiv/Unterstrichen |
| **Sheets** | 8 | Anlegen, Bereich lesen/schreiben/anhängen/leeren, **Tabellenblatt anlegen/umbenennen/löschen** |
| **Slides** | 5 | Anlegen, lesen, Titel+Text-Folie hinzufügen/**löschen/verschieben** |
| **Chat** | 4 | Räume auflisten, **Raum erstellen**, Nachricht senden, Nachrichten lesen |
| **Meet** | 2 | Meeting-Raum anlegen (Beitritts-Link), Details abrufen |

Google-Fehler (fehlender Scope, abgelaufene Berechtigung, API nicht
aktiviert, ...) kommen 1:1 mit Googles eigener Fehlermeldung zurück, statt
geraten zu werden.

## Bestätigungspflicht beim Löschen

Jedes Tool, das Daten unwiderruflich entfernt (Name endet auf
`_loeschen`, dazu `google_mail_papierkorb` und `google_sheet_bereich_leeren`),
hat einen Parameter `bestaetigt` (Standard `False`). Ohne `bestaetigt=True`
passiert **technisch nichts** -- das Tool gibt nur einen Hinweis zurück, was
gelöscht würde. Claude ist angewiesen, immer erst im Chat nachzufragen und
dann mit `bestaetigt=True` zu wiederholen. Das ist codeseitig erzwungen,
nicht nur eine Anweisung, der die KI folgen könnte oder auch nicht.

**Ausnahme: `google_termin_loeschen` (Kalender-Termine).** Der hat gar
keinen `bestaetigt`-Parameter und löscht sofort -- ausdrücklich so
gewünscht, damit Terminänderungen schnell gehen.

Mail-/Chat-Versand (`google_mail_senden`, `google_mail_antworten`,
`google_mail_entwurf_senden`, `google_chat_nachricht_senden`) hat *keinen*
codeseitigen Schutz (das würde bedeuten, doppelt aufrufen zu müssen, nur um
einmal zu senden) -- dafür weisen die Server-`instructions` Claude an, den
Inhalt vor dem Senden im Chat zu bestätigen.

## Fahrplan

Ziel ist moeglichst vollstaendige Abdeckung jeder angebundenen API, nicht
nur eine Grundauswahl -- wird schrittweise erweitert, mit jeweils eigener
Testrunde. Bekannte, noch offene Lücken:

- **Gmail**: Filter/Regeln verwalten, mehrere Anhänge pro Downloadaufruf.
- **Docs**: Bilder, Tabellen, Kommentare/Vorschläge, Aufzählungslisten.
- **Sheets**: Zellformatierung (Farben/Schrift), Diagramme, Sortieren/Filtern, Pivot-Tabellen.
- **Slides**: freies Layout (Bilder, Positionierung, eigene Designs statt nur Titel+Text).
- **Kontakte**: Kontaktgruppen, Volltextsuche über `searchContacts`.
- **Meet**: Teilnehmerlisten, Aufzeichnungen/Transkripte (`conferenceRecords`).
- **Neue Dienste**: YouTube, Apps Script.

**Google Keep ist deaktiviert** (Code liegt in `app/services/notes.py`,
aber nicht in `_SERVICE_MODULES` eingehängt): Googles eigene Doku
beschreibt die Keep API als für Unternehmensumgebungen gedacht, und ein
echter Authorize-Versuch mit einem privaten Google-Konto wurde von Google
mit `invalid_scope` abgelehnt. Kommt zurück, falls sich das mal ändert
(z.B. mit einem Workspace-Konto).

Danach die weiteren eingeschränkten Dienste, wenn das jeweils zutrifft:
Google Ads (braucht einen von Google genehmigten Developer-Token),
Workspace Admin SDK (braucht ein bezahltes Workspace-Konto mit
Admin-Rechten), Classroom (braucht echte Classroom-Nutzung), Google Photos
(seit einer Google-Richtlinienänderung eingeschränkter Lesezugriff für
nicht verifizierte Apps).

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
  einem Update, das neue/erweiterte Berechtigungen braucht, muss
  `/authorize` erneut aufgerufen werden, damit die neuen Scopes mit
  zugestimmt werden.
- **Google-API-Fehler "invalid_scope" beim Aufrufen von `/authorize`**:
  einer der angeforderten Scopes lässt sich für diesen Google-Account/dieses
  Cloud-Projekt nicht vergeben (z.B. Keep, siehe Fahrplan) -- betrifft dann
  die komplette Anmeldung, da alle Scopes zusammen angefragt werden. In
  `app/server.py` das entsprechende Modul aus `_SERVICE_MODULES` entfernen.
- **Lösch-Tool antwortet nur mit einem Hinweis, löscht aber nichts**: so
  gewollt -- erst mit `bestaetigt=True` erneut aufrufen (siehe
  [Bestätigungspflicht beim Löschen](#bestätigungspflicht-beim-löschen)).
- **Claude/eine KI bekommt 401 auf dem MCP-Port**: Token in
  Client-Konfiguration und `.env` vergleichen.
