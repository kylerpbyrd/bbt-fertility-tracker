"""
Home Assistant REST API client.

Responsibilities:
  1. Publish BBT tracker insights as HA entity states after each cycle analysis.
  2. Poll a configured HA sensor entity to auto-import temperature readings.

All network calls are best-effort: failures are logged as warnings and never
crash the add-on, because HA connectivity is not guaranteed.
"""
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from datetime import date
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_HA_API_BASE = "http://supervisor/core/api"
_SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------

def _request(method: str, path: str, payload: dict | None = None) -> dict | None:
    """
    Make an authenticated request to the HA Core REST API via Supervisor proxy.
    Returns parsed JSON on success, None on any failure.
    """
    if not _SUPERVISOR_TOKEN:
        return None

    url = f"{_HA_API_BASE}{path}"
    body = json.dumps(payload).encode() if payload else None
    headers = {
        "Authorization": f"Bearer {_SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            logger.error("HA API: Unauthorized — check SUPERVISOR_TOKEN")
        elif exc.code != 404:
            logger.warning("HA API %s %s → HTTP %d", method, path, exc.code)
        return None
    except Exception as exc:
        logger.debug("HA API %s %s failed: %s", method, path, exc)
        return None


# ---------------------------------------------------------------------------
# Entity publishing
# ---------------------------------------------------------------------------

def publish_entity(entity_id: str, state: str, attributes: dict | None = None) -> bool:
    """POST a state update for a single HA entity."""
    payload: dict = {"state": state}
    if attributes:
        payload["attributes"] = {k: v for k, v in attributes.items() if v is not None}
    return _request("POST", f"/states/{entity_id}", payload) is not None


def get_entity(entity_id: str) -> dict | None:
    """Return the current state dict of a HA entity, or None."""
    return _request("GET", f"/states/{entity_id}")


def publish_profile_entities(profile: dict, insights: dict,
                             next_period: str | None = None) -> None:
    """
    Publish all tracked BBT entities for one profile to Home Assistant.

    Entity roster (all prefixed `bbt_{slug}_`):
      sensor.bbt_{slug}_cycle_day
      sensor.bbt_{slug}_cycle_phase
      sensor.bbt_{slug}_last_temp
      binary_sensor.bbt_{slug}_fertile_window
      binary_sensor.bbt_{slug}_ovulation_confirmed
      sensor.bbt_{slug}_ovulation_date
      sensor.bbt_{slug}_next_period_date
      sensor.bbt_{slug}_luteal_length
      sensor.bbt_{slug}_avg_cycle_length
    """
    slug = profile.get("slug", "default")
    name = profile.get("name", "Default")
    unit = profile.get("temp_unit", "F")

    cycle_day = insights.get("cycle_day", "unknown")
    phase = insights.get("phase", "unknown")
    last_temp = insights.get("last_temp")
    ov_confirmed = bool(insights.get("ovulation_confirmed"))
    ov_date = insights.get("ovulation_date") or "none"
    luteal = insights.get("luteal_length")
    avg_cycle = insights.get("avg_cycle_length")

    # Determine fertile window status
    in_fertile = False
    fertile_start = insights.get("fertile_start_date") or insights.get("fertile_start")
    fertile_end = insights.get("fertile_end_date") or insights.get("fertile_end")
    if fertile_start and fertile_end:
        try:
            in_fertile = (
                date.fromisoformat(fertile_start)
                <= date.today()
                <= date.fromisoformat(fertile_end)
            )
        except ValueError:
            pass

    entities = [
        (
            f"sensor.bbt_{slug}_cycle_day",
            str(cycle_day),
            {"friendly_name": f"BBT {name} Cycle Day",
             "unit_of_measurement": "days",
             "icon": "mdi:calendar-today"},
        ),
        (
            f"sensor.bbt_{slug}_cycle_phase",
            phase,
            {"friendly_name": f"BBT {name} Cycle Phase",
             "icon": "mdi:water-circle"},
        ),
        (
            f"binary_sensor.bbt_{slug}_fertile_window",
            "on" if in_fertile else "off",
            {"friendly_name": f"BBT {name} Fertile Window",
             "icon": "mdi:seed",
             "device_class": "presence"},
        ),
        (
            f"binary_sensor.bbt_{slug}_ovulation_confirmed",
            "on" if ov_confirmed else "off",
            {"friendly_name": f"BBT {name} Ovulation Confirmed",
             "icon": "mdi:check-circle",
             "device_class": "presence"},
        ),
        (
            f"sensor.bbt_{slug}_ovulation_date",
            ov_date,
            {"friendly_name": f"BBT {name} Ovulation Date",
             "icon": "mdi:calendar-star",
             "device_class": "date"},
        ),
        (
            f"sensor.bbt_{slug}_next_period_date",
            next_period or "none",
            {"friendly_name": f"BBT {name} Next Period Date",
             "icon": "mdi:calendar-arrow-right",
             "device_class": "date"},
        ),
    ]

    if last_temp is not None:
        entities.append((
            f"sensor.bbt_{slug}_last_temp",
            str(round(float(last_temp), 2)),
            {"friendly_name": f"BBT {name} Last Temperature",
             "unit_of_measurement": f"°{unit}",
             "icon": "mdi:thermometer",
             "device_class": "temperature"},
        ))

    if luteal is not None:
        entities.append((
            f"sensor.bbt_{slug}_luteal_length",
            str(luteal),
            {"friendly_name": f"BBT {name} Luteal Length",
             "unit_of_measurement": "days",
             "icon": "mdi:timer-sand"},
        ))

    if avg_cycle is not None:
        entities.append((
            f"sensor.bbt_{slug}_avg_cycle_length",
            str(avg_cycle),
            {"friendly_name": f"BBT {name} Avg Cycle Length",
             "unit_of_measurement": "days",
             "icon": "mdi:chart-timeline-variant"},
        ))

    for entity_id, state, attrs in entities:
        publish_entity(entity_id, state, attrs)
        logger.debug("Published %s = %s", entity_id, state)


# ---------------------------------------------------------------------------
# Sensor polling
# ---------------------------------------------------------------------------

def poll_sensor_reading(entity_id: str) -> float | None:
    """
    Fetch the current numeric state of a HA sensor entity.
    Returns a float, or None if the entity is unavailable / non-numeric.
    """
    if not entity_id or not entity_id.strip():
        return None

    data = get_entity(entity_id.strip())
    if not data:
        return None

    state = data.get("state", "")
    if state in ("unknown", "unavailable", ""):
        return None

    try:
        return float(state)
    except (ValueError, TypeError):
        logger.warning("HA sensor %s: non-numeric state %r", entity_id, state)
        return None


# ---------------------------------------------------------------------------
# Background polling timer
# ---------------------------------------------------------------------------

_poll_timer: Optional[threading.Timer] = None
_poll_callback: Optional[Callable] = None


def start_polling(interval_minutes: int, callback: Callable) -> None:
    """Start a recurring background timer that calls *callback* every interval."""
    global _poll_callback
    _poll_callback = callback
    _schedule_next(interval_minutes)
    logger.info("HA sensor polling started (every %d min)", interval_minutes)


def stop_polling() -> None:
    global _poll_timer
    if _poll_timer:
        _poll_timer.cancel()
        _poll_timer = None


# ---------------------------------------------------------------------------
# Lovelace resource registration
# ---------------------------------------------------------------------------

_CARD_URL = "/hassio/ingress/bbt_fertility_tracker/bbt-card.js"
_OLD_CARD_URL = "/local/bbt-card.js"


def register_lovelace_card() -> None:
    """
    Register bbt-card.js as a Lovelace module resource via the HA REST API.
    Removes the old /local/ registration if present to avoid duplicate definitions.
    Safe to call every startup — skips if already registered.
    """
    resources = _request("GET", "/lovelace/resources")
    if not isinstance(resources, list):
        logger.warning("Lovelace resources API not available (YAML mode?)")
        return

    # Remove stale /local/ registration
    for r in resources:
        if r.get("url") == _OLD_CARD_URL:
            _request("DELETE", f"/lovelace/resources/{r['id']}")
            logger.info("Removed old Lovelace resource: %s", _OLD_CARD_URL)

    resources = _request("GET", "/lovelace/resources") or []
    if any(r.get("url") == _CARD_URL for r in resources):
        logger.debug("Lovelace card already registered")
        return

    result = _request("POST", "/lovelace/resources", {
        "res_type": "module",
        "url": _CARD_URL,
    })
    if result:
        logger.info("Lovelace card registered at %s", _CARD_URL)
    else:
        logger.warning("Could not register Lovelace card resource")


def _schedule_next(interval_minutes: int) -> None:
    global _poll_timer
    if _poll_timer:
        _poll_timer.cancel()
    _poll_timer = threading.Timer(
        interval_minutes * 60, _fire, args=(interval_minutes,)
    )
    _poll_timer.daemon = True
    _poll_timer.start()


def _fire(interval_minutes: int) -> None:
    if _poll_callback:
        try:
            _poll_callback()
        except Exception as exc:
            logger.error("Polling callback error: %s", exc, exc_info=True)
    _schedule_next(interval_minutes)
