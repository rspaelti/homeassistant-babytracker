# Changelog

## 0.2.1

- **Stuhlfarben als visuelle Kacheln** — 6 normale Farben (senfgelb → dunkelbraun + grün) und 5 auffällige (blass/weiss/grau/schwarz/blutig), angelehnt an die Stool Color Card für Gallengangatresie-Screening. Rote Warnbox bei Auswahl auffälliger Farbe.
- **Löschen-Button** (🗑) auf allen Einträgen in Ernährung, Windeln, Schlaf und Wachstum. Bestätigungsdialog vor dem Löschen.
- Hard-Delete (endgültig), mit Kind-ID-Prüfung für Sicherheit.

## 0.2.0 — Phase 2: Alltag

- **Stillen / Flasche** (`/feed`): Seitenwechsel-Timer für die Brust (links/rechts, live in JS), Flasche mit Typ + offered/taken ml, Erbrechen-Flag
- **Windeln** (`/diaper`): Pipi/Stuhl-Auswahl, Farbe (gelb/grün/braun/schwarz/weiss/blutig), Konsistenz, Intensität, Pipi-Warnung wenn <6/Tag
- **Schlaf** (`/sleep`): Start/Stop-Session mit Ortsauswahl, Live "schläft seit …", Tagesbilanz in Stunden, nachträgliches Eintragen
- **Schnell-Eingabe-Hub** (`/quick`): 6 grosse Buttons für die häufigen Aktionen
- **Home-Dashboard**: echte Tagesbilanz pro Kategorie mit "zuletzt vor …" und Alters-Label (z.B. "2 Tage alt")
- **Daily-Service** (`services/daily.py`): aggregiert Feedings, Windeln, Schlaf pro Tag + Formatter für "vor X Min." und Dauer
- **Tz-Helper**: `as_aware()` normalisiert tz-naive SQLite-Datetimes zu lokaler Zeitzone

## 0.1.9

- Restore accidentally removed `settings.db_url` property (regression from 0.1.7)

## 0.1.8

- Fix setup form: prefill from DB (existing child) or defaults, not from removed settings

## 0.1.7

- Remove child_* options from add-on config — setup is done in-app via `/setup/child`
- Add placeholder pages for `/quick`, `/mother`, `/settings` (no more 404s from nav)
- Home page shows actual child name from database (not from config)
- Seed script now only ensures a parent user exists

## 0.1.6

- New `/setup/child` page with form to create/edit the child directly in the UI
- `/growth*` redirects to `/setup/child` when no child exists (instead of 404)
- Debug log for add-on config values at startup

## 0.1.5

- Fix HA Ingress: read `X-Ingress-Path` header as `root_path`, prefix all internal links with it. App now works correctly inside HA's ingress tunnel.

## 0.1.4

- Fix AttributeError on home page: `settings.default_child` was renamed to `settings.child_display_name` during sanitisation but home route still referenced the old name

## 0.1.3

- Remove obsolete `COPY scripts/` from Dockerfile (scripts are inside `src/babytracker/scripts/`)

## 0.1.2

- Base image pinned to `3.12-alpine3.18` (3.12-alpine3.20 does not exist upstream)

## 0.1.1

- Seed-Daten des Kindes jetzt über Add-on-Konfiguration statt hardcoded
- Neue Optionen: `child_name`, `child_sex`, `child_birth_at`, `child_birth_weight_g`, `child_birth_length_cm`

## 0.1.0

- Initial Add-on-Skelett
- FastAPI mit Ingress-Support
- SQLite + Alembic, 16 Tabellen
- WHO-Perzentilen-Berechnung (Z-Score, Chart-Referenzlinien)
- Wachstums-Eingabe + Chart
