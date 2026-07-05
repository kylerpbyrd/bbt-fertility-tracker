"""
Coverline calculation for BBT fertility charting.

The coverline is the highest of up to 6 consecutive non-discarded temperatures
immediately before the suspected thermal shift, plus a small threshold
(0.1 °F / 0.05 °C).  It serves as the baseline that all three post-ovulatory
temperatures must exceed for ovulation to be confirmed.
"""
from typing import Optional

# Threshold added to the highest pre-shift temperature
THRESHOLD_F: float = 0.1
THRESHOLD_C: float = 0.05


def compute_coverline(pre_shift_temps: list[float], unit: str = "F") -> Optional[float]:
    """
    Compute the coverline from a list of pre-shift temperatures.

    Uses at most the last 6 values provided.

    Args:
        pre_shift_temps: Non-discarded temperatures recorded before the
                         thermal shift, sorted oldest → newest.
        unit: 'F' or 'C'

    Returns:
        Coverline value rounded to 2 decimal places, or None if the list
        is empty.
    """
    if not pre_shift_temps:
        return None
    sample = pre_shift_temps[-6:]
    threshold = THRESHOLD_F if unit == "F" else THRESHOLD_C
    return round(max(sample) + threshold, 2)


def estimate_baseline(temps: list[float], unit: str = "F") -> Optional[float]:
    """
    Estimate a low-phase baseline for display before ovulation is confirmed.

    Uses the average of the lowest 6 recorded temperatures as a rough
    indicator of the pre-ovulatory phase level.

    Args:
        temps: All non-discarded temperatures in the cycle so far.
        unit: 'F' or 'C'  (currently unused but kept for API consistency)

    Returns:
        Estimated baseline rounded to 2 decimal places, or None.
    """
    if not temps:
        return None
    sample = sorted(temps)[:6]
    return round(sum(sample) / len(sample), 2)
