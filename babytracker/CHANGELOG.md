# Changelog

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
