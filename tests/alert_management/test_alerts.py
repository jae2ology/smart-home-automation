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
from app import app, create_alert


# ---------------------------------------------------------------------------
# Seeded Database Constants (from schema.sql & seed.sql)
# ---------------------------------------------------------------------------
# Homes in seed.sql:
#   id=1 -> 'Maple House' (Home A - Enrolled in monitoring_enrollments)
#   id=2 -> 'Coastal Condo' (Home B - NOT enrolled in monitoring_enrollments)
HOME_A_ID = 1
HOME_B_ID = 2

# Devices in seed.sql:
#   id=1 -> 'Front Door Lock' (home_id=1)
#   id=5 -> 'Condo Leak Sensor' (home_id=2)
HOME_A_DEVICE_ID = 1
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
def alert_env(tmp_path, monkeypatch):
    """
    Sets up an isolated SQLite database with `schema.sql` + `seed.sql` and seeds
    the test entities defined in Section 4 (Test Data & Environment Setup):
      - Home A (id=1, Enrolled in Monitoring with emergency contact details)
      - Home B (id=2, Not Enrolled in Monitoring)
      - Owner A (`user_a@example.com` -> ACTIVE owner on Home A only)
      - Owner B (`user_b@example.com` -> ACTIVE owner on Home B only)
      - Operator (`op_1@example.com` -> global role='monitor')
    """
    test_db_path = tmp_path / "test_alerts.db"
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

        # Clear pre-seeded alerts/acknowledgements so tests have a clean slate
        db.execute("DELETE FROM alert_acknowledgements")
        db.execute("DELETE FROM monitoring_events")
        db.execute("DELETE FROM alerts")

        # Ensure Home A is enrolled in monitoring and Home B is NOT enrolled
        db.execute("DELETE FROM monitoring_enrollments WHERE home_id = ?", (HOME_B_ID,))
        existing_enroll = db.execute(
            "SELECT id FROM monitoring_enrollments WHERE home_id = ?", (HOME_A_ID,)
        ).fetchone()
        if not existing_enroll:
            db.execute(
                "INSERT INTO monitoring_enrollments(home_id, status, contact_name, contact_phone) "
                "VALUES (?, 'ACTIVE', 'Jane Doe Emergency', '555-0199')",
                (HOME_A_ID,),
            )

        # Create Owner A (user_a) bound exclusively to Home A
        cur_ua = db.execute(
            "INSERT INTO users(email, name, password, role, active) "
            "VALUES ('user_a@example.com', 'Owner A', 'pass_a', 'owner', 1)"
        )
        setup_ids["user_a_id"] = cur_ua.lastrowid
        db.execute(
            "INSERT INTO memberships(home_id, user_id, home_role, status, created_at) "
            "VALUES (?, ?, 'OWNER', 'ACTIVE', '2026-11-01T00:00:00')",
            (HOME_A_ID, setup_ids["user_a_id"]),
        )

        # Create Owner B (user_b) bound exclusively to Home B
        cur_ub = db.execute(
            "INSERT INTO users(email, name, password, role, active) "
            "VALUES ('user_b@example.com', 'Owner B', 'pass_b', 'owner', 1)"
        )
        setup_ids["user_b_id"] = cur_ub.lastrowid
        db.execute(
            "INSERT INTO memberships(home_id, user_id, home_role, status, created_at) "
            "VALUES (?, ?, 'OWNER', 'ACTIVE', '2026-11-01T00:00:00')",
            (HOME_B_ID, setup_ids["user_b_id"]),
        )

        # Create Monitoring Operator (op_1)
        cur_op = db.execute(
            "INSERT INTO users(email, name, password, role, active) "
            "VALUES ('op_1@example.com', 'Operator One', 'pass_op', 'monitor', 1)"
        )
        setup_ids["op_1_id"] = cur_op.lastrowid

        db.commit()

    with app.test_client() as client:
        yield client, setup_ids


def login_as(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Test Cases (Section 3: Test Cases & Matrix)
# ---------------------------------------------------------------------------

def test_tc_alert_01_alert_generation_and_deduplication_window(alert_env):
    """
    TC-ALERT-01: Alert Generation & Deduplication Window
    Type: Positive / Edge
    Inputs: Device triggers FIRE_ALARM at T=0. Identical alert triggered at T=+30s (Window: 300s).
    Expected: 1st alert created (Status: OPEN). 2nd alert suppressed/deduplicated into 1st record.
    Traceability: FR-30, FR-31
    """
    with app.app_context():
        db = db_module.get_db()

        # T = 0s
        alert_id_1 = create_alert(
            db, HOME_A_ID, HOME_A_DEVICE_ID, "FIRE_ALARM", "CRITICAL", "Smoke detected in kitchen", "evt-fire-1"
        )
        db.commit()

        # T = +30s (within 300s deduplication window)
        MockDateTime.advance(seconds=30)
        alert_id_2 = create_alert(
            db, HOME_A_ID, HOME_A_DEVICE_ID, "FIRE_ALARM", "CRITICAL", "Smoke detected in kitchen", "evt-fire-2"
        )
        db.commit()

        assert alert_id_1 == alert_id_2
        rows = db.execute(
            "SELECT * FROM alerts WHERE home_id = ? AND kind = 'FIRE_ALARM'",
            (HOME_A_ID,),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "OPEN"


def test_tc_alert_02_cross_home_deduplication_isolation(alert_env):
    """
    TC-ALERT-02: Cross-Home Deduplication Isolation
    Type: Security / Positive
    Inputs: DEV-01 in Home A and DEV-02 in Home B trigger identical alert kind simultaneously.
    Expected: Two separate alerts generated. Home A deduplication does not suppress Home B alert.
    Traceability: FR-31, BR-06
    """
    with app.app_context():
        db = db_module.get_db()

        id_home_a = create_alert(
            db, HOME_A_ID, HOME_A_DEVICE_ID, "CRITICAL_BURGLAR", "CRITICAL", "Intrusion Home A", "evt-burg-a"
        )
        id_home_b = create_alert(
            db, HOME_B_ID, HOME_B_DEVICE_ID, "CRITICAL_BURGLAR", "CRITICAL", "Intrusion Home B", "evt-burg-b"
        )
        db.commit()

        assert id_home_a != id_home_b
        count = db.execute("SELECT COUNT(*) c FROM alerts WHERE kind = 'CRITICAL_BURGLAR'").fetchone()["c"]
        assert count == 2


def test_tc_alert_03_alert_acknowledgement_with_audit_note(alert_env):
    """
    TC-ALERT-03: Alert Acknowledgement with Audit Note
    Type: Positive
    Inputs: Authorized Home Owner A acknowledges alert in Home A with note "False alarm, cooking smoke".
    Expected: Alert status changed to ACKNOWLEDGED. Actor ID, timestamp, and note stored permanently.
              Original alert record retained (no hard delete).
    Traceability: FR-32, FR-33
    """
    client, ids = alert_env
    note_text = "False alarm, cooking smoke"

    with app.app_context():
        db = db_module.get_db()
        alert_id = create_alert(
            db, HOME_A_ID, HOME_A_DEVICE_ID, "FIRE_ALARM", "CRITICAL", "Kitchen smoke", "evt-ack-1"
        )
        db.commit()

    login_as(client, "user_a@example.com", "pass_a")
    resp = client.post(
        f"/alerts/{alert_id}/ack",
        data={"note": note_text},
        headers={"Referer": f"/homes/{HOME_A_ID}"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        db = db_module.get_db()
        alert_row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        assert alert_row is not None
        assert alert_row["status"] == "ACKNOWLEDGED"

        ack_row = db.execute(
            "SELECT * FROM alert_acknowledgements WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        assert ack_row is not None
        assert ack_row["user_id"] == ids["user_a_id"]
        assert ack_row["note"] == note_text
        assert ack_row["created_at"] is not None


def test_tc_alert_04_unauthorized_alert_acknowledgement(alert_env):
    """
    TC-ALERT-04: Unauthorized Alert Acknowledgement
    Type: Security
    Inputs: Owner B (member of Home B only) attempts to acknowledge an alert in Home A.
    Expected: HTTP 403 Forbidden. Alert state remains OPEN and no acknowledgement is recorded.
    Traceability: FR-32, BR-01
    """
    client, _ = alert_env

    with app.app_context():
        db = db_module.get_db()
        alert_id = create_alert(
            db, HOME_A_ID, HOME_A_DEVICE_ID, "FIRE_ALARM", "CRITICAL", "Home A Alert", "evt-unauth-ack"
        )
        db.commit()

    login_as(client, "user_b@example.com", "pass_b")
    resp = client.post(
        f"/alerts/{alert_id}/ack",
        data={"note": "Unauthorized cross-home ack"},
        follow_redirects=False,
    )

    assert resp.status_code == 403, (
        f"Authorization Defect (FR-32/BR-01): Owner B from Home B acknowledged Home A alert {alert_id} "
        f"(returned HTTP {resp.status_code} instead of 403 Forbidden; ack() lacks can_access_home check)."
    )


def test_tc_alert_05_unenrolled_home_monitoring_isolation(alert_env):
    """
    TC-ALERT-05: Unenrolled Home Monitoring Isolation
    Type: Security
    Inputs: Monitoring Operator queries `/monitor/alerts` when non-monitored Home B has an active CRITICAL alert.
    Expected: Alert for unenrolled Home B is NOT visible to Monitoring Operator.
    Traceability: FR-34
    """
    client, _ = alert_env

    with app.app_context():
        db = db_module.get_db()
        create_alert(
            db, HOME_B_ID, HOME_B_DEVICE_ID, "WATER_LEAK", "CRITICAL", "Unenrolled Home B Critical Leak", "evt-unenrolled-1"
        )
        db.commit()

    login_as(client, "op_1@example.com", "pass_op")
    resp = client.get("/monitor/alerts")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Unenrolled Home B Critical Leak" not in body, (
        "Monitoring Isolation Defect (FR-34): /monitor/alerts displays alerts from unenrolled Home B "
        "('Coastal Condo') because monitor_alerts() does not filter by active monitoring_enrollments."
    )


def test_tc_alert_06_least_privilege_data_view_for_monitoring_operator(alert_env):
    """
    TC-ALERT-06: Least-Privilege Data View for Monitoring Operator
    Type: Security / Positive
    Inputs: Monitoring Operator views alert for enrolled Home A. Inspect rendered view and device access.
    Expected: Operator sees emergency contact name, address label, and alert type on monitoring view,
              while detailed telemetry/device history endpoints are forbidden (HTTP 403).
    Traceability: FR-35
    """
    client, _ = alert_env

    with app.app_context():
        db = db_module.get_db()
        create_alert(
            db, HOME_A_ID, HOME_A_DEVICE_ID, "FIRE_ALARM", "CRITICAL", "Enrolled Home A Fire", "evt-op-view-1"
        )
        home_a = db.execute("SELECT address_label FROM homes WHERE id = ?", (HOME_A_ID,)).fetchone()
        enroll_a = db.execute(
            "SELECT contact_nameFROM monitoring_enrollments WHERE home_id = ?", (HOME_A_ID,)
        ).fetchone()
        db.commit()

    login_as(client, "op_1@example.com", "pass_op")

    # 1. Check /monitor/alerts includes emergency contact name and address label (FR-35)
    mon_resp = client.get("/monitor/alerts")
    assert mon_resp.status_code == 200
    mon_html = mon_resp.get_data(as_text=True)

    assert "FIRE_ALARM" in mon_html
    assert (home_a["address_label"] in mon_html) and (enroll_a["contact_name"] in mon_html), (
        f"Least-Privilege Payload Defect (FR-35): /monitor/alerts omits home address_label "
        f"({home_a['address_label']!r}) and/or contact_name({enroll_a['contact_name']!r})."
    )

    # 2. Verify detailed device telemetry history is blocked for Monitoring Operator (FR-35)
    dev_resp = client.get(f"/devices/{HOME_A_DEVICE_ID}")
    assert dev_resp.status_code == 403, (
        f"Least-Privilege Access Defect (FR-35): Monitoring Operator accessed detailed device telemetry "
        f"at /devices/{HOME_A_DEVICE_ID} (HTTP {dev_resp.status_code} instead of 403 Forbidden)."
    )
