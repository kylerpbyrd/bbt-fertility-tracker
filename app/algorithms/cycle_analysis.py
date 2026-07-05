"""
Cycle analysis orchestrator.

Wires together: coverline → ovulation detection → fertile window → insights,
then stores the result in the computed_insights table and returns the dict
so callers can immediately publish to Home Assistant.

Public API
──────────
  analyze_cycle(cycle_id, db)  → dict of insights (also persisted to DB)
  predict_next_period(db, profile_id, cycle_id) → ISO date string or None
  get_current_cycle_day(cycle_start_date) → int (1-based)
"""
import logging
from datetime import date, timedelta
from typing import Optional

from algorithms.ovulation import detect_ovulation, OvulationResult
from algorithms.fertile_window import compute_fertile_window

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_current_cycle_day(cycle_start_date: str) -> int:
    """Return today's 1-based cycle day."""
    start = date.fromisoformat(cycle_start_date)
    return max(1, (date.today() - start).days + 1)


def _past_cycle_lengths(db, profile_id: int, exclude_cycle_id: int,
                        limit: int = 12) -> list[int]:
    rows = db.execute(
        """
        SELECT cycle_length FROM cycles
        WHERE profile_id = ? AND id != ? AND cycle_length IS NOT NULL
        ORDER BY start_date DESC LIMIT ?
        """,
        (profile_id, exclude_cycle_id, limit),
    ).fetchall()
    return [r["cycle_length"] for r in rows]


def _count_consecutive_elevated(temps: list[dict], coverline: float,
                                after_date: str) -> int:
    """
    Count how many consecutive non-discarded temperatures above *coverline*
    exist starting from (and including) *after_date*.
    """
    relevant = sorted(
        [t for t in temps if not t.get("is_discarded") and t["date"] >= after_date],
        key=lambda t: t["date"],
    )
    count = 0
    for t in relevant:
        if t["temp_value"] > coverline:
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_cycle(cycle_id: int, db) -> dict:
    """
    Run full cycle analysis and persist results to computed_insights.

    Steps:
      1. Load all temperatures and fertility signs for the cycle.
      2. Detect ovulation (sympto-thermal method).
      3. Compute fertile window using ovulation result + cycle history.
      4. Derive luteal length, short-luteal flag, pregnancy indicator.
      5. Upsert into computed_insights.
      6. Return a plain dict of all computed values.
    """
    cycle = db.execute("SELECT * FROM cycles WHERE id = ?", (cycle_id,)).fetchone()
    if not cycle:
        return {}

    profile = db.execute(
        "SELECT * FROM profiles WHERE id = ?", (cycle["profile_id"],)
    ).fetchone()
    unit = profile["temp_unit"] if profile else "F"
    method = profile["interpretation_method"] if profile else "standard"

    # Load temperatures with cycle_day computed in SQL
    temp_rows = db.execute(
        """
        SELECT
            date,
            temp_value,
            is_discarded,
            CAST(julianday(date) - julianday(?) + 1 AS INTEGER) AS cycle_day
        FROM temperatures
        WHERE cycle_id = ?
        ORDER BY date ASC
        """,
        (cycle["start_date"], cycle_id),
    ).fetchall()
    temps = [dict(r) for r in temp_rows]

    # Load fertility signs for mucus rule
    sign_rows = db.execute(
        "SELECT date, cervical_mucus FROM fertility_signs WHERE cycle_id = ?",
        (cycle_id,),
    ).fetchall()
    fertility_signs = [dict(r) for r in sign_rows]

    # ── 1. Detect ovulation ──────────────────────────────────────────────────
    ov: OvulationResult = detect_ovulation(temps, unit=unit, method=method)

    # ── 2. Fertile window ────────────────────────────────────────────────────
    past_lengths = _past_cycle_lengths(db, cycle["profile_id"], cycle_id)
    fw = compute_fertile_window(
        cycle_start_date=cycle["start_date"],
        ovulation_result=ov,
        fertility_signs=fertility_signs,
        past_cycle_lengths=past_lengths,
        unit=unit,
    )

    # ── 3. Luteal length ─────────────────────────────────────────────────────
    luteal_length: Optional[int] = None
    if ov.ovulation_date:
        ov_date_obj = date.fromisoformat(ov.ovulation_date)
        end_date_obj = (
            date.fromisoformat(cycle["end_date"])
            if cycle["end_date"]
            else date.today()
        )
        luteal_length = max(0, (end_date_obj - ov_date_obj).days)

    # ── 4. Consecutive elevated temps & special flags ────────────────────────
    consecutive = 0
    if ov.shift_start_date and ov.coverline:
        consecutive = _count_consecutive_elevated(temps, ov.coverline, ov.shift_start_date)

    pregnancy_indicator = consecutive >= 18
    short_luteal = luteal_length is not None and luteal_length < 10

    # ── 5. Persist ───────────────────────────────────────────────────────────
    db.execute(
        """
        INSERT INTO computed_insights (
            cycle_id, coverline, ovulation_date, ovulation_confirmed,
            ovulation_method, fertile_start_date, fertile_end_date,
            post_ovulatory_infertile_date, luteal_length, luteal_phase_short,
            pregnancy_indicator, consecutive_elevated_temps, computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(cycle_id) DO UPDATE SET
            coverline                    = excluded.coverline,
            ovulation_date               = excluded.ovulation_date,
            ovulation_confirmed          = excluded.ovulation_confirmed,
            ovulation_method             = excluded.ovulation_method,
            fertile_start_date           = excluded.fertile_start_date,
            fertile_end_date             = excluded.fertile_end_date,
            post_ovulatory_infertile_date = excluded.post_ovulatory_infertile_date,
            luteal_length                = excluded.luteal_length,
            luteal_phase_short           = excluded.luteal_phase_short,
            pregnancy_indicator          = excluded.pregnancy_indicator,
            consecutive_elevated_temps   = excluded.consecutive_elevated_temps,
            computed_at                  = datetime('now')
        """,
        (
            cycle_id,
            ov.coverline,
            ov.ovulation_date,
            1 if ov.detected else 0,
            ov.method,
            fw.get("fertile_start"),
            fw.get("fertile_end"),
            fw.get("post_ovulatory_infertile"),
            luteal_length,
            1 if short_luteal else 0,
            1 if pregnancy_indicator else 0,
            consecutive,
        ),
    )
    db.commit()

    return {
        "cycle_id": cycle_id,
        "coverline": ov.coverline,
        "ovulation_date": ov.ovulation_date,
        "ovulation_confirmed": ov.detected,
        "ovulation_confidence": ov.confidence,
        "ovulation_method": ov.method,
        "fertile_start": fw.get("fertile_start"),
        "fertile_end": fw.get("fertile_end"),
        "post_ovulatory_infertile": fw.get("post_ovulatory_infertile"),
        "luteal_length": luteal_length,
        "short_luteal": short_luteal,
        "pregnancy_indicator": pregnancy_indicator,
        "consecutive_elevated": consecutive,
    }


# ---------------------------------------------------------------------------
# Period prediction
# ---------------------------------------------------------------------------

def predict_next_period(db, profile_id: int, current_cycle_id: int) -> Optional[str]:
    """
    Predict the next period start date.

    Strategy:
      If ovulation is confirmed, use ovulation_date + average luteal length.
      Otherwise fall back to cycle_start + average cycle length.
    """
    cycle = db.execute(
        "SELECT start_date FROM cycles WHERE id = ?", (current_cycle_id,)
    ).fetchone()
    if not cycle:
        return None

    insight = db.execute(
        "SELECT ovulation_date FROM computed_insights WHERE cycle_id = ?",
        (current_cycle_id,),
    ).fetchone()

    if insight and insight["ovulation_date"]:
        # Average luteal length from past cycles
        rows = db.execute(
            """
            SELECT ci.luteal_length FROM computed_insights ci
            JOIN cycles c ON c.id = ci.cycle_id
            WHERE c.profile_id = ? AND ci.luteal_length IS NOT NULL
              AND ci.luteal_length > 0
            ORDER BY c.start_date DESC LIMIT 6
            """,
            (profile_id,),
        ).fetchall()
        avg_luteal = round(sum(r["luteal_length"] for r in rows) / len(rows)) if rows else 14
        ov_date = date.fromisoformat(insight["ovulation_date"])
        return (ov_date + timedelta(days=avg_luteal + 1)).isoformat()

    # Fallback: average cycle length
    rows = db.execute(
        """
        SELECT cycle_length FROM cycles
        WHERE profile_id = ? AND cycle_length IS NOT NULL
        ORDER BY start_date DESC LIMIT 6
        """,
        (profile_id,),
    ).fetchall()
    avg_len = round(sum(r["cycle_length"] for r in rows) / len(rows)) if rows else 28
    start = date.fromisoformat(cycle["start_date"])
    return (start + timedelta(days=avg_len)).isoformat()
