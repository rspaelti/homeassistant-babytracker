# Changelog

## 0.6.0 — Phase 4 Mama + Tagesverlauf + Notizen

### 📋 Tagesverlauf (`/timeline`)
- Chronologischer Zeitstrahl aller Events über alle Kategorien: Stillen, Flasche, Windeln, Schlaf, Temperatur, Gesundheitsereignisse, Medikamente, Mama-Einträge, Messungen, Notizen
- Filter: Heute / Gestern / 7 Tage / beliebiger Tag
- Druck-freundliche Ansicht (Button "🖨 Drucken / PDF") — ideal für Hebamme/Arzt-Besuch
- Footer-Navigation: "Wachstum" ersetzt durch "Verlauf" (Wachstum bleibt über Home-Kachel erreichbar)

### 📝 Freie Notizen (`/notes/new`)
- Neue Eingabe mit Zeitpunkt + Freitext + optionalen Tags
- Erscheint im Tagesverlauf mit 📝-Icon
- Für Auffälligkeiten, Fragen an die Hebamme, besondere Momente

### 🤱 Phase 4: Mama-Sektion (`/mother`)
- **💉 Clexane-Tracker**: Ein-Klick "60 mg jetzt", Countdown bis Therapie-Ende (6 Wo. postpartal), Heute-Status prominent
- **🦵 Thrombose-Check**: tägliche Waden-Kontrolle L+R (ok / Schwellung / Rötung / Schmerz)
- **🩹 Wunde**: Kaiserschnitt-Status (unauffällig / gerötet / nässt / Sekret gelb/grün / blutig) + Notiz
- **❤️ Blutdruck + Puls**: systolisch/diastolisch/Puls mit Validierung
- **🩸 Wochenfluss (Lochien)**: Farbe + Menge, Verlauf-Hinweis rot→braun→gelb→weiss
- **📋 EPDS-Fragebogen** (Edinburgh Postnatal Depression Scale): 10 Items auf Deutsch, Auswertung mit Risikoklasse, **Self-Harm-Alarmbox bei Item 10** mit Schweizer Hilfs-Hotlines (Dargebotene Hand 143, Notruf 144)
- **😊 Stimmung**: 5-Stufen-Emoji-Skala, Ein-Tap vom Hub
- Hub-Seite mit allen Status-Kacheln auf einen Blick

### 🏠 Home-Dashboard erweitert
- Neue Kacheln: Mama (Clexane-Status), Tagesverlauf (Event-Anzahl heute)

### 🔧 Internes
- `services/timeline.py` + `services/mother.py`
- Seed läuft jetzt auch beim Python-Startup → robust im Dev-Modus
- Defensives `_mother_id()` legt Parent-User bei Bedarf an

## 0.5.0 — Push-Empfänger in der App konfigurieren

- **Neue Tabelle `notify_targets`**: beliebig viele Push-Empfänger (z.B. Renés iPhone + Janas iPhone + Grosseltern)
- **Auto-Discovery**: Die App fragt HA nach allen `notify.mobile_app_*` Services und bietet sie als Dropdown an. Manuelle Eingabe weiterhin möglich (Fallback).
- **Pro Target**: Aktivieren/Deaktivieren, Löschen, und ein **Test**-Button der sofort eine Test-Push sendet.
- **Scheduler** pusht jetzt an **alle aktivierten Targets** parallel (statt nur einer Service-Name in Config).
- **`notify_service` aus Add-on-Config entfernt** — alles über UI. Falls bei bestehenden Installationen noch gesetzt: wird beim ersten Start einmalig migriert.
- Integriert in `/warnings` → "Push-Empfänger"-Abschnitt.

## 0.4.3

- Mehr-Hub aufgeräumt: nur noch Warnungen, Kind, weitere Einstellungen. Gesundheit/Meds waren doppelt mit Home und gehören nicht zu Einstellungen.
- Warnungen-Seite bekommt **Regel-Konfiguration**: jede der 5 Regeln ist einzeln ein-/ausschaltbar + Push pro Regel separat steuerbar. Label + Beschreibung sichtbar.
- Neue Tabelle `warning_rule_config` + Migration. Defaults: alle aktiv, alle Push aktiv.
- Scheduler überspringt deaktivierte Regeln; Push nur bei `push_enabled` pro Regel.

## 0.4.2

- Fix: fehlende `routes/more.py` für den /more-Hub nachgereicht (v0.4.1 hätte beim Start gecrasht)

## 0.4.1

- Fieber-Schwelle für <3 Monate auf **38.0 °C** angehoben (bisher 37.5) — gemäss Kinderarzt-Empfehlung (sofort Arzt/Notfall ab 38 °C). Gilt im Warnings-Check und im Live-Input-Formular.
- "Mehr"-Footer-Eintrag zeigt jetzt einen echten **Hub** (`/more`) mit Links zu Warnungen, Gesundheit, Medikamente, Kind bearbeiten, Mama (Phase 4), Einstellungen (Phase 3+).
- Aktive Warnungen werden im Mehr-Hub als **roter Badge mit Anzahl** neben "Warnungen" angezeigt.

## 0.4.0 — Phase 3d: Alarm-Service + HA-Notifications

- **Neue Warnungs-Engine** (`services/warnings.py`) mit 5 Regeln:
  - `weight_loss_10`: Gewichtsverlust >10 % vom Geburtsgewicht (Tag 1–14)
  - `fever`: altersabhängige Fieber-Schwelle überschritten (<3 Mt: 37.5 / 3–6 Mt: 38 / >6 Mt: 38.5 °C)
  - `low_pees`: <6 Pipi heute ab Tag 5 (nur abends ab 18 Uhr)
  - `no_feed_4h`: >4h keine Mahlzeit (nur tagsüber 7–22 Uhr)
  - `percentile_jump`: ΔZ >2 zwischen zwei letzten Gewichtsmessungen
- **APScheduler** prüft alle 5 Min. automatisch
- **HA-Notifications** via `notify.mobile_app_*` Service. Neue Config-Option `notify_service` (leer = nur UI, keine Push). Critical-Flag setzt iOS Critical Alert.
- **Neue Tabelle `warning_states`** speichert aktiv/inaktiv + Debouncing (gleiche Warnung wird frühestens alle 6h erneut gepusht)
- **Neue Seite `/warnings`** mit aktiven Warnungen + Verlauf
- **Home-Dashboard** zeigt aktive Warnungen oben (rot = critical, amber = warn)
- Neue DB-Migration

## 0.3.0 — Phase 3a+3b: Gesundheit & Medikamente

- **Gesundheit** (`/health`): Hub mit Schnelleingabe-Kacheln
- **Temperatur** mit altersabhängiger Fieber-Schwelle (<3 Mt: 37.5 °C, 3–6 Mt: 38 °C, >6 Mt: 38.5 °C) und roter Warnung live beim Eintippen
- **Ikterus-Stufen 0–3** mit visueller Farbskala (grün→rot)
- **Nabel-Status** (feucht/trocken/abgefallen/gerötet/Sekret)
- **Haut-Status** (ok/Wunde/Ausschlag/Windelrose)
- **Schreiphasen** (einfache Zeit + Notiz)
- **Medikamente** (`/meds`): Presets für Vit D 400 IE / Vit K 2 mg / Paracetamol, Ein-Klick "Jetzt geben" für Vit D, Heute-Status prominent
- **Home-Dashboard** erweitert: Gesundheits-Kachel (letzte Temperatur) + Vit-D-Status (heute ausstehend/gegeben)
- **Schnell-Eingabe** um Temperatur + Medikament erweitert
- Löschen auf allen neuen Kategorien

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
