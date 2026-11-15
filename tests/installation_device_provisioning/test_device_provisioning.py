import logging
import os
import sys
import pytest

# Add project root (`smart-home-automation/`) to sys.path so `db` and `app` resolve
# regardless of whether pytest is invoked from the root or a subdirectory.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import db as db_module
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
#   id=1 -> 'Front Door Lock' (home_id=1, external_id='dev-lock-1')
SEEDED_HOME_A_LOCK_ID = 1

# Users in seed.sql:
#   id=1 -> 'owner@example.com' ('Morgan Owner', role='owner')
#   id=3 -> 'installer@example.com' ('Ian Installer', role='installer')
OWNER_USER_ID = 1
INSTALLER_USER_ID = 3


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    Redirects `db.DB_PATH` to a fresh temporary SQLite file and runs `db.init_db()`
    (which loads `schema.sql` and `seed.sql`) so every test starts with a clean,
    seeded database without touching `app.db`.
    """
    test_db_path = tmp_path / "test_app.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(test_db_path))
    monkeypatch.setattr(app, "before_request_funcs", {None: []})

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db_module.init_db()
        # Grant installer temporary ACTIVE membership on Home A (id=1) for provisioning
        db = db_module.get_db()
        db.execute(
            "INSERT INTO memberships(home_id, user_id, home_role, status, created_at) "
            "VALUES (?, ?, 'INSTALLER', 'ACTIVE', '2026-11-15T10:00')",
            (HOME_A_ID, INSTALLER_USER_ID),
        )
        db.commit()

    with app.test_client() as test_client:
        yield test_client


def login_as(test_client, email, password):
    """Authenticates via `POST /login` using real seeded credentials."""
    return test_client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Test Cases (Section 3: Test Cases & Matrix)
# ---------------------------------------------------------------------------

def test_tc_inst_01_provision_new_device_as_installer(client):
    """
    TC-INST-01: Provision New Device as Installer
    Type: Positive
    Inputs: Installer assigned to Home A provisions a Smart Lock (Type: LOCK, ExtID: LOCK-101).
    Expected: Device registered under Home A, initial status PROVISIONED, token generated securely.
    Traceability: FR-04, FR-05, FR-07
    """
    login_as(client, "installer@example.com", "install")

    payload = {
        "device_type": "LOCK",
        "external_id": "LOCK-101",
        "name": "Patio Smart Lock",
    }

    response = client.post(f"/api/homes/{HOME_A_ID}/devices", json=payload)

    assert response.status_code in (200, 201)
    body = response.get_json()
    assert body["home_id"] == HOME_A_ID
    assert body["external_id"] == "LOCK-101"
    assert body["status"] == "PROVISIONED"

    token = body.get("device_token") or body.get("token")
    assert token and len(token) >= 16

    with app.app_context():
        db = db_module.get_db()
        row = db.execute(
            "SELECT * FROM devices WHERE home_id = ? AND external_id = ?",
            (HOME_A_ID, "LOCK-101"),
        ).fetchone()
        assert row is not None
        assert row["status"] == "PROVISIONED"


@pytest.mark.parametrize(
    "actual_route",
    [
        f"/api/homes/{HOME_A_ID}/status",        # Exposes devices + open alerts JSON for Home A
        f"/devices/{SEEDED_HOME_A_LOCK_ID}",     # Exposes last 100 telemetry records for device 1
        "/monitor/alerts",                       # Exposes unresolved alerts across all homes
    ],
)
def test_tc_inst_02_telemetry_access_denial_for_installer(client, actual_route):
    """
    TC-INST-02: Telemetry & Alerts Access Denial for Installer
    Type: Security / Negative
    Inputs: Installer attempts to read household telemetry and alerts via the actual
            routes exposed in `app.py` (`/api/homes/<hid>/status`, `/devices/<did>`,
            and `/monitor/alerts`).
    Expected: HTTP 403 Forbidden. Access explicitly denied.
    Traceability: FR-04, BR-02, NFR-03
    """
    login_as(client, "installer@example.com", "install")

    response = client.get(actual_route)

    assert response.status_code == 403, (
        f"Security Defect (FR-04/BR-02/NFR-03): Installer accessed {actual_route} "
        f"and received HTTP {response.status_code} instead of 403 Forbidden."
    )


def test_tc_inst_03_global_duplicate_external_id_rejection(client):
    """
    TC-INST-03: Global Duplicate External ID Rejection
    Type: Negative
    Inputs: Register device with ExtID: LOCK-101 in Home B when LOCK-101 exists in Home A.
    Expected: HTTP 409 Conflict / Error DUPLICATE_EXTERNAL_ID. Device creation rejected.
    Traceability: FR-06, BR-01
    """
    # Seed LOCK-101 in Home A (id=1)
    with app.app_context():
        db = db_module.get_db()
        db.execute(
            "INSERT INTO devices(home_id, name, device_type, capabilities, status, external_id) "
            "VALUES (?, 'Front Lock 101', 'LOCK', 'LOCK,UNLOCK', 'PROVISIONED', 'LOCK-101')",
            (HOME_A_ID,),
        )
        db.commit()

    login_as(client, "owner@example.com", "student")

    payload = {
        "device_type": "LOCK",
        "external_id": "LOCK-101",
        "name": "Condo Duplicate Lock",
    }

    response = client.post(f"/api/homes/{HOME_B_ID}/devices", json=payload)

    assert response.status_code == 409
    body = response.get_json()
    assert body.get("error") == "DUPLICATE_EXTERNAL_ID"


def test_tc_inst_04_revoke_device_token(client):
    """
    TC-INST-04: Revoke Device Token
    Type: Functional
    Inputs: Home Owner triggers credential revocation for LOCK-101.
    Expected: Old device token invalid (401 Unauthorized). Device status set to UNPAIRED or REVOKED.
    Traceability: FR-07
    """
    # Seed LOCK-101 and its active device_tokens entry
    with app.app_context():
        db = db_module.get_db()
        cur = db.execute(
            "INSERT INTO devices(home_id, name, device_type, capabilities, status, external_id) "
            "VALUES (?, 'Smart Lock 101', 'LOCK', 'LOCK,UNLOCK', 'PROVISIONED', 'LOCK-101')",
            (HOME_A_ID,),
        )
        device_id = cur.lastrowid
        old_token = "token-lock-101-secret"
        db.execute(
            "INSERT INTO device_tokens(device_id, token, created_at, revoked_at) "
            "VALUES (?, ?, '2026-11-15T10:00', NULL)",
            (device_id, old_token),
        )
        db.commit()

    # Home Owner triggers credential revocation
    login_as(client, "owner@example.com", "student")
    revoke_resp = client.post(f"/api/homes/{HOME_A_ID}/devices/{device_id}/revoke")
    assert revoke_resp.status_code in (200, 204)

    # Verify device status is UNPAIRED or REVOKED in devices table
    with app.app_context():
        db = db_module.get_db()
        dev = db.execute("SELECT status FROM devices WHERE id = ?", (device_id,)).fetchone()
        assert dev["status"] in ("UNPAIRED", "REVOKED")

    # Verify old device token is rejected with 401 Unauthorized on POST /api/device/telemetry
    telemetry_resp = client.post(
        "/api/device/telemetry",
        json={
            "device_id": device_id,
            "source_event_id": "evt-revoked-token-1",
            "metric": "battery",
            "value": 90,
            "reported_at": "2026-11-15T15:30:00",
        },
        headers={"X-Device-Token": old_token},
    )
    assert telemetry_resp.status_code == 401


def test_tc_inst_05_installer_access_boundary_post_provisioning(client):
    """
    TC-INST-05: Installer Access Boundary Post-Provisioning
    Type: Security
    Inputs: Installer attempts to issue a manual command (`POST /devices/<did>/command`)
            after their provisioning window/membership on Home A is EXPIRED.
    Expected: HTTP 403 Forbidden. Temporary scope expired and no command recorded.
    Traceability: FR-04, BR-02
    """
    with app.app_context():
        db = db_module.get_db()
        # Expire installer's membership/provisioning window on Home A
        db.execute(
            "UPDATE memberships SET status = 'EXPIRED' WHERE home_id = ? AND user_id = ?",
            (HOME_A_ID, INSTALLER_USER_ID),
        )
        db.commit()

    login_as(client, "installer@example.com", "install")

    # Actual route in `app.py` is `POST /devices/<int:did>/command` (form data)
    response = client.post(
        f"/devices/{SEEDED_HOME_A_LOCK_ID}/command",
        data={"command": "UNLOCK", "payload": "{}"},
    )

    assert response.status_code == 403, (
        f"Security Defect (FR-04/BR-02): Installer with EXPIRED membership executed "
        f"POST /devices/{SEEDED_HOME_A_LOCK_ID}/command and received HTTP {response.status_code} instead of 403."
    )


def test_tc_inst_06_secret_token_exposure_in_logs_and_api(client, caplog):
    """
    TC-INST-06: Secret Token Exposure in Logs / API
    Type: Security
    Inputs: Provision device; inspect HTTP response, server logs, and audit trails.
    Expected: Device credential displayed once upon creation; raw token absent in standard logs/APIs.
    Traceability: FR-37, NFR-13
    """
    caplog.set_level(logging.DEBUG)
    login_as(client, "installer@example.com", "install")

    create_resp = client.post(
        f"/api/homes/{HOME_A_ID}/devices",
        json={
            "device_type": "THERMOSTAT",
            "external_id": "THERM-101",
            "name": "Upstairs Thermostat",
        },
    )
    assert create_resp.status_code in (200, 201)
    create_body = create_resp.get_json()
    raw_token = create_body.get("device_token") or create_body.get("token")
    assert raw_token, "Device credential must be returned once upon creation"

    # Switch to Home Owner to inspect subsequent APIs and audit trails
    login_as(client, "owner@example.com", "student")

    devices_resp = client.get(f"/api/homes/{HOME_A_ID}/devices")
    if devices_resp.status_code == 200:
        assert raw_token not in devices_resp.get_data(as_text=True)

    with app.app_context():
        db = db_module.get_db()
        audit_rows = db.execute("SELECT * FROM audit_log").fetchall()
        for row in audit_rows:
            assert raw_token not in str(dict(row))

    assert raw_token not in caplog.text