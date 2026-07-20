from algorithms.coverline import compute_coverline
from algorithms.fertile_window import compute_fertile_window
from algorithms.ovulation import detect_ovulation


def _temperature(day, value, discarded=False):
    return {
        "date": f"2026-01-{day:02d}",
        "cycle_day": day,
        "temp_value": value,
        "is_discarded": discarded,
    }


def test_coverline_uses_the_latest_six_readings_and_unit_threshold():
    assert compute_coverline([97.0, 97.1, 97.2, 97.3, 97.4, 97.5, 98.0]) == 98.1
    assert compute_coverline([36.4, 36.5], unit="C") == 36.55


def test_standard_three_day_shift_confirms_ovulation():
    temps = [
        _temperature(1, 97.0), _temperature(2, 97.1), _temperature(3, 97.2),
        _temperature(4, 97.1), _temperature(5, 97.3), _temperature(6, 97.2),
        _temperature(7, 97.5), _temperature(8, 97.6), _temperature(9, 97.7),
    ]

    result = detect_ovulation(temps)

    assert result.detected is True
    assert result.confidence == "confirmed"
    assert result.shift_start_date == "2026-01-07"
    assert result.ovulation_date == "2026-01-06"
    assert result.coverline == 97.4


def test_discarded_reading_does_not_prevent_a_confirmed_shift():
    temps = [
        _temperature(1, 97.0), _temperature(2, 97.1), _temperature(3, 97.2),
        _temperature(4, 97.1), _temperature(5, 97.3), _temperature(6, 97.2),
        _temperature(7, 97.8, discarded=True), _temperature(8, 97.5),
        _temperature(9, 97.6), _temperature(10, 97.7),
    ]

    result = detect_ovulation(temps)

    assert result.detected is True
    assert result.shift_start_date == "2026-01-08"


def test_fertile_mucus_moves_the_window_start_earlier_than_calendar_rule():
    no_ovulation = detect_ovulation([])

    window = compute_fertile_window(
        cycle_start_date="2026-01-01",
        ovulation_result=no_ovulation,
        fertility_signs=[{"date": "2026-01-04", "cervical_mucus": "egg_white"}],
        past_cycle_lengths=[30],
    )

    assert window["fertile_start"] == "2026-01-04"
    assert window["calendar_rule_day"] == 12
    assert window["mucus_triggered"] is True
