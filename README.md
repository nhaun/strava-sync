# strava-sync

Kleiner Docker-Dienst, der regelmäßig (Standard: stündlich) neue Strava-Aktivitäten herunterlädt und als
Datei in einem Ordner ablegt, z. B. im `watch/`-Ordner von Dreeve (`IMPORT_MODE=files`).

- Bevorzugt die **Originaldatei** (FIT/TCX/GPX, gzip wird entpackt). Wenn es keine gibt, wird der GPX-Export von Strava genutzt.
- **Inkrementell:** Bereits geladene Aktivitäten stehen in `/state/state.json`. Pro Lauf werden nur die neuesten Seiten der Aktivitätsliste abgefragt.
- Optionaler, gedrosselter **Backfill** ab einem Startdatum.
- Ohne Strava-API und ohne Premium: Der Dienst nutzt die Web-Session über das Cookie `strava_remember_token`. Damit funktioniert er auch bei 2FA.

## ⚠️ Hinweise / Risiken

- Das ist **Scraping der Strava-Website** und verstößt gegen die Strava-Nutzungsbedingungen. Strava kann
  das jederzeit technisch unterbinden oder im Extremfall den Account sperren. Nutzung auf eigenes Risiko.
- Das Token ist ein **vollwertiger Login** für deinen Account. Behandle es wie ein Passwort:
  nur in `.env`, nie committen.
- Das Token wird ungültig, wenn du dich im Browser **abmeldest**, das Passwort änderst, oder wenn es abläuft
  (die Laufzeit ist von Strava nicht dokumentiert). Dann zeigt der Container `unhealthy`, und im Log steht ein Hinweis.
- Defensive Defaults: höchstens 50 Downloads pro Lauf und 3 s Pause zwischen Downloads. Bei Fehlern oder HTTP 429
  verdoppelt sich die Wartezeit bis maximal 6 h.

## Token besorgen

1. Im Browser auf <https://www.strava.com> einloggen (mit 2FA) und dabei **„Angemeldet bleiben“** aktivieren.
2. Die DevTools öffnen (F12):
   - Chrome/Edge: *Application → Cookies → https://www.strava.com*
   - Firefox: *Web-Speicher → Cookies*
3. Den Wert des Cookies **`strava_remember_token`** kopieren. Er beginnt mit `eyJ…` und besteht aus drei durch Punkte getrennten Teilen (`xxx.yyy.zzz`). Kopiere den kompletten Rohwert aus der Spalte „Value“, nicht die einzelnen Einträge der geparsten Ansicht, die z. B. Firefox als Array mit drei Einträgen anzeigt.
4. **Nicht abmelden.** Das Browserfenster einfach schließen, denn ein Logout macht das Token ungültig.

Wann das Token abläuft, zeigt der Payload des JWT (Feld `exp`), z. B. per
`echo '<token>' | cut -d. -f2 | base64 -d 2>/dev/null`.

## Konfiguration (ENV)

| Variable | Default | Beschreibung |
|---|---|---|
| `STRAVA_REMEMBER_TOKEN` | – (Pflicht) | Wert des Cookies `strava_remember_token` |
| `SYNC_INTERVAL` | `3600` | Sekunden zwischen zwei Läufen |
| `BACKFILL_SINCE` | leer | `YYYY-MM-DD`: Beim **ersten** Start werden alle Aktivitäten ab diesem Datum geladen. Ist das Feld leer, werden nur Aktivitäten ab dem ersten Start geladen. |
| `MAX_DOWNLOADS_PER_RUN` | `50` | Obergrenze pro Lauf, verteilt einen großen Backfill auf mehrere Stunden |
| `DOWNLOAD_DELAY` | `3` | Pause zwischen Downloads in Sekunden |
| `WATCH_DIR` | `/watch` | Zielordner |
| `STATE_DIR` | `/state` | Ablage für Zustand (`state.json`) und Healthcheck (`health`) |

`BACKFILL_SINCE` wird nur beim allerersten Lauf ausgewertet, solange noch kein `state.json` existiert. Wenn du den
Backfill neu starten willst, lösche das State-Volume.

## Betrieb mit Docker Compose (neben Dreeve)

```bash
cp docker-compose.example.yml docker-compose.yml    # Pfad zum Dreeve-watch-Ordner anpassen
echo "STRAVA_REMEMBER_TOKEN=eyJ..." > .env && chmod 600 .env
docker compose up -d --build
docker compose logs -f strava-sync
```

- Der Container läuft als UID `1000` und muss in den `watch`-Ordner schreiben dürfen. Passe bei Bedarf
  `user:` im Compose-File an den Besitzer des Ordners an.
- Dateien heißen `strava-<id>.fit|tcx|gpx` und werden atomar geschrieben, sodass Dreeve keine halben Dateien sieht.
- Den Zustand prüfst du mit `docker inspect --format '{{.State.Health.Status}}' strava-sync` oder
  `docker compose exec strava-sync cat /state/health`.

### Token erneuern

Ein neues Token in `.env` eintragen und `docker compose up -d` ausführen. Der Zustand bleibt erhalten. Wenn Strava das
Token selbst rotiert (per `Set-Cookie`), speichert der Dienst das neue Token in `state.json` und verwendet immer das
Token mit der spätesten Ablaufzeit.

## Wie es funktioniert

1. Login: Die Cookies `strava_remember_id` und `strava_remember_token` werden gesetzt. `GET /me` muss auf
   `/athletes/<id>` umleiten.
2. Liste: `GET /athlete/training_activities?page=N` liefert die neuesten Aktivitäten zuerst. Das Paging stoppt, sobald
   eine Seite nichts Neues mehr enthält oder das Startdatum unterschritten ist.
3. Download: `GET /activities/<id>/export_original`. Fehlt das Original oder ist es unbrauchbar, folgt
   `GET /activities/<id>/export_gpx`. Aktivitäten ohne Datei und ohne GPS (manuelle Einträge) werden übersprungen.

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```
