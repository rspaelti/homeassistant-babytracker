"""Platzhalter-Routen für noch nicht implementierte Features."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from babytracker.auth import CurrentUser, get_current_user

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


def _placeholder(request: Request, user: CurrentUser, title: str, phase: str, planned: list[str]):
    return templates.TemplateResponse(
        request,
        "placeholder.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": "Baby",
            "title": title,
            "phase": phase,
            "planned": planned,
        },
    )


@router.get("/quick", response_class=HTMLResponse)
async def quick(request: Request, user: CurrentUser = Depends(get_current_user)):
    return _placeholder(
        request, user,
        title="Schnell-Eingabe",
        phase="Phase 2",
        planned=[
            "🍼 Stillen / Flasche starten/stoppen",
            "💩 Windel erfassen (Pipi / Stuhl / Farbe)",
            "😴 Schlaf-Session",
            "🌡️ Temperatur",
            "💊 Medikamenten-Gabe",
            "📝 Freie Notiz",
        ],
    )


@router.get("/mother", response_class=HTMLResponse)
async def mother(request: Request, user: CurrentUser = Depends(get_current_user)):
    return _placeholder(
        request, user,
        title="Mama (Wochenbett)",
        phase="Phase 4",
        planned=[
            "🩹 Wunde (Kaiserschnitt / Dammriss)",
            "💉 Clexane-Gabe",
            "❤️ Blutdruck + Puls",
            "🦵 Thrombose-Check",
            "📊 EPDS-Fragebogen",
            "😊 Stimmung + Notizen",
        ],
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: CurrentUser = Depends(get_current_user)):
    return _placeholder(
        request, user,
        title="Einstellungen",
        phase="Phase 3+",
        planned=[
            "👶 Kind bearbeiten — schon jetzt via /setup/child erreichbar",
            "👪 Weitere User anlegen (Family / Readonly)",
            "🔔 Alarm-Schwellen (Gewichtsverlust, Windel-Bilanz)",
            "📥 Daten-Export (CSV / JSON / PDF)",
            "🎨 Theme (Dark-Mode-Override)",
        ],
    )
