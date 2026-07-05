"""
Ovulation detection via the sympto-thermal method.

Rules implemented
─────────────────
Standard rule
  3 consecutive non-discarded temperatures all strictly above the coverline.
  Ovulation day = the day BEFORE the first elevated temperature.

Conservative variant
  Same as standard, but the 3rd elevated temperature must additionally be
  at least 0.2 °F (0.1 °C) above the coverline.

"Witch's hat" exception
  If the 2nd of the 3 required elevated temperatures dips at or below the
  coverline, but a 4th temperature confirms the post-shift phase, ovulation
  is still detected.  The dip day is ignored.

Scan begins at MIN_CYCLE_DAY (default 6) because ovulation cannot occur
before that point.

A "possible" detection (confidence='possible') is returned when exactly 2
consecutive elevated temperatures have been seen — indicating the shift is
likely but not yet confirmed.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from algorithms.coverline import compute_coverline, THRESHOLD_F, THRESHOLD_C

# Ovulation cannot occur before this cycle day
MIN_CYCLE_DAY: int = 6

# Extra margin required for the conservative method
_EXTRA_F: float = 0.2
_EXTRA_C: float = 0.1

# Maximum gap in cycle days between "consecutive" readings
_MAX_GAP: int = 2


@dataclass
class OvulationResult:
    """Holds the outcome of a single ovulation-detection run."""

    detected: bool
    ovulation_date: Optional[str] = None       # Day before first elevated temp
    shift_start_date: Optional[str] = None     # Date of first elevated temp
    coverline: Optional[float] = None
    method: str = "none"
    confidence: str = "none"                   # 'confirmed' | 'possible' | 'none'
    consecutive_elevated: int = 0
    shift_day_index: int = -1                  # Index in the active-temp list


def detect_ovulation(
    temps: list[dict],
    unit: str = "F",
    method: str = "standard",
) -> OvulationResult:
    """
    Detect ovulation from a list of temperature records.

    Args:
        temps: List of dicts, each with keys:
                 date          – ISO date string (YYYY-MM-DD)
                 cycle_day     – 1-based integer cycle day
                 temp_value    – float
                 is_discarded  – truthy/falsy
               The list does NOT need to be pre-sorted.
        unit:   'F' or 'C'
        method: 'standard' or 'conservative'

    Returns:
        OvulationResult describing the detection outcome.
    """
    active = sorted(
        [t for t in temps if not t.get("is_discarded", False)],
        key=lambda t: t["cycle_day"],
    )
    n = len(active)
    if n < 4:
        return OvulationResult(detected=False)

    extra = _EXTRA_F if unit == "F" else _EXTRA_C

    # ── Confirmed detection scan ────────────────────────────────────────────
    for i in range(n):
        if active[i]["cycle_day"] < MIN_CYCLE_DAY:
            continue

        pre_values = [active[j]["temp_value"] for j in range(i)]
        if len(pre_values) < 3:
            continue

        coverline = compute_coverline(pre_values, unit)
        if coverline is None:
            continue

        if i + 2 >= n:
            break

        t0, t1, t2 = active[i], active[i + 1], active[i + 2]

        # Require roughly consecutive cycle days
        if (t1["cycle_day"] - t0["cycle_day"] > _MAX_GAP or
                t2["cycle_day"] - t1["cycle_day"] > _MAX_GAP):
            continue

        all_above = (
            t0["temp_value"] > coverline
            and t1["temp_value"] > coverline
            and t2["temp_value"] > coverline
        )

        if all_above:
            # Conservative extra-height check on 3rd temperature
            if method == "conservative" and t2["temp_value"] < coverline + extra:
                continue

            ov_date = (
                date.fromisoformat(t0["date"]) - timedelta(days=1)
            ).isoformat()
            return OvulationResult(
                detected=True,
                ovulation_date=ov_date,
                shift_start_date=t0["date"],
                coverline=coverline,
                method=method,
                confidence="confirmed",
                consecutive_elevated=3,
                shift_day_index=i,
            )

        # Witch's hat: t0 and t2 above, t1 dips, but t3 also above
        if (i + 3 < n
                and t0["temp_value"] > coverline
                and t2["temp_value"] > coverline):
            t3 = active[i + 3]
            if (t3["cycle_day"] - t2["cycle_day"] <= _MAX_GAP
                    and t3["temp_value"] > coverline):
                ov_date = (
                    date.fromisoformat(t0["date"]) - timedelta(days=1)
                ).isoformat()
                return OvulationResult(
                    detected=True,
                    ovulation_date=ov_date,
                    shift_start_date=t0["date"],
                    coverline=coverline,
                    method=f"{method}_witchhat",
                    confidence="confirmed",
                    consecutive_elevated=3,
                    shift_day_index=i,
                )

    # ── Possible detection (2 elevated temps) ───────────────────────────────
    for i in range(n):
        if active[i]["cycle_day"] < MIN_CYCLE_DAY:
            continue

        pre_values = [active[j]["temp_value"] for j in range(i)]
        if len(pre_values) < 3:
            continue

        coverline = compute_coverline(pre_values, unit)
        if coverline is None:
            continue

        if i + 1 >= n:
            break

        t0, t1 = active[i], active[i + 1]
        if t1["cycle_day"] - t0["cycle_day"] > _MAX_GAP:
            continue
        if t0["temp_value"] > coverline and t1["temp_value"] > coverline:
            ov_date = (
                date.fromisoformat(t0["date"]) - timedelta(days=1)
            ).isoformat()
            return OvulationResult(
                detected=False,
                ovulation_date=ov_date,
                shift_start_date=t0["date"],
                coverline=coverline,
                method=method,
                confidence="possible",
                consecutive_elevated=2,
                shift_day_index=i,
            )

    # ── No shift found — return best-effort coverline estimate ──────────────
    all_values = [t["temp_value"] for t in active]
    est = compute_coverline(all_values, unit) if all_values else None
    return OvulationResult(detected=False, coverline=est)
