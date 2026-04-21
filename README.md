# Baby-Tracker (Home Assistant Add-on)

Baby-Tracking-Web-App als Home-Assistant-Add-on. Erfasst Wachstum, Ernährung, Schlaf, Vitalwerte, Gesundheit und Wochenbett-Daten der Mutter.

## Features (geplant)

- Wachstum mit WHO-Perzentilen-Kurven (0–5 Jahre)
- Stillen / Flasche / Windeln / Schlaf
- Vitalwerte (manuell + Owlet Dream Sock via Home Assistant)
- Gesundheits-Ereignisse (Ikterus, Nabel, Haut)
- Medikamente (Vitamin D/K)
- Impfkalender + U-Termine (CH)
- Wochenbett-Sektion für die Mutter
- Tagebuch mit Fotos (später)
- Rollen für Familie / Grosseltern (später)

## Installation

1. In Home Assistant: **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories**
2. URL dieses Repos eintragen
3. "Baby-Tracker" installieren, Add-on-Konfiguration ausfüllen, starten
4. Über die HA-Seitenleiste öffnen

## Konfiguration

Die Geburtsdaten des Kindes werden in der Add-on-Konfiguration gesetzt und beim ersten Start als Ausgangsdatensatz in die Datenbank geschrieben. Siehe `babytracker/DOCS.md`.

## Entwicklung

```bash
cd babytracker
uv sync
uv run alembic upgrade head
uv run uvicorn babytracker.main:app --reload --port 8099
```

## Lizenz

WHO Growth Standards: CC BY-NC-SA 3.0 IGO, <https://www.who.int/childgrowth>
