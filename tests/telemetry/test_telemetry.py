from datetime import datetime, timedelta, timezone
import os
import sys
import pytest

# Add project root (`smart-home-automation/`) to sys.path so `db` and `app` resolve
# regardless of whether pytest is invoked from the root or a subdirectory.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app as app_module
import db as db_module
import domain as domain_module
from app import app


# ---------------------------------------------------------------------------
# Seeded Database Constants (from schema.sql & seed.sql)
# ---------------------------------------------------------------------------
# Homes in seed.sql:
#   id=1 -> 'Maple House' (Home A)
#   id=2 -> 'Coastal Condo' (Home B)
HOME_A_ID = 1
HOME_B_ID = 2

# Devices in seed.sql:
#   id=1 -> 'Front Door Lock' (home_id=1)
#   id=5 -> 'Condo Leak Sensor' (home_id=2)
HOME_A_DEFAULT_DEVICE_ID = 1
HOME_B_DEVICE_ID = 5


class MockDateTime(datetime):
    """Deterministic clock replacement for `app.datetime` and `domain.datetime`."""

    _current_utc: datetime = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def set_utc(cls, dt_utc: datetime):
        assert dt_utc.tzinfo is not None, "Provide a timezone-aware UTC datetime"
        cls._current_utc = dt_utc.astimezone(timezone.utc)

    @classmethod
    def advance(cls, **kwargs):
        cls._current_utc += timedelta(**kwargs)

    @classmethod
    def utcnow(cls):
        return cls._current_utc.replace(tzinfo=None)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._current_utc.replace(tzinfo=None)
        return cls._current_utc.astimezone(tz)


@pytest.fixture
def telemetry_env(tmp_path, monkeypatch):
    """
    Sets up an isolated SQLite database with `schema.sql` + `seed.sql` and seeds
    the test devices & rules defined in Section 4 (Test Data & Environment Setup):
      - DEV-TH1 (Thermostat, Home A)
      - DEV-CS1 (Contact Sensor, Home A)
      - DEV-LT1 (Smart Light, Home A)
      - Rule R1: DEV-CS1 temp > 75 -> DEV-LT1 = ON (Priority 10, Cooldown 60s)
      - Rule R2: DEV-CS1 temp > 75 -> DEV-LT1 = RED (Priority 50, Cooldown 0s)
    """
    test_db_path = tmp_path / "test_telemetry.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(test_db_path))
    monkeypatch.setattr(app, "before_request_funcs", {None: []})
    monkeypatch.setattr(app_module, "datetime", MockDateTime)
    monkeypatch.setattr(domain_module, "datetime", MockDateTime)

    MockDateTime.set_utc(datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc))

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    setup_ids = {}

    with app.app_context():
        db_module.init_db()
        db = db_module.get_db()

        # Clear existing rules so only test-controlled rules evaluate
        db.execute("DELETE FROM rule_runs")
        db.execute("DELETE FROM rule_actions")
        db.execute("DELETE FROM rules")

        # Seed DEV-TH1, DEV-CS1, DEV-LT1 in Home A (id=1)
        cur_th = db.execute(
            "INSERT INTO devices(home_id, name, device_type, capabilities, status, external_id, last_seen_at) "
            "VALUES (?, 'Thermostat TH1', 'THERMOSTAT', 'SET_TEMP', 'ONLINE', 'DEV-TH1', '2026-11-19T11:50:00')",
            (HOME_A_ID,),
        )
        setup_ids["dev_th1_id"] = cur_th.lastrowid

        cur_cs = db.execute(
            "INSERT INTO devices(home_id, name, device_type, capabilities, status, external_id, last_seen_at) "
            "VALUES (?, 'Contact Sensor CS1', 'SENSOR', '', 'ONLINE', 'DEV-CS1', '2026-11-19T11:50:00')",
            (HOME_A_ID,),
        )
        setup_ids["dev_cs1_id"] = cur_cs.lastrowid

        cur_lt = db.execute(
            "INSERT INTO devices(home_id, name, device_type, capabilities, status, external_id, last_seen_at) "
            "VALUES (?, 'Smart Light LT1', 'LIGHT', 'ON,OFF,RED', 'ONLINE', 'DEV-LT1', '2026-11-19T11:50:00')",
            (HOME_A_ID,),
        )
        setup_ids["dev_lt1_id"] = cur_lt.lastrowid

        # Seed device-bound tokens for DEV-TH1, DEV-CS1, and Home B's DEV-02 (id=5)
        setup_ids["tok_th1"] = "tok-dev-th1-secret"
        setup_ids["tok_cs1"] = "tok-dev-cs1-secret"
        setup_ids["tok_home_b"] = "tok-dev-home-b-secret"

        db.execute(
            "INSERT INTO device_tokens(device_id, token, created_at, revoked_at) VALUES (?, ?, '2026-11-19T00:00:00', NULL)",
            (setup_ids["dev_th1_id"], setup_ids["tok_th1"]),
        )
        db.execute(
            "INSERT INTO device_tokens(device_id, token, created_at, revoked_at) VALUES (?, ?, '2026-11-19T00:00:00', NULL)",
            (setup_ids["dev_cs1_id"], setup_ids["tok_cs1"]),
        )
        db.execute(
            "INSERT INTO device_tokens(device_id, token, created_at, revoked_at) VALUES (?, ?, '2026-11-19T00:00:00', NULL)",
            (HOME_B_DEVICE_ID, setup_ids["tok_home_b"]),
        )

        # Seed Rule R1: Trigger DEV-CS1 temp > 75 -> Action DEV-LT1 = ON (Priority 10, Cooldown 60s)
        cur_r1 = db.execute(
            "INSERT INTO rules(home_id, name, trigger_device_id, trigger_metric, trigger_operator, trigger_value, cooldown_sec, priority, enabled) "
            "VALUES (?, 'Rule R1 Low Priority', ?, 'temp', '>', '75', 60, 10, 1)",
            (HOME_A_ID, setup_ids["dev_cs1_id"]),
        )
        setup_ids["rule_r1_id"] = cur_r1.lastrowid
        db.execute(
            "INSERT INTO rule_actions(rule_id, device_id, command, payload, sequence_no) VALUES (?, ?, ?, ?, ?)",
            (setup_ids["rule_r1_id"], setup_ids["dev_lt1_id"], "ON", '{"state":"ON"}', 1),
        )

        # Seed Rule R2: Trigger DEV-CS1 temp > 75 -> Action DEV-LT1 = RED (Priority 50, Cooldown 0s)
        cur_r2 = db.execute(
            "INSERT INTO rules(home_id, name, trigger_device_id, trigger_metric, trigger_operator, trigger_value, cooldown_sec, priority, enabled) "
            "VALUES (?, 'Rule R2 High Priority', ?, 'temp', '>', '75', 0, 50, 1)",
            (HOME_A_ID, setup_ids["dev_cs1_id"]),
        )
        setup_ids["rule_r2_id"] = cur_r2.lastrowid
        db.execute(
            "INSERT INTO rule_actions(rule_id, device_id, command, payload, sequence_no) VALUES (?, ?, ?, ?, ?)",
            (setup_ids["rule_r2_id"], setup_ids["dev_lt1_id"], "RED", '{"color":"RED"}', 1),
        )

        db.commit()

    with app.test_client() as client:
        yield client, setup_ids


# ---------------------------------------------------------------------------
# Test Cases (Section 3: Test Cases & Matrix)
# ---------------------------------------------------------------------------

def test_tc_telem_01_valid_telemetry_ingestion_and_health_update(telemetry_env):
    """
    TC-TELEM-01: Valid Telemetry Ingestion & Health Update
    Type: Positive
    Inputs: DEV-TH1 posts telemetry {source_event_id: "E-100", metric: "temp", value: 78.5}.
    Expected: HTTP 201/202 Accepted. Telemetry logged, device last_seen_at updated.
    Traceability: FR-08, FR-09, FR-13
    """
    client, ids = telemetry_env
    reported_ts = "2026-11-19T12:00:00"

    resp = client.post(
        "/api/device/telemetry",
        json={
            "device_id": ids["dev_th1_id"],
            "source_event_id": "E-100",
            "metric": "temp",
            "value": 78.5,
            "reported_at": reported_ts,
        },
        headers={"X-Device-Token": ids["tok_th1"]},
    )

    assert resp.status_code in (201, 202)

    with app.app_context():
        db = db_module.get_db()
        telem = db.execute(
            "SELECT * FROM telemetry WHERE device_id = ? AND source_event_id = 'E-100'",
            (ids["dev_th1_id"],),
        ).fetchone()
        assert telem is not None
        assert telem["value"] == 78.5

        dev = db.execute("SELECT last_seen_at, status FROM devices WHERE id = ?", (ids["dev_th1_id"],)).fetchone()
        assert dev["last_seen_at"] == reported_ts
        assert dev["status"] == "ONLINE"


def test_tc_telem_02_exact_telemetry_replay_deduplication(telemetry_env):
    """
    TC-TELEM-02: Exact Telemetry Replay Attack / Duplication
    Type: Edge / Negative
    Inputs: Re-post identical {device_id: DEV-CS1, source_event_id: "E-100"} 5 seconds later.
    Expected: Duplicate ignored (HTTP 200/202, no new telemetry row inserted, no re-triggering of rules).
    Traceability: FR-10, FR-11, FR-26, BR-03
    """
    client, ids = telemetry_env
    payload = {
        "device_id": ids["dev_cs1_id"],
        "source_event_id": "E-100",
        "metric": "temp",
        "value": 80.0,
        "reported_at": "2026-11-19T12:00:00",
    }

    first_resp = client.post("/api/device/telemetry", json=payload, headers={"X-Device-Token": ids["tok_cs1"]})
    assert first_resp.status_code in (200, 201, 202)

    with app.app_context():
        db = db_module.get_db()
        runs_after_first = db.execute("SELECT COUNT(*) c FROM rule_runs").fetchone()["c"]
        assert runs_after_first >= 1

    # Advance 5 seconds and replay exact same event
    MockDateTime.advance(seconds=5)
    replay_resp = client.post("/api/device/telemetry", json=payload, headers={"X-Device-Token": ids["tok_cs1"]})
    assert replay_resp.status_code in (200, 202)

    with app.app_context():
        db = db_module.get_db()
        telem_count = db.execute(
            "SELECT COUNT(*) c FROM telemetry WHERE device_id = ? AND source_event_id = 'E-100'",
            (ids["dev_cs1_id"],),
        ).fetchone()["c"]
        assert telem_count == 1

        runs_after_replay = db.execute("SELECT COUNT(*) c FROM rule_runs").fetchone()["c"]
        assert runs_after_replay == runs_after_first


def test_tc_telem_03_identical_source_id_across_different_devices(telemetry_env):
    """
    TC-TELEM-03: Identical Source ID Across Different Devices
    Type: Edge / Positive
    Inputs: DEV-TH1 posts source_event_id="E-200"; DEV-CS1 also posts source_event_id="E-200".
    Expected: Both events accepted and stored independently without cross-device collision (BR-03).
    Traceability: FR-10, BR-03
    """
    client, ids = telemetry_env

    resp_1 = client.post(
        "/api/device/telemetry",
        json={
            "device_id": ids["dev_th1_id"],
            "source_event_id": "E-200",
            "metric": "temp",
            "value": 71.0,
            "reported_at": "2026-11-19T12:00:00",
        },
        headers={"X-Device-Token": ids["tok_th1"]},
    )
    assert resp_1.status_code in (201, 202)

    resp_2 = client.post(
        "/api/device/telemetry",
        json={
            "device_id": ids["dev_cs1_id"],
            "source_event_id": "E-200",
            "metric": "temp",
            "value": 72.0,
            "reported_at": "2026-11-19T12:00:01",
        },
        headers={"X-Device-Token": ids["tok_cs1"]},
    )
    assert resp_2.status_code in (201, 202), (
        f"Replay Key Defect (FR-10/BR-03): DEV-CS1 event 'E-200' collided with DEV-TH1 event 'E-200' "
        f"(response={resp_2.get_json()}; app.py checks source_event_id globally instead of per device_id)."
    )

    with app.app_context():
        db = db_module.get_db()
        rows = db.execute("SELECT * FROM telemetry WHERE source_event_id = 'E-200'").fetchall()
        assert len(rows) == 2


def test_tc_telem_04_stale_out_of_tolerance_clock_skew_event(telemetry_env):
    """
    TC-TELEM-04: Stale / Out-of-Tolerance Clock Skew Event
    Type: Boundary
    Inputs: Post telemetry with reported_at 15 minutes in the past (exceeding 5-minute tolerance)
            when device last_seen_at is already newer (11:50:00 -> 12:00:00 vs stale 11:45:00).
    Expected: Handled explicitly (rejected or marked STALE); does NOT overwrite newer device last_seen_at.
    Traceability: FR-12
    """
    client, ids = telemetry_env
    # Server clock is 12:00:00; device last_seen_at is 11:50:00; reported_at is 11:45:00 (15m stale)
    stale_ts = "2026-11-19T11:45:00"

    resp = client.post(
        "/api/device/telemetry",
        json={
            "device_id": ids["dev_th1_id"],
            "source_event_id": "E-STALE-1",
            "metric": "temp",
            "value": 65.0,
            "reported_at": stale_ts,
        },
        headers={"X-Device-Token": ids["tok_th1"]},
    )

    with app.app_context():
        db = db_module.get_db()
        dev = db.execute("SELECT last_seen_at FROM devices WHERE id = ?", (ids["dev_th1_id"],)).fetchone()
        assert dev["last_seen_at"] != stale_ts, (
            f"Clock Skew / Staleness Defect (FR-12): Stale telemetry (reported_at={stale_ts}, 15m old) "
            f"overwrote newer device last_seen_at ('2026-11-19T11:50:00') with HTTP {resp.status_code}."
        )


def test_tc_telem_05_cross_tenant_token_telemetry_spoofing(telemetry_env):
    """
    TC-TELEM-05: Cross-Tenant Token Telemetry Spoofing
    Type: Security
    Inputs: Token bound to DEV-TH1 (Home A) is used to post telemetry claiming device_id = DEV-02 (Home B).
    Expected: HTTP 401 Unauthorized or 403 Forbidden (token must be bound to its own device).
    Traceability: FR-08, BR-01
    """
    client, ids = telemetry_env

    resp = client.post(
        "/api/device/telemetry",
        json={
            "device_id": HOME_B_DEVICE_ID,
            "source_event_id": "E-SPOOF-1",
            "metric": "leak",
            "value": 1,
            "reported_at": "2026-11-19T12:00:00",
        },
        headers={"X-Device-Token": ids["tok_th1"]},
    )

    assert resp.status_code in (401, 403), (
        f"Device Token Binding Defect (FR-08/BR-01): Token for Home A device {ids['dev_th1_id']} "
        f"successfully posted telemetry for Home B device {HOME_B_DEVICE_ID} (HTTP {resp.status_code})."
    )


def test_tc_telem_06_rule_priority_execution_ordering(telemetry_env):
    """
    TC-TELEM-06: Rule Priority Execution Ordering
    Type: Functional
    Inputs: Event DEV-CS1 temp = 80 triggers Rule R1 (Priority 10) and Rule R2 (Priority 50).
    Expected: Higher-priority Rule R2 (50) executes before lower-priority Rule R1 (10) in rule_runs.
    Traceability: FR-22, BR-04
    """
    client, ids = telemetry_env

    resp = client.post(
        "/api/device/telemetry",
        json={
            "device_id": ids["dev_cs1_id"],
            "source_event_id": "E-PRIO-1",
            "metric": "temp",
            "value": 80.0,
            "reported_at": "2026-11-19T12:00:00",
        },
        headers={"X-Device-Token": ids["tok_cs1"]},
    )
    assert resp.status_code in (201, 202)

    with app.app_context():
        db = db_module.get_db()
        runs = db.execute(
            "SELECT rule_id FROM rule_runs WHERE trigger_event_id = 'E-PRIO-1' ORDER BY id ASC"
        ).fetchall()
        executed_rule_order = [r["rule_id"] for r in runs]
        assert executed_rule_order == [ids["rule_r2_id"], ids["rule_r1_id"]], (
            f"Rule Priority Defect (FR-22/BR-04): Expected high-priority Rule R2 ({ids['rule_r2_id']}, prio=50) "
            f"to execute before Rule R1 ({ids['rule_r1_id']}, prio=10), but order was {executed_rule_order} "
            f"(app.py sorts ORDER BY priority ASC instead of DESC)."
        )


def test_tc_telem_07_rule_conflict_resolution(telemetry_env):
    """
    TC-TELEM-07: Rule Conflict Resolution
    Type: Boundary
    Inputs: Rule A (Priority 10) commands Light = OFF; Rule B (Priority 50) commands Light = ON
            on the same trigger event.
    Expected: Conflict policy resolves conflicting commands on DEV-LT1 so only the winning
              high-priority command ('ON') is dispatched (not both conflicting commands).
    Traceability: FR-23
    """
    client, ids = telemetry_env

    with app.app_context():
        db = db_module.get_db()
        db.execute("UPDATE rule_actions SET command = 'OFF' WHERE rule_id = ?", (ids["rule_r1_id"],))
        db.execute("UPDATE rule_actions SET command = 'ON' WHERE rule_id = ?", (ids["rule_r2_id"],))
        db.commit()

    resp = client.post(
        "/api/device/telemetry",
        json={
            "device_id": ids["dev_cs1_id"],
            "source_event_id": "E-CONFLICT-1",
            "metric": "temp",
            "value": 82.0,
            "reported_at": "2026-11-19T12:00:00",
        },
        headers={"X-Device-Token": ids["tok_cs1"]},
    )
    assert resp.status_code in (201, 202)

    with app.app_context():
        db = db_module.get_db()
        cmds = db.execute(
            "SELECT command FROM device_commands WHERE device_id = ? ORDER BY id ASC",
            (ids["dev_lt1_id"],),
        ).fetchall()
        cmd_list = [c["command"] for c in cmds]
        assert cmd_list == ["ON"], (
            f"Conflict Resolution Defect (FR-23): Conflicting commands {cmd_list} were both sent to "
            f"DEV-LT1 instead of resolving to single winning command ['ON']."
        )


def test_tc_telem_08_per_rule_cooldown_enforcement(telemetry_env):
    """
    TC-TELEM-08: Per-Rule Cooldown Enforcement
    Type: Functional
    Inputs:
      - T=0s: DEV-CS1 temp = 80 triggers R1 (Cooldown: 60s) and R2 (Cooldown: 0s).
      - T=30s: DEV-CS1 temp = 81 re-triggers evaluation.
    Expected: At T=30s, R1 is skipped due to active 60s cooldown, while R2 (0s cooldown) still runs.
    Traceability: FR-24, BR-05
    """
    client, ids = telemetry_env

    # T = 0s
    resp_t0 = client.post(
        "/api/device/telemetry",
        json={
            "device_id": ids["dev_cs1_id"],
            "source_event_id": "E-COOL-0",
            "metric": "temp",
            "value": 80.0,
            "reported_at": "2026-11-19T12:00:00",
        },
        headers={"X-Device-Token": ids["tok_cs1"]},
    )
    assert resp_t0.status_code in (201, 202)

    # T = +30s (inside R1's 60s cooldown, outside R2's 0s cooldown)
    MockDateTime.advance(seconds=30)
    resp_t30 = client.post(
        "/api/device/telemetry",
        json={
            "device_id": ids["dev_cs1_id"],
            "source_event_id": "E-COOL-30",
            "metric": "temp",
            "value": 81.0,
            "reported_at": "2026-11-19T12:00:30",
        },
        headers={"X-Device-Token": ids["tok_cs1"]},
    )
    assert resp_t30.status_code in (201, 202)

    with app.app_context():
        db = db_module.get_db()
        t30_runs = [
            r["rule_id"]
            for r in db.execute("SELECT rule_id FROM rule_runs WHERE trigger_event_id = 'E-COOL-30'").fetchall()
        ]
        assert ids["rule_r1_id"] not in t30_runs
        assert ids["rule_r2_id"] in t30_runs


def test_tc_telem_09_execution_logging_and_audit(telemetry_env):
    """
    TC-TELEM-09: Execution Logging & Audit
    Type: Functional
    Inputs: Rule triggers and completes successfully.
    Expected: `rule_runs` records `trigger_event_id`, `started_at`, `completed_at`, `status='SUCCESS'`,
              and action payload details are persisted.
    Traceability: FR-25
    """
    client, ids = telemetry_env

    resp = client.post(
        "/api/device/telemetry",
        json={
            "device_id": ids["dev_cs1_id"],
            "source_event_id": "E-LOG-1",
            "metric": "temp",
            "value": 79.0,
            "reported_at": "2026-11-19T12:00:00",
        },
        headers={"X-Device-Token": ids["tok_cs1"]},
    )
    assert resp.status_code in (201, 202)

    with app.app_context():
        db = db_module.get_db()
        run = db.execute(
            "SELECT * FROM rule_runs WHERE trigger_event_id = 'E-LOG-1' AND rule_id = ?",
            (ids["rule_r2_id"],),
        ).fetchone()
        assert run is not None
        assert run["trigger_event_id"] == "E-LOG-1"
        assert run["started_at"] is not None
        assert run["completed_at"] is not None
        assert run["status"] == "SUCCESS"
        assert "RED" in (run["details"] or ""), (
            f"Execution Audit Defect (FR-25): rule_runs.details does not log action payload details "
            f"(details={run['details']!r})."
        )