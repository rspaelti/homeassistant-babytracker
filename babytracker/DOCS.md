# Baby-Tracker

## Konfiguration

| Option | Default | Beschreibung |
|---|---|---|
| `timezone` | `Europe/Zurich` | IANA-Timezone für alle Anzeigen |
| `owlet_entity_prefix` | `sensor.dream_sock_` | Prefix der Owlet-Dream-Sock-Entitäten in HA |
| `log_level` | `info` | `debug` / `info` / `warning` / `error` |
| `child_name` | _leer_ | Name des Kindes (beim ersten Start in DB geschrieben) |
| `child_sex` | `f` | `f` für Mädchen, `m` für Jungen (WHO-Perzentilen sind geschlechtsspezifisch) |
| `child_birth_at` | _leer_ | ISO-Zeitstempel der Geburt, z.B. `2026-01-15T09:30:00+01:00` |
| `child_birth_weight_g` | `0` | Geburtsgewicht in Gramm |
| `child_birth_length_cm` | `0.0` | Geburtslänge in cm |

Die Felder `child_name` und `child_birth_at` werden beim **ersten Start mit leerer Datenbank** ausgewertet und als Ausgangsdatensatz in die SQLite geschrieben. Spätere Änderungen der Konfiguration ändern die bereits gespeicherten Daten nicht — dafür editiert man direkt in der App.

## Zugriff

Nach dem Start erscheint "Baby" in der HA-Seitenleiste. Klick öffnet die App via Ingress — kein separater Login nötig.

## Daten

- DB: `/data/babytracker.sqlite3` (persistent, überlebt Updates)
- Fotos: `/data/photos/`
- Backups: `/data/backups/` (täglich 03:00 lokal)

## Owlet-Integration

Voraussetzung: Die HACS-Integration `ryanbdclark/owlet` ist in Home Assistant aktiv und die Dream-Sock-Entitäten sind erreichbar. Der Baby-Tracker holt die Werte alle 10 Min. und speichert Min/Max/Avg-Aggregate.
