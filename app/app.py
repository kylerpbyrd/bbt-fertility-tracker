"""
BBT Fertility Tracker — Flask application entry-point.

Run from: python3 /app/app.py
PYTHONPATH must include /app (set in run.sh).
"""
import logging
import os
import threading
from datetime import date, datetime, timedelta

from flask import (Flask, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)

from algorithms.cycle_analysis import (analyze_cycle, get_current_cycle_day,
                                       predict_next_period)
from algorithms.fertile_window import get_cycle_phase
import ha_client
from db import (get_db, get_active_profile, get_or_create_current_cycle,
                init_db, slugify)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HA Ingress path middleware
# ---------------------------------------------------------------------------


class _IngressMiddleware:
    """Strip the HA ingress path prefix so Flask sees a normal SCRIPT_NAME."""

    def __init__(self, wsgi_app):
        self._app = wsgi_app

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_INGRESS_PATH", "").rstrip("/")
        if prefix:
            environ["SCRIPT_NAME"] = prefix
            path = environ.get("PATH_INFO", "")
            if path.startswith(prefix):
                environ["PATH_INFO"] = path[len(prefix):] or "/"
        return self._app(environ, start_response)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

DATA_PATH = os.environ.get("DATA_PATH", "/data")
_SECRET_KEY_FILE = os.path.join(DATA_PATH, "secret_key")
TEMP_UNIT = os.environ.get("BBT_TEMP_UNIT", "F")
HA_SENSOR_ENTITY = os.environ.get("BBT_HA_SENSOR_ENTITY", "")
POLL_INTERVAL = int(os.environ.get("BBT_POLL_INTERVAL", "15"))
CHART_JS_LOCAL = os.path.exists("/app/static/js/chart.umd.min.js")


def _get_or_create_secret_key() -> str:
    os.makedirs(DATA_PATH, exist_ok=True)
    if os.path.isfile(_SECRET_KEY_FILE):
        return open(_SECRET_KEY_FILE).read().strip()
    key = os.urandom(32).hex()
    with open(_SECRET_KEY_FILE, "w") as fh:
        fh.write(key)
    return key


app = Flask(__name__)
app.secret_key = _get_or_create_secret_key()
app.wsgi_app = _IngressMiddleware(app.wsgi_app)


# ---------------------------------------------------------------------------
# Request lifecycle
# ---------------------------------------------------------------------------

@app.before_request
def _open_db_and_profile():
    g.db = get_db()
    g.profile = get_active_profile(g.db, session.get("profile_id"))
    if not g.profile:
        _create_default_profile(g.db)
        g.profile = get_active_profile(g.db)
    g.cycle = None
    if g.profile:
        g.cycle = get_or_create_current_cycle(g.db, g.profile["id"])


@app.teardown_appcontext
def _close_db(exc):
    db = getattr(g, "db", None)
    if db:
        db.close()


@app.context_processor
def _inject_globals():
    return {
        "profile": getattr(g, "profile", None),
        "cycle": getattr(g, "cycle", None),
        "chart_js_local": CHART_JS_LOCAL,
    }


def _create_default_profile(db):
    db.execute(
        """
        INSERT OR IGNORE INTO profiles (name, slug, temp_unit, ha_sensor_entity, active)
        VALUES ('Default', 'default', ?, ?, 1)
        """,
        (TEMP_UNIT, HA_SENSOR_ENTITY),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Background analysis helper (runs in a daemon thread)
# ---------------------------------------------------------------------------

def _async_analyze_and_publish(cycle_id: int, profile: dict):
    db = get_db()
    try:
        insights = analyze_cycle(cycle_id, db)

        cycle = db.execute("SELECT * FROM cycles WHERE id = ?", (cycle_id,)).fetchone()
        if not cycle:
            return

        insights["cycle_day"] = get_current_cycle_day(cycle["start_date"])

        last_temp = db.execute(
            """
            SELECT temp_value FROM temperatures
            WHERE cycle_id = ? AND is_discarded = 0
            ORDER BY date DESC LIMIT 1
            """,
            (cycle_id,),
        ).fetchone()
        insights["last_temp"] = last_temp["temp_value"] if last_temp else None

        flow_days = _get_flow_days(db, cycle_id)
        phase = get_cycle_phase(
            current_date=date.today(),
            cycle_start=date.fromisoformat(cycle["start_date"]),
            flow_days=flow_days,
            fertile_window={
                "fertile_start": insights.get("fertile_start"),
                "fertile_end": insights.get("fertile_end"),
            },
            ovulation_date=insights.get("ovulation_date"),
            ovulation_confirmed=bool(insights.get("ovulation_confirmed")),
            post_ov_infertile=insights.get("post_ovulatory_infertile"),
        )
        insights["phase"] = phase

        past = db.execute(
            """
            SELECT cycle_length FROM cycles
            WHERE profile_id = ? AND cycle_length IS NOT NULL
            ORDER BY start_date DESC LIMIT 6
            """,
            (profile["id"],),
        ).fetchall()
        if past:
            insights["avg_cycle_length"] = round(
                sum(r["cycle_length"] for r in past) / len(past)
            )

        next_period = predict_next_period(db, profile["id"], cycle_id)
        ha_client.publish_profile_entities(profile, insights, next_period)

    except Exception as exc:
        logger.error("Analysis/publish error: %s", exc, exc_info=True)
    finally:
        db.close()


def _trigger_analysis(cycle_id: int, profile: dict):
    t = threading.Thread(
        target=_async_analyze_and_publish,
        args=(cycle_id, profile),
        daemon=True,
    )
    t.start()


# ---------------------------------------------------------------------------
# Internal query helpers
# ---------------------------------------------------------------------------

def _get_flow_days(db, cycle_id: int) -> list[str]:
    rows = db.execute(
        """
        SELECT date FROM fertility_signs
        WHERE cycle_id = ? AND menstrual_flow IN ('spotting','light','medium','heavy')
        ORDER BY date
        """,
        (cycle_id,),
    ).fetchall()
    return [r["date"] for r in rows]


def _close_and_start_cycle(db, profile_id: int, new_start: str):
    """Close the currently open cycle and start a new one."""
    current = db.execute(
        """
        SELECT * FROM cycles WHERE profile_id = ? AND end_date IS NULL
        ORDER BY start_date DESC LIMIT 1
        """,
        (profile_id,),
    ).fetchone()
    if current:
        start = date.fromisoformat(current["start_date"])
        end = date.fromisoformat(new_start) - timedelta(days=1)
        if end >= start:
            db.execute(
                "UPDATE cycles SET end_date = ?, cycle_length = ? WHERE id = ?",
                (end.isoformat(), (end - start).days + 1, current["id"]),
            )
    db.execute(
        "INSERT INTO cycles (profile_id, start_date) VALUES (?, ?)",
        (profile_id, new_start),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Routes — Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    if not g.profile or not g.cycle:
        return render_template("dashboard.html", insights={}, phase="unknown",
                               cycle_day=0, recent_temps=[], warnings=[],
                               today_temp=None, today_signs=None,
                               ha_reading=None, next_period=None)

    db = g.db
    cid = g.cycle["id"]
    today = date.today().isoformat()

    insight_row = db.execute(
        "SELECT * FROM computed_insights WHERE cycle_id = ?", (cid,)
    ).fetchone()
    insights = dict(insight_row) if insight_row else {}

    cycle_day = get_current_cycle_day(g.cycle["start_date"])

    today_temp = db.execute(
        "SELECT * FROM temperatures WHERE cycle_id = ? AND date = ?",
        (cid, today),
    ).fetchone()
    today_signs = db.execute(
        "SELECT * FROM fertility_signs WHERE cycle_id = ? AND date = ?",
        (cid, today),
    ).fetchone()

    recent_temps = db.execute(
        """
        SELECT date, temp_value, is_discarded FROM temperatures
        WHERE cycle_id = ? ORDER BY date DESC LIMIT 14
        """,
        (cid,),
    ).fetchall()

    ha_reading = None
    if g.profile.get("ha_sensor_entity"):
        ha_reading = ha_client.poll_sensor_reading(g.profile["ha_sensor_entity"])

    next_period = predict_next_period(db, g.profile["id"], cid)

    flow_days = _get_flow_days(db, cid)
    phase = get_cycle_phase(
        current_date=date.today(),
        cycle_start=date.fromisoformat(g.cycle["start_date"]),
        flow_days=flow_days,
        fertile_window={
            "fertile_start": insights.get("fertile_start_date"),
            "fertile_end": insights.get("fertile_end_date"),
        },
        ovulation_date=insights.get("ovulation_date"),
        ovulation_confirmed=bool(insights.get("ovulation_confirmed")),
        post_ov_infertile=insights.get("post_ovulatory_infertile_date"),
    )

    warnings = []
    if insights.get("luteal_phase_short"):
        warnings.append({
            "type": "warning",
            "message": "Short luteal phase detected (< 10 days). Consider consulting a healthcare provider.",
        })
    if insights.get("pregnancy_indicator"):
        warnings.append({
            "type": "info",
            "message": "18+ consecutive elevated temperatures detected — this may indicate pregnancy!",
        })

    avg_cycle = None
    past = db.execute(
        """
        SELECT cycle_length FROM cycles WHERE profile_id = ? AND cycle_length IS NOT NULL
        ORDER BY start_date DESC LIMIT 6
        """,
        (g.profile["id"],),
    ).fetchall()
    if past:
        avg_cycle = round(sum(r["cycle_length"] for r in past) / len(past))

    return render_template(
        "dashboard.html",
        insights=insights,
        phase=phase,
        cycle_day=cycle_day,
        recent_temps=recent_temps,
        today_temp=today_temp,
        today_signs=today_signs,
        ha_reading=ha_reading,
        next_period=next_period,
        warnings=warnings,
        avg_cycle=avg_cycle,
    )


# ---------------------------------------------------------------------------
# Routes — Entry
# ---------------------------------------------------------------------------

@app.route("/entry", methods=["GET", "POST"])
def entry():
    if not g.profile:
        flash("Please create a profile first.", "error")
        return redirect(url_for("profiles"))

    db = g.db
    today = date.today().isoformat()
    entry_date = request.args.get("date", today)

    ha_reading = None
    if g.profile.get("ha_sensor_entity"):
        ha_reading = ha_client.poll_sensor_reading(g.profile["ha_sensor_entity"])

    if request.method == "POST":
        entry_date = request.form.get("date", today)
        temp_str = request.form.get("temp_value", "").strip()
        time_taken = request.form.get("time_taken", "").strip()
        is_discarded = bool(request.form.get("is_discarded"))
        discard_reason = request.form.get("discard_reason", "").strip()
        temp_notes = request.form.get("temp_notes", "").strip()
        menstrual_flow = request.form.get("menstrual_flow", "").strip()
        cervical_mucus = request.form.get("cervical_mucus", "").strip()
        cervical_position = request.form.get("cervical_position", "").strip()
        cervical_firmness = request.form.get("cervical_firmness", "").strip()
        cervical_opening = request.form.get("cervical_opening", "").strip()
        opk_result = request.form.get("opk_result", "").strip()
        signs_notes = request.form.get("signs_notes", "").strip()
        symptom_types = request.form.getlist("symptoms")
        symptom_severity = max(1, min(3, int(request.form.get("symptom_severity", 1))))
        is_period_start = bool(request.form.get("is_period_start"))

        # Validate temperature
        temp_value = None
        errors = []
        if temp_str:
            try:
                temp_value = float(temp_str)
                unit = g.profile["temp_unit"]
                if unit == "F" and not (90.0 <= temp_value <= 105.0):
                    errors.append("Temperature must be between 90 °F and 105 °F")
                elif unit == "C" and not (32.0 <= temp_value <= 41.0):
                    errors.append("Temperature must be between 32 °C and 41 °C")
            except ValueError:
                errors.append("Temperature must be a numeric value")

        if errors:
            for msg in errors:
                flash(msg, "error")
        else:
            if is_period_start:
                _close_and_start_cycle(db, g.profile["id"], entry_date)
                g.cycle = get_or_create_current_cycle(db, g.profile["id"])

            cid = g.cycle["id"]

            if temp_value is not None:
                db.execute(
                    """
                    INSERT INTO temperatures
                        (cycle_id, date, temp_value, time_taken,
                         is_discarded, discard_reason, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cycle_id, date) DO UPDATE SET
                        temp_value     = excluded.temp_value,
                        time_taken     = excluded.time_taken,
                        is_discarded   = excluded.is_discarded,
                        discard_reason = excluded.discard_reason,
                        notes          = excluded.notes
                    """,
                    (cid, entry_date, temp_value, time_taken,
                     1 if is_discarded else 0, discard_reason, temp_notes),
                )

            if any([menstrual_flow, cervical_mucus, cervical_position,
                    cervical_firmness, cervical_opening, opk_result, signs_notes]):
                db.execute(
                    """
                    INSERT INTO fertility_signs
                        (cycle_id, date, menstrual_flow, cervical_mucus,
                         cervical_position, cervical_firmness, cervical_opening,
                         opk_result, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cycle_id, date) DO UPDATE SET
                        menstrual_flow    = excluded.menstrual_flow,
                        cervical_mucus    = excluded.cervical_mucus,
                        cervical_position = excluded.cervical_position,
                        cervical_firmness = excluded.cervical_firmness,
                        cervical_opening  = excluded.cervical_opening,
                        opk_result        = excluded.opk_result,
                        notes             = excluded.notes
                    """,
                    (cid, entry_date, menstrual_flow, cervical_mucus,
                     cervical_position, cervical_firmness, cervical_opening,
                     opk_result, signs_notes),
                )

            if symptom_types:
                db.execute(
                    "DELETE FROM symptoms WHERE cycle_id = ? AND date = ?",
                    (cid, entry_date),
                )
                for stype in symptom_types:
                    db.execute(
                        "INSERT INTO symptoms (cycle_id, date, symptom_type, severity)"
                        " VALUES (?, ?, ?, ?)",
                        (cid, entry_date, stype, symptom_severity),
                    )

            db.commit()
            _trigger_analysis(cid, dict(g.profile))
            flash("Entry saved.", "success")
            return redirect(url_for("dashboard"))

    cid = g.cycle["id"] if g.cycle else None
    ex_temp = ex_signs = None
    ex_symptoms: list[str] = []
    ex_severity = 1
    if cid:
        ex_temp = db.execute(
            "SELECT * FROM temperatures WHERE cycle_id = ? AND date = ?",
            (cid, entry_date),
        ).fetchone()
        ex_signs = db.execute(
            "SELECT * FROM fertility_signs WHERE cycle_id = ? AND date = ?",
            (cid, entry_date),
        ).fetchone()
        rows = db.execute(
            "SELECT symptom_type, severity FROM symptoms"
            " WHERE cycle_id = ? AND date = ?",
            (cid, entry_date),
        ).fetchall()
        ex_symptoms = [r["symptom_type"] for r in rows]
        ex_severity = rows[0]["severity"] if rows else 1

    return render_template(
        "entry.html",
        entry_date=entry_date,
        today=today,
        ha_reading=ha_reading,
        ex_temp=ex_temp,
        ex_signs=ex_signs,
        ex_symptoms=ex_symptoms,
        ex_severity=ex_severity,
    )


# ---------------------------------------------------------------------------
# Routes — History
# ---------------------------------------------------------------------------

@app.route("/history")
def history():
    if not g.profile:
        return redirect(url_for("profiles"))

    cycles = g.db.execute(
        """
        SELECT c.*,
               ci.ovulation_date, ci.luteal_length, ci.ovulation_confirmed,
               ci.fertile_start_date, ci.fertile_end_date,
               ci.coverline
        FROM cycles c
        LEFT JOIN computed_insights ci ON ci.cycle_id = c.id
        WHERE c.profile_id = ?
        ORDER BY c.start_date DESC
        """,
        (g.profile["id"],),
    ).fetchall()

    return render_template("history.html", cycles=cycles)


@app.route("/history/<int:cycle_id>")
def cycle_detail(cycle_id):
    db = g.db
    cycle = db.execute("SELECT * FROM cycles WHERE id = ?", (cycle_id,)).fetchone()
    if not cycle or (g.profile and cycle["profile_id"] != g.profile["id"]):
        flash("Cycle not found.", "error")
        return redirect(url_for("history"))

    insight = db.execute(
        "SELECT * FROM computed_insights WHERE cycle_id = ?", (cycle_id,)
    ).fetchone()

    temps = db.execute(
        """
        SELECT date, temp_value, is_discarded, time_taken, notes,
               CAST(julianday(date) - julianday(?) + 1 AS INTEGER) AS cycle_day
        FROM temperatures WHERE cycle_id = ? ORDER BY date
        """,
        (cycle["start_date"], cycle_id),
    ).fetchall()

    signs = db.execute(
        "SELECT * FROM fertility_signs WHERE cycle_id = ? ORDER BY date",
        (cycle_id,),
    ).fetchall()

    symptoms_by_date: dict[str, list[str]] = {}
    for row in db.execute(
        "SELECT date, symptom_type FROM symptoms WHERE cycle_id = ? ORDER BY date",
        (cycle_id,),
    ).fetchall():
        symptoms_by_date.setdefault(row["date"], []).append(row["symptom_type"])

    return render_template(
        "cycle_detail.html",
        cycle=cycle,
        insight=insight,
        temps=temps,
        signs=signs,
        symptoms_by_date=symptoms_by_date,
    )


# ---------------------------------------------------------------------------
# Routes — API (JSON)
# ---------------------------------------------------------------------------

@app.route("/api/chart-data/<int:cycle_id>")
def api_chart_data(cycle_id):
    db = g.db
    cycle = db.execute("SELECT * FROM cycles WHERE id = ?", (cycle_id,)).fetchone()
    if not cycle:
        return jsonify({"error": "Not found"}), 404

    temps = db.execute(
        """
        SELECT date, temp_value, is_discarded,
               CAST(julianday(date) - julianday(?) + 1 AS INTEGER) AS cycle_day
        FROM temperatures WHERE cycle_id = ? ORDER BY date
        """,
        (cycle["start_date"], cycle_id),
    ).fetchall()

    signs = db.execute(
        "SELECT date, cervical_mucus, opk_result FROM fertility_signs WHERE cycle_id = ?",
        (cycle_id,),
    ).fetchall()
    mucus_map = {s["date"]: s["cervical_mucus"] for s in signs}
    opk_map = {s["date"]: s["opk_result"] for s in signs}

    insight = db.execute(
        "SELECT * FROM computed_insights WHERE cycle_id = ?", (cycle_id,)
    ).fetchone()

    labels = []
    temperatures = []
    discarded = []

    for t in temps:
        label = f"Day {t['cycle_day']}"
        labels.append(label)
        if t["is_discarded"]:
            temperatures.append(None)
            discarded.append({"x": label, "y": t["temp_value"]})
        else:
            temperatures.append(t["temp_value"])

    result: dict = {
        "labels": labels,
        "temperatures": temperatures,
        "discarded": discarded,
        "coverline": None,
        "fertile_start_day": None,
        "fertile_end_day": None,
        "ovulation_day": None,
        "mucus": {},
        "opk": {},
        "unit": g.profile["temp_unit"] if g.profile else "F",
    }

    if insight:
        ins = dict(insight)
        result["coverline"] = ins.get("coverline")
        start = date.fromisoformat(cycle["start_date"])
        for field, key in [
            ("fertile_start_date", "fertile_start_day"),
            ("fertile_end_date", "fertile_end_day"),
            ("ovulation_date", "ovulation_day"),
        ]:
            if ins.get(field):
                result[key] = (date.fromisoformat(ins[field]) - start).days + 1

    for t in temps:
        d = t["date"]
        if d in mucus_map and mucus_map[d]:
            result["mucus"][str(t["cycle_day"])] = mucus_map[d]
        if d in opk_map and opk_map[d]:
            result["opk"][str(t["cycle_day"])] = opk_map[d]

    return jsonify(result)


@app.route("/api/insights")
def api_insights():
    if not g.profile or not g.cycle:
        return jsonify({"error": "No active profile"})
    row = g.db.execute(
        "SELECT * FROM computed_insights WHERE cycle_id = ?", (g.cycle["id"],)
    ).fetchone()
    data = dict(row) if row else {}
    data["cycle_day"] = get_current_cycle_day(g.cycle["start_date"])
    return jsonify(data)


@app.route("/api/entry", methods=["POST"])
def api_entry():
    """JSON endpoint — used by HA automations to push a temperature."""
    data = request.get_json(silent=True)
    if not data or "temp_value" not in data:
        return jsonify({"error": "temp_value required"}), 400
    if not g.profile or not g.cycle:
        return jsonify({"error": "No active profile"}), 400

    try:
        temp_value = float(data["temp_value"])
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid temp_value"}), 400

    entry_date = data.get("date", date.today().isoformat())
    time_taken = data.get("time_taken", datetime.now().strftime("%H:%M"))
    cid = g.cycle["id"]

    g.db.execute(
        """
        INSERT INTO temperatures (cycle_id, date, temp_value, time_taken, notes)
        VALUES (?, ?, ?, ?, 'API import')
        ON CONFLICT(cycle_id, date) DO NOTHING
        """,
        (cid, entry_date, temp_value, time_taken),
    )
    g.db.commit()
    _trigger_analysis(cid, dict(g.profile))
    return jsonify({"status": "ok", "date": entry_date, "temp_value": temp_value})


# ---------------------------------------------------------------------------
# Routes — Profiles
# ---------------------------------------------------------------------------

@app.route("/profiles", methods=["GET", "POST"])
def profiles():
    db = g.db

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "create":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Profile name is required.", "error")
            elif db.execute("SELECT id FROM profiles WHERE name = ?", (name,)).fetchone():
                flash(f'A profile named "{name}" already exists.', "error")
            else:
                slug = slugify(name)
                count = db.execute("SELECT COUNT(*) AS c FROM profiles").fetchone()["c"]
                if db.execute("SELECT id FROM profiles WHERE slug = ?", (slug,)).fetchone():
                    slug = f"{slug}_{count}"
                db.execute(
                    "INSERT INTO profiles (name, slug, temp_unit) VALUES (?, ?, ?)",
                    (name, slug, TEMP_UNIT),
                )
                db.commit()
                flash(f'Profile "{name}" created.', "success")

        elif action == "activate":
            pid = int(request.form.get("profile_id", 0))
            db.execute("UPDATE profiles SET active = 0")
            db.execute("UPDATE profiles SET active = 1 WHERE id = ?", (pid,))
            db.commit()
            session["profile_id"] = pid
            flash("Profile activated.", "success")

        elif action == "delete":
            pid = int(request.form.get("profile_id", 0))
            if db.execute("SELECT COUNT(*) AS c FROM profiles").fetchone()["c"] <= 1:
                flash("Cannot delete the only profile.", "error")
            else:
                db.execute("DELETE FROM profiles WHERE id = ?", (pid,))
                db.commit()
                if session.get("profile_id") == pid:
                    session.pop("profile_id", None)
                flash("Profile deleted.", "success")

        return redirect(url_for("profiles"))

    all_profiles = db.execute(
        "SELECT * FROM profiles ORDER BY created_at ASC"
    ).fetchall()
    return render_template("profiles.html", all_profiles=all_profiles)


# ---------------------------------------------------------------------------
# Routes — Settings
# ---------------------------------------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if not g.profile:
        return redirect(url_for("profiles"))

    db = g.db
    pid = g.profile["id"]

    if request.method == "POST":
        temp_unit = request.form.get("temp_unit", "F")
        ha_sensor = request.form.get("ha_sensor_entity", "").strip()
        interp = request.form.get("interpretation_method", "standard")
        db.execute(
            """
            UPDATE profiles
            SET temp_unit = ?, ha_sensor_entity = ?, interpretation_method = ?
            WHERE id = ?
            """,
            (temp_unit, ha_sensor, interp, pid),
        )
        db.commit()
        g.profile = get_active_profile(db, pid)
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html")


@app.route("/new-cycle", methods=["POST"])
def new_cycle():
    if not g.profile:
        return redirect(url_for("profiles"))
    start_date = request.form.get("start_date", date.today().isoformat())
    _close_and_start_cycle(g.db, g.profile["id"], start_date)
    flash("New cycle started.", "success")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# HA sensor polling callback
# ---------------------------------------------------------------------------

def _poll_ha_sensors():
    """Periodically called by ha_client background timer."""
    db = get_db()
    try:
        profiles = db.execute(
            "SELECT * FROM profiles WHERE ha_sensor_entity != ''"
        ).fetchall()
        for p in profiles:
            entity_id = p["ha_sensor_entity"]
            if not entity_id:
                continue
            temp = ha_client.poll_sensor_reading(entity_id)
            if temp is None:
                continue
            cycle = get_or_create_current_cycle(db, p["id"])
            today = date.today().isoformat()
            existing = db.execute(
                "SELECT id FROM temperatures WHERE cycle_id = ? AND date = ?",
                (cycle["id"], today),
            ).fetchone()
            if not existing:
                db.execute(
                    """
                    INSERT INTO temperatures
                        (cycle_id, date, temp_value, time_taken, notes)
                    VALUES (?, ?, ?, ?, 'Auto-imported from HA sensor')
                    """,
                    (cycle["id"], today, temp,
                     datetime.now().strftime("%H:%M")),
                )
                db.commit()
                logger.info(
                    "Auto-imported %.2f°%s from %s (profile: %s)",
                    temp, p["temp_unit"], entity_id, p["name"],
                )
                _trigger_analysis(cycle["id"], dict(p))
    except Exception as exc:
        logger.error("Sensor poll error: %s", exc, exc_info=True)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()

    # Ensure every existing profile has an open cycle
    db0 = get_db()
    try:
        for p in db0.execute("SELECT * FROM profiles").fetchall():
            get_or_create_current_cycle(db0, p["id"])

        # Initial entity publish for all profiles
        for p in db0.execute("SELECT * FROM profiles").fetchall():
            cycle = get_or_create_current_cycle(db0, p["id"])
            insight_row = db0.execute(
                "SELECT * FROM computed_insights WHERE cycle_id = ?", (cycle["id"],)
            ).fetchone()
            insights = dict(insight_row) if insight_row else {}
            insights["cycle_day"] = get_current_cycle_day(cycle["start_date"])
            ha_client.publish_profile_entities(dict(p), insights)
    except Exception as exc:
        logger.warning("Startup entity publish skipped: %s", exc)
    finally:
        db0.close()

    ha_client.start_polling(POLL_INTERVAL, _poll_ha_sensors)

    port = int(os.environ.get("PORT", 8099))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
