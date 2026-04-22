"""Client für die Home-Assistant-REST-API via Supervisor-Proxy."""

from __future__ import annotations

import logging

import httpx

from babytracker.config import settings

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _headers() -> dict:
    if not settings.ha_token:
        return {}
    return {
        "Authorization": f"Bearer {settings.ha_token}",
        "Content-Type": "application/json",
    }


async def call_service(domain: str, service: str, payload: dict) -> bool:
    """Ruft einen HA-Service auf. Gibt True bei Erfolg zurück."""
    if not settings.ha_url or not settings.ha_token:
        log.debug("HA not configured, skipping service call %s.%s", domain, service)
        return False
    url = f"{settings.ha_url}/api/services/{domain}/{service}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, headers=_headers(), json=payload)
        if r.status_code < 300:
            return True
        log.warning("HA service call %s.%s failed: %s %s", domain, service, r.status_code, r.text[:200])
        return False
    except httpx.HTTPError as e:
        log.warning("HA service call %s.%s error: %s", domain, service, e)
        return False


async def notify_mobile(service_name: str, title: str, message: str, critical: bool = False) -> bool:
    if not service_name:
        return False
    # Service-Name kann "mobile_app_renes_iphone" oder "notify.mobile_app_..." sein
    if service_name.startswith("notify."):
        service_name = service_name[len("notify."):]
    data: dict = {"title": title, "message": message}
    if critical:
        # iOS Critical Alert (HA Companion)
        data["data"] = {"push": {"interruption-level": "critical", "sound": {"critical": 1, "volume": 1.0}}}
    return await call_service("notify", service_name, data)


async def list_mobile_app_notify_services() -> list[str]:
    """Liefert alle verfügbaren `notify.mobile_app_*` Services aus HA.

    Fragt die HA REST-API GET /api/services ab und filtert die notify-Domain.
    Gibt eine Liste von Service-Namen ohne "notify." Prefix zurück.
    """
    if not settings.ha_url or not settings.ha_token:
        return []
    url = f"{settings.ha_url}/api/services"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, headers=_headers())
        if r.status_code != 200:
            log.warning("HA /api/services: %s", r.status_code)
            return []
        result: list[str] = []
        for entry in r.json():
            if entry.get("domain") != "notify":
                continue
            for svc_name in entry.get("services", {}):
                if svc_name.startswith("mobile_app_"):
                    result.append(svc_name)
        return sorted(result)
    except httpx.HTTPError as e:
        log.warning("list_mobile_app_notify_services failed: %s", e)
        return []


async def get_state(entity_id: str) -> dict | None:
    if not settings.ha_url or not settings.ha_token:
        return None
    url = f"{settings.ha_url}/api/states/{entity_id}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, headers=_headers())
        if r.status_code == 200:
            return r.json()
    except httpx.HTTPError:
        return None
    return None
