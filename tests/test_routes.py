import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Load the application with an isolated SQLite database for each test."""
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    monkeypatch.setenv("BBT_TEMP_UNIT", "F")
    sys.path.insert(0, str(APP_DIR))

    for module_name in ("bbt_tracker_app", "db", "ha_client"):
        sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location(
        "bbt_tracker_app", APP_DIR / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.init_db()
    module.app.config.update(TESTING=True)
    monkeypatch.setattr(module, "_trigger_analysis", lambda *_args: None)

    with module.app.test_client() as test_client:
        yield test_client

    sys.path.remove(str(APP_DIR))


def test_dashboard_creates_a_default_profile_and_loads(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"BBT Fertility Tracker" in response.data


def test_api_entry_requires_a_temperature_value(client):
    response = client.post("/api/entry", json={})

    assert response.status_code == 400
    assert response.get_json()["error"] == "temp_value required"


def test_api_entry_rejects_a_non_numeric_temperature(client):
    response = client.get("/")
    assert response.status_code == 200

    response = client.post("/api/entry", json={"temp_value": "not-a-temperature"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Invalid temp_value"
