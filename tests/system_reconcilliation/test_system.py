import hashlib
import os
import sqlite3
import sys
import pytest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import db as db_module
from app import app


# Homes in seed.sql:
#   id=1 -> 'Maple House' (enrolled in monitoring_enrollments with status='ACTIVE')
#   id=2 -> 'Coastal Condo' (NOT enrolled in monitoring_enrollments)
HOME_1_ID = 1
HOME_2_ID = 2

# Devices in seed.sql:
#   id=1 -> 'Front Door Lock' (home_id=1)
#   id=5 -> 'Condo Leak Sensor' (home_id=2)
HOME_1_DEVICE_ID = 1
HOME_2_DEVICE_ID = 5

def compute_database_snapshot_hash(db_path: str) -> str:
    """
    Computes a deterministic SHA-256 checksum over the schema and all rows of every
    user table in the SQLite database to verify read-only execution (`FR-46`).
    """
    conn = sqlite3.connect(db_path)
    try:
        hasher = hashlib.sha256()
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        for table in tables:
            hasher.update(table.encode("utf-8"))
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for r in rows:
                hasher.update(repr(tuple(r)).encode("utf-8"))
        return hasher.hexdigest()
    finally:
        conn.close()


@pytest.fixture
def client_with_corrupted_db(tmp_path, monkeypatch):
    """
    Redirects `db.DB_PATH` to an isolated temporary SQLite database, initializes
    `schema.sql` + `seed.sql`, and seeds the 4 intentional data anomalies defined
    in Section 4 (Test Data & Environment Setup):
      1. Mismatched device `last_seen_at` vs latest telemetry `reported_at`.
      2. Orphaned action targeting a non-existent `device_id` (9999).
      3. Cross-home reference: Rule in Home 1 targeting Device 5 (belongs to Home 2).
      4. Monitoring alert/event record for Home 2 (unenrolled home).
    """
    test_db_path = tmp_path / "test_reconciliation.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(test_db_path))
    monkeypatch.setattr(app, "before_request_funcs", {None: []})

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db_module.init_db()
        db = db_module.get_db()

        # Anomaly 1: Device 1 last_seen_at = 08:00 AM, but telemetry reported_at = 10:00 AM
        db.execute(
            "UPDATE devices SET last_seen_at = '2026-11-17T08:00:00' WHERE id = ?",
            (HOME_1_DEVICE_ID,),
        )
        db.execute(
            "INSERT INTO telemetry(device_id, source_event_id, metric, value, reported_at, received_at) "
            "VALUES (?, 'evt-recon-mismatch-1', 'battery', 79, '2026-11-17T10:00:00', '2026-11-17T10:00:01')",
            (HOME_1_DEVICE_ID,),
        )

        # Anomaly 2: Orphaned scene_action & rule_action targeting non-existent device_id = 9999
        db.execute(
            "INSERT INTO scene_actions(scene_id, device_id, command, payload, sequence_no) "
            "VALUES (1, 9999, 'OFF', '{}', 99)"
        )
        db.execute(
            "INSERT INTO rule_actions(rule_id, device_id, command, payload, sequence_no) "
            "VALUES (1, 9999, 'ON', '{}', 99)"
        )

        # Anomaly 3: Cross-home reference — Rule 1 (in Home 1) targeting Device 5 (in Home 2)
        db.execute(
            "INSERT INTO rule_actions(rule_id, device_id, command, payload, sequence_no) "
            "VALUES (1, ?, 'OFF', '{}', 100)",
            (HOME_2_DEVICE_ID,),
        )

        # Anomaly 4: Alert & monitoring event on Home 2 (Coastal Condo has NO active monitoring_enrollment)
        cur_alert = db.execute(
            "INSERT INTO alerts(home_id, device_id, kind, severity, message, status, dedup_key, created_at) "
            "VALUES (?, ?, 'WATER_LEAK', 'CRITICAL', 'Leak in unenrolled home', 'OPEN', '5:WATER_LEAK', '2026-11-17T09:00:00')",
            (HOME_2_ID, HOME_2_DEVICE_ID),
        )
        unenrolled_alert_id = cur_alert.lastrowid
        db.execute(
            "INSERT INTO monitoring_events(enrollment_id, alert_id, event_type, status, details, created_at) "
            "VALUES (NULL, ?, 'DISPATCH', 'SENT', 'Dispatched without enrollment', '2026-11-17T09:01:00')",
            (unenrolled_alert_id,),
        )

        db.commit()

    with app.test_client() as test_client:
        yield test_client, str(test_db_path)


def login_as_admin(test_client):
    """Authenticates as seeded admin (`admin@example.com` / `admin`) required by `@roles_required('admin')`."""
    return test_client.post(
        "/login",
        data={"email": "admin@example.com", "password": "admin"},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Test Cases (Section 3: Test Cases & Matrix)
# ---------------------------------------------------------------------------

def test_tc_recon_01_detection_of_inconsistent_device_last_seen_state(client_with_corrupted_db):
    """
    TC-RECON-01: Detection of Inconsistent Device Last-Seen State
    Type: Positive (State Consistency / Diagnostic)
    Inputs: Device 1 has `last_seen_at = 08:00 AM`, while latest telemetry `reported_at = 10:00 AM`.
    Expected: Reconciliation report flags `DEV_LAST_SEEN_MISMATCH` (or `LAST_SEEN_MISMATCH`)
              with device ID (`1`) and delta/timestamp details.
    Traceability: FR-46, NFR-15
    """
    client, _ = client_with_corrupted_db
    login_as_admin(client)

    resp = client.get("/admin/reconciliation")
    assert resp.status_code == 200
    issues = resp.get_json().get("issues", [])

    mismatch_issues = [
        i for i in issues
        if i.get("device") == HOME_1_DEVICE_ID
        and i.get("type") in ("DEV_LAST_SEEN_MISMATCH", "LAST_SEEN_MISMATCH")
    ]
    assert len(mismatch_issues) == 1, f"Expected last-seen mismatch for device {HOME_1_DEVICE_ID}, got: {issues}"
    issue = mismatch_issues[0]
    assert "08:00:00" in str(issue.get("device_value"))
    assert "10:00:00" in str(issue.get("telemetry"))


def test_tc_recon_02_detection_of_orphan_actions_and_cross_home_references(client_with_corrupted_db):
    """
    TC-RECON-02: Detection of Orphan Actions & Cross-Home References
    Type: Positive / Edge (Referential & Domain Integrity Diagnostic)
    Inputs:
      - Scene/rule action targeting non-existent `device_id = 9999`.
      - Rule 1 (Home 1) action targeting Device 5 (Home 2).
    Expected: Report flags both `ORPHAN_ACTION` and `CROSS_HOME_REFERENCE_VIOLATION`.
    Traceability: FR-46, NFR-15
    """
    client, _ = client_with_corrupted_db
    login_as_admin(client)

    resp = client.get("/admin/reconciliation")
    assert resp.status_code == 200
    issues = resp.get_json().get("issues", [])
    issue_types = {i.get("type") for i in issues}

    assert "ORPHAN_ACTION" in issue_types, (
        f"Integrity Defect (FR-46/NFR-15): Reconciliation failed to flag ORPHAN_ACTION "
        f"for non-existent device_id=9999. Returned issues: {issues}"
    )
    assert "CROSS_HOME_REFERENCE_VIOLATION" in issue_types, (
        f"Integrity Defect (FR-46/NFR-15): Reconciliation failed to flag CROSS_HOME_REFERENCE_VIOLATION "
        f"for Home 1 rule targeting Home 2 device. Returned issues: {issues}"
    )


def test_tc_recon_03_detection_of_invalid_alert_monitoring_combinations(client_with_corrupted_db):
    """
    TC-RECON-03: Detection of Invalid Alert/Monitoring Combinations
    Type: Positive (Business Rule / Domain Consistency Diagnostic)
    Inputs: Alert and monitoring dispatch event recorded for Home 2 (`Coastal Condo`),
            which has no active record in `monitoring_enrollments`.
    Expected: Report flags `INVALID_MONITORING_ENROLLMENT_ALERT`.
    Traceability: FR-46
    """
    client, _ = client_with_corrupted_db
    login_as_admin(client)

    resp = client.get("/admin/reconciliation")
    assert resp.status_code == 200
    issues = resp.get_json().get("issues", [])
    issue_types = {i.get("type") for i in issues}

    assert "INVALID_MONITORING_ENROLLMENT_ALERT" in issue_types, (
        f"Diagnostic Defect (FR-46): Reconciliation failed to flag INVALID_MONITORING_ENROLLMENT_ALERT "
        f"for unenrolled Home {HOME_2_ID}. Returned issues: {issues}"
    )


def test_tc_recon_04_read_only_audit_execution_guarantee(client_with_corrupted_db):
    """
    TC-RECON-04: Read-Only Audit Execution Guarantee
    Type: Security / Boundary (Non-Destructive Read-Only Verification)
    Inputs: Capture SHA-256 database snapshot -> Execute `GET /admin/reconciliation` ->
            Capture post-run SHA-256 database snapshot.
    Expected: Pre-run and post-run database checksums are identical (0 records modified/repaired).
    Traceability: FR-46
    """
    client, db_path = client_with_corrupted_db
    login_as_admin(client)

    checksum_before = compute_database_snapshot_hash(db_path)

    resp = client.get("/admin/reconciliation")
    assert resp.status_code == 200

    checksum_after = compute_database_snapshot_hash(db_path)

    assert checksum_before == checksum_after, (
        "Read-Only Violation (FR-46): Database state changed during GET /admin/reconciliation."
    )