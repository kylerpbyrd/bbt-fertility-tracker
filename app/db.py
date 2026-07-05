"""
Database module — SQLite-backed persistent storage at /data/bbt.db.
All tables use STRICT typing where available and WAL journal mode for
safe concurrent reads from the background polling thread.
"""
import os
import re
import sqlite3
import logging
from datetime import date

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.environ.get("DATA_PATH", "/data"), "bbt.db")

_SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS profiles (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT    NOT NULL UNIQUE,
    slug                 TEXT    NOT NULL UNIQUE,
    temp_unit            TEXT    NOT NULL DEFAULT 'F',
    interpretation_method TEXT   NOT NULL DEFAULT 'standard',
    ha_sensor_entity     TEXT    NOT NULL DEFAULT '',
    active               INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cycles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id   INTEGER NOT NULL,
    start_date   TEXT    NOT NULL,
    end_date     TEXT,
    cycle_length INTEGER,
    notes        TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS temperatures (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id       INTEGER NOT NULL,
    date           TEXT    NOT NULL,
    temp_value     REAL    NOT NULL,
    time_taken     TEXT    NOT NULL DEFAULT '',
    is_discarded   INTEGER NOT NULL DEFAULT 0,
    discard_reason TEXT    NOT NULL DEFAULT '',
    notes          TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (cycle_id) REFERENCES cycles(id) ON DELETE CASCADE,
    UNIQUE(cycle_id, date)
);

CREATE TABLE IF NOT EXISTS fertility_signs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id           INTEGER NOT NULL,
    date               TEXT    NOT NULL,
    menstrual_flow     TEXT    NOT NULL DEFAULT '',
    cervical_mucus     TEXT    NOT NULL DEFAULT '',
    cervical_position  TEXT    NOT NULL DEFAULT '',
    cervical_firmness  TEXT    NOT NULL DEFAULT '',
    cervical_opening   TEXT    NOT NULL DEFAULT '',
    opk_result         TEXT    NOT NULL DEFAULT '',
    notes              TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (cycle_id) REFERENCES cycles(id) ON DELETE CASCADE,
    UNIQUE(cycle_id, date)
);

CREATE TABLE IF NOT EXISTS symptoms (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id     INTEGER NOT NULL,
    date         TEXT    NOT NULL,
    symptom_type TEXT    NOT NULL,
    severity     INTEGER NOT NULL DEFAULT 1,
    notes        TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (cycle_id) REFERENCES cycles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS computed_insights (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id                    INTEGER NOT NULL UNIQUE,
    coverline                   REAL,
    ovulation_date              TEXT,
    ovulation_confirmed         INTEGER NOT NULL DEFAULT 0,
    ovulation_method            TEXT    NOT NULL DEFAULT '',
    fertile_start_date          TEXT,
    fertile_end_date            TEXT,
    post_ovulatory_infertile_date TEXT,
    luteal_length               INTEGER,
    luteal_phase_short          INTEGER NOT NULL DEFAULT 0,
    pregnancy_indicator         INTEGER NOT NULL DEFAULT 0,
    consecutive_elevated_temps  INTEGER NOT NULL DEFAULT 0,
    computed_at                 TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (cycle_id) REFERENCES cycles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    profile_id INTEGER NOT NULL,
    key        TEXT    NOT NULL,
    value      TEXT    NOT NULL,
    PRIMARY KEY (profile_id, key),
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);
"""


def get_db() -> sqlite3.Connection:
    """Return a new database connection with row_factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    """Create all tables if they do not already exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
        logger.info("Database ready at %s", DB_PATH)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Convert a profile name to a URL/entity-safe slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_") or "profile"


def get_active_profile(db: sqlite3.Connection, session_profile_id=None) -> dict | None:
    """
    Return the active profile as a plain dict.
    Priority: session override → DB active flag → first profile.
    """
    if session_profile_id:
        row = db.execute(
            "SELECT * FROM profiles WHERE id = ?", (session_profile_id,)
        ).fetchone()
        if row:
            return dict(row)

    row = db.execute(
        "SELECT * FROM profiles WHERE active = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if row:
        return dict(row)

    row = db.execute("SELECT * FROM profiles ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Cycle helpers
# ---------------------------------------------------------------------------

def get_or_create_current_cycle(db: sqlite3.Connection, profile_id: int,
                                start_date: str | None = None) -> dict:
    """
    Return the most recent open cycle for a profile.
    Creates a new cycle starting today if none exists.
    """
    row = db.execute(
        """
        SELECT * FROM cycles
        WHERE profile_id = ? AND end_date IS NULL
        ORDER BY start_date DESC LIMIT 1
        """,
        (profile_id,),
    ).fetchone()

    if row:
        return dict(row)

    today = start_date or date.today().isoformat()
    cur = db.execute(
        "INSERT INTO cycles (profile_id, start_date) VALUES (?, ?)",
        (profile_id, today),
    )
    db.commit()
    return dict(
        db.execute("SELECT * FROM cycles WHERE id = ?", (cur.lastrowid,)).fetchone()
    )
