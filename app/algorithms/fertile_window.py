"""
Fertile window calculation and cycle-phase determination.

Fertile window boundaries
─────────────────────────
Pre-ovulatory fertile start  (earlier of):
  Calendar rule : shortest_past_cycle_length − 18  (Kippley/Weschler method)
  Mucus rule    : first day of fertile cervical mucus (watery or egg-white)
  Default       : Day 8 when no cycle history exists

Post-ovulatory infertility starts:
  Day 4 after the 3rd consecutive elevated temperature above the coverline
  (i.e. shift_start_date + 3 days).

The fertile window end is the day before post-ovulatory infertility starts.

Cycle phases
────────────
menstruation · pre_ovulatory · fertile · ovulation · luteal
"""
from datetime import date, timedelta
from typing import Optional

# Cervical-mucus types that indicate the fertile phase
_FERTILE_MUCUS: frozenset[str] = frozenset({"watery", "egg_white"})

# Minimum reasonable cycle length used to clamp the calendar rule
_MIN_CYCLE: int = 21
_DEFAULT_FERTILE_START_DAY: int = 8


def compute_fertile_window(
    cycle_start_date: str,
    ovulation_result,                    # OvulationResult from ovulation.py
    fertility_signs: list[dict],         # [{date, cervical_mucus}]
    past_cycle_lengths: list[int],
    unit: str = "F",                     # kept for API symmetry
) -> dict:
    """
    Compute the fertile window boundaries for a cycle.

    Returns a dict with:
        fertile_start           – ISO date string
        fertile_end             – ISO date string or None
        post_ovulatory_infertile – ISO date string or None
        calendar_rule_day       – integer day number used for calendar rule
        mucus_triggered         – bool (was start moved earlier by mucus?)
    """
    cycle_start = date.fromisoformat(cycle_start_date)

    # ── Pre-ovulatory start ─────────────────────────────────────────────────
    if past_cycle_lengths:
        shortest = max(min(past_cycle_lengths), _MIN_CYCLE)
        calendar_day = max(1, shortest - 18)
    else:
        calendar_day = _DEFAULT_FERTILE_START_DAY

    calendar_date = cycle_start + timedelta(days=calendar_day - 1)

    # First day of fertile mucus
    mucus_date: Optional[date] = None
    for sign in sorted(fertility_signs, key=lambda s: s["date"]):
        if sign.get("cervical_mucus", "").lower() in _FERTILE_MUCUS:
            mucus_date = date.fromisoformat(sign["date"])
            break

    if mucus_date is not None:
        fertile_start = min(calendar_date, mucus_date)
        mucus_triggered = mucus_date < calendar_date
    else:
        fertile_start = calendar_date
        mucus_triggered = False

    # ── Post-ovulatory infertility start & fertile end ──────────────────────
    fertile_end: Optional[date] = None
    post_ov_infertile: Optional[date] = None

    if ovulation_result.detected and ovulation_result.shift_start_date:
        # Confirmed: infertile from shift_start_date + 3 days
        shift_start = date.fromisoformat(ovulation_result.shift_start_date)
        post_ov_infertile = shift_start + timedelta(days=3)
        fertile_end = post_ov_infertile - timedelta(days=1)
    elif ovulation_result.ovulation_date:
        # Possible: conservative estimate
        ov_date = date.fromisoformat(ovulation_result.ovulation_date)
        fertile_end = ov_date + timedelta(days=2)
        post_ov_infertile = fertile_end + timedelta(days=1)

    return {
        "fertile_start": fertile_start.isoformat(),
        "fertile_end": fertile_end.isoformat() if fertile_end else None,
        "post_ovulatory_infertile": post_ov_infertile.isoformat() if post_ov_infertile else None,
        "calendar_rule_day": calendar_day,
        "mucus_triggered": mucus_triggered,
    }


def get_cycle_phase(
    current_date: date,
    cycle_start: date,
    flow_days: list[str],
    fertile_window: dict,
    ovulation_date: Optional[str],
    ovulation_confirmed: bool,
    post_ov_infertile: Optional[str],
) -> str:
    """
    Return a phase label for *current_date* within this cycle.

    Phase precedence (highest → lowest):
      1. menstruation  – current_date in flow_days
      2. luteal        – post-ovulatory infertility has started
      3. ovulation     – confirmed ovulation day
      4. fertile       – within the fertile window (and pre-ovulatory)
      5. pre_ovulatory – default
    """
    today_str = current_date.isoformat()

    if today_str in flow_days:
        return "menstruation"

    if post_ov_infertile:
        try:
            if current_date >= date.fromisoformat(post_ov_infertile):
                return "luteal"
        except ValueError:
            pass

    if ovulation_confirmed and ovulation_date and today_str == ovulation_date:
        return "ovulation"

    fs = fertile_window.get("fertile_start")
    fe = fertile_window.get("fertile_end")
    if fs and fe:
        try:
            if date.fromisoformat(fs) <= current_date <= date.fromisoformat(fe):
                # After confirmed ovulation we are already in luteal
                if ovulation_confirmed and ovulation_date:
                    if current_date > date.fromisoformat(ovulation_date):
                        return "luteal"
                return "fertile"
        except ValueError:
            pass

    return "pre_ovulatory"
