# Baby-Tracker

## Konfiguration

| Option | Default | Beschreibung |
|---|---|---|
| `timezone` | `Europe/Zurich` | IANA-Timezone für alle Anzeigen |
| `owlet_entity_prefix` | `sensor.dream_sock_` | Prefix der Owlet-Dream-Sock-Entitäten in HA |
| `log_level` | `info` | `debug` / `info` / `warning` / `error` |

**Kind anlegen:** Direkt in der App unter **Wachstum** → du wirst automatisch zum Setup-Formular weitergeleitet.

## Zugriff

Nach dem Start erscheint "Baby" in der HA-Seitenleiste. Klick öffnet die App via Ingress — kein separater Login nötig.

## Daten

- DB: `/data/babytracker.sqlite3` (persistent, überlebt Updates)
- Fotos: `/data/photos/`
- Backups: `/data/backups/` (täglich 03:00 lokal)

## Owlet-Integration

Voraussetzung: Die HACS-Integration `ryanbdclark/owlet` ist in Home Assistant aktiv. Werte werden alle 10 Min. als Min/Max/Avg-Aggregate gespeichert.
