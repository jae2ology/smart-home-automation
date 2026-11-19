from datetime import datetime, timedelta, timezone
import os
import sqlite3
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
HOME_A_ID = 1
HOME_A_DEVICE_ID = 1
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin"


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
def retention_env(tmp_path, monkeypatch):
    """
    Sets up an isolated SQLite database with `schema.sql` + `seed.sql` and seeds
    a clean telemetry dataset anchored to MockDateTime (2026-11-19T12:00:00Z)
    with a 90-day retention policy (`PURGE_TELEMETRY_DAYS = 90`, cutoff = 2026-08-21T12:00:00).
    """
    test_db_path = tmp_path / "test_retention.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(test_db_path))
    monkeypatch.setattr(app, "before_request_funcs", {None: []})
    monkeypatch.setattr(app_module, "datetime", MockDateTime)
    monkeypatch.setattr(domain_module, "datetime", MockDateTime)

    fixed_now = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
    MockDateTime.set_utc(fixed_now)

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db_module.init_db()
        db = db_module.get_db()

        # Clear pre-seeded telemetry/alerts/rule_runs so tests control exact records
        db.execute("DELETE FROM alert_acknowledgements")
        db.execute("DELETE FROM alerts")
        db.execute("DELETE FROM rule_runs")
        db.execute("DELETE FROM telemetry")
        db.commit()

    with app.test_client() as client:
        # Authenticate as admin (if `/admin/retention` enforces role check)
        client.post(
            "/login",
            data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            follow_redirects=False,
        )
        yield client, fixed_now


def trigger_retention(client, days=90):
    return client.post(
        "/admin/retention",
        json={"days": days, "purge_telemetry_days": days},
    )
# ---------------------------------------------------------------------------
# Test Cases (Section 3: Test Cases & Matrix)
# ---------------------------------------------------------------------------

def test_tc_ret_01_age_based_telemetry_purge_or_archive(retention_env):
    """
    TC-RET-01: Age-Based Telemetry Purge / Archive
    Type: Positive
    Inputs: Retention threshold = 90 days. DB contains Telemetry A (91 days old) and Telemetry B (89 days old).
    Expected: Retention job runs: Telemetry A archived/purged from active telemetry; Telemetry B preserved.
    Traceability: FR-42, BR-09
    """
    client, now_utc = retention_env
    ts_91_days_old = (now_utc - timedelta(days=91)).replace(tzinfo=None).isoformat(timespec="seconds")
    ts_89_days_old = (now_utc - timedelta(days=89)).replace(tzinfo=None).isoformat(timespec="seconds")

    with app.app_context():
        db = db_module.get_db()
        db.execute(
            "INSERT INTO telemetry(device_id, metric, value, reported_at, source_event_id) "
            "VALUES (?, 'temp', 70.0, ?, 'E-RET-91D')",
            (HOME_A_DEVICE_ID, ts_91_days_old),
        )
        db.execute(
            "INSERT INTO telemetry(device_id, metric, value, reported_at, source_event_id) "
            "VALUES (?, 'temp', 72.0, ?, 'E-RET-89D')",
            (HOME_A_DEVICE_ID, ts_89_days_old),
        )
        db.commit()

    resp = trigger_retention(client, days=90)
    assert resp.status_code in (200, 204, 302)

    with app.app_context():
        db = db_module.get_db()
        row_91 = db.execute("SELECT * FROM telemetry WHERE source_event_id = 'E-RET-91D'").fetchone()
        row_89 = db.execute("SELECT * FROM telemetry WHERE source_event_id = 'E-RET-89D'").fetchone()

        assert row_91 is None, "Telemetry A (91 days old) should be purged or moved out of active telemetry."
        assert row_89 is not None, "Telemetry B (89 days old) must be preserved."


def test_tc_ret_02_referential_integrity_lock_active_alert(retention_env):
    """
    TC-RET-02: Referential Integrity Lock (Active Alert & RuleRun)
    Type: Boundary / Edge
    Inputs:
      - Record T1: Age 120 days (Unlinked)
      - Record T2: Age 120 days (Linked via source_event_id to OPEN Alert ALT-50 and active RuleRun)
      - Record T3: Age 30 days (Unlinked)
    Expected: T1 is purged/archived; T3 is preserved; T2 is preserved (or safely archived with
              relational linkage intact) without orphan alert references or DB foreign key errors.
    Traceability: FR-43, NFR-15
    """
    client, now_utc = retention_env
    ts_120_days_old = (now_utc - timedelta(days=120)).replace(tzinfo=None).isoformat(timespec="seconds")
    ts_30_days_old = (now_utc - timedelta(days=30)).replace(tzinfo=None).isoformat(timespec="seconds")

    with app.app_context():
        db = db_module.get_db()
        # T1: Unlinked 120-day-old telemetry
        db.execute(
            "INSERT INTO telemetry(device_id, metric, value, reported_at, source_event_id) "
            "VALUES (?, 'temp', 68.0, ?, 'E-T1-UNLINKED')",
            (HOME_A_DEVICE_ID, ts_120_days_old),
        )
        # T2: Linked 120-day-old telemetry referenced by an OPEN alert (ALT-50)
        db.execute(
            "INSERT INTO telemetry(device_id, metric, value, reported_at, source_event_id) "
            "VALUES (?, 'smoke', 1.0, ?, 'E-T2-LINKED-ALT50')",
            (HOME_A_DEVICE_ID, ts_120_days_old),
        )
        db.execute(
            "INSERT INTO alerts(id, home_id, device_id, kind, severity, message, status, created_at, dedup_key) "
            "VALUES (50, ?, ?, 'FIRE_ALARM', 'CRITICAL', 'Active Alert ALT-50', 'OPEN', ?, 'E-T2-LINKED-ALT50')",
            (HOME_A_ID, HOME_A_DEVICE_ID, ts_120_days_old),
        )
        # Also link T2 in rule_runs if rule 1 exists
        rule_row = db.execute("SELECT id FROM rules LIMIT 1").fetchone()
        if rule_row:
            db.execute(
                "INSERT INTO rule_runs(rule_id, trigger_event_id, started_at, completed_at, status, details) "
                "VALUES (?, 'E-T2-LINKED-ALT50', ?, ?, 'SUCCESS', 'Triggered ALT-50')",
                (rule_row["id"], ts_120_days_old, ts_120_days_old),
            )

        # T3: Unlinked 30-day-old telemetry
        db.execute(
            "INSERT INTO telemetry(device_id, metric, value, reported_at, source_event_id) "
            "VALUES (?, 'temp', 71.5, ?, 'E-T3-RECENT')",
            (HOME_A_DEVICE_ID, ts_30_days_old),
        )
        db.commit()

    resp = trigger_retention(client, days=90)
    assert resp.status_code in (200, 204, 302)

    with app.app_context():
        db = db_module.get_db()
        t1 = db.execute("SELECT * FROM telemetry WHERE source_event_id = 'E-T1-UNLINKED'").fetchone()
        t2 = db.execute("SELECT * FROM telemetry WHERE source_event_id = 'E-T2-LINKED-ALT50'").fetchone()
        t3 = db.execute("SELECT * FROM telemetry WHERE source_event_id = 'E-T3-RECENT'").fetchone()
        alt_50 = db.execute("SELECT * FROM alerts WHERE id = 50").fetchone()

        assert t1 is None, "Unlinked 120-day record T1 should be purged."
        assert t3 is not None, "Recent 30-day record T3 must be preserved."
        assert alt_50 is not None and alt_50["status"] == "OPEN"
        assert t2 is not None, (
            "Referential Integrity Defect (FR-43/NFR-15): Retention job hard-deleted 120-day telemetry "
            "record T2 ('E-T2-LINKED-ALT50') even though it is directly referenced by OPEN Alert ALT-50 "
            "and an active rule_run audit trail, creating an orphaned reference."
        )


def test_tc_ret_03_boundary_retention_window_testing(retention_env):
    """
    TC-RET-03: Boundary Retention Window Testing
    Type: Boundary
    Inputs: DB contains telemetry records at:
      - Cutoff - 1 second (90 days + 1 second old -> strictly older than cutoff)
      - Cutoff            (exactly 90 days old)
      - Cutoff + 1 second (90 days - 1 second old -> newer than cutoff)
    Expected: Only records strictly older than cutoff (Cutoff - 1s) are purged/archived;
              exact Cutoff and Cutoff + 1s records remain intact.
    Traceability: FR-42, BR-09
    """
    client, now_utc = retention_env
    cutoff = (now_utc - timedelta(days=90)).replace(tzinfo=None)

    ts_older = (cutoff - timedelta(seconds=1)).isoformat(timespec="seconds")
    ts_exact = cutoff.isoformat(timespec="seconds")
    ts_newer = (cutoff + timedelta(seconds=1)).isoformat(timespec="seconds")

    with app.app_context():
        db = db_module.get_db()
        db.execute(
            "INSERT INTO telemetry(device_id, metric, value, reported_at, source_event_id) "
            "VALUES (?, 'temp', 60.0, ?, 'E-CUTOFF-MINUS-1S')",
            (HOME_A_DEVICE_ID, ts_older),
        )
        db.execute(
            "INSERT INTO telemetry(device_id, metric, value, reported_at, source_event_id) "
            "VALUES (?, 'temp', 61.0, ?, 'E-CUTOFF-EXACT')",
            (HOME_A_DEVICE_ID, ts_exact),
        )
        db.execute(
            "INSERT INTO telemetry(device_id, metric, value, reported_at, source_event_id) "
            "VALUES (?, 'temp', 62.0, ?, 'E-CUTOFF-PLUS-1S')",
            (HOME_A_DEVICE_ID, ts_newer),
        )
        db.commit()

    resp = trigger_retention(client, days=90)
    assert resp.status_code in (200, 204, 302)

    with app.app_context():
        db = db_module.get_db()
        row_older = db.execute("SELECT * FROM telemetry WHERE source_event_id = 'E-CUTOFF-MINUS-1S'").fetchone()
        row_exact = db.execute("SELECT * FROM telemetry WHERE source_event_id = 'E-CUTOFF-EXACT'").fetchone()
        row_newer = db.execute("SELECT * FROM telemetry WHERE source_event_id = 'E-CUTOFF-PLUS-1S'").fetchone()

        assert row_older is None, "Record at Cutoff - 1s (older than 90d) should be purged."
        assert row_exact is not None, "Record at exact Cutoff (90d) must remain intact."
        assert row_newer is not None, "Record at Cutoff + 1s (newer than 90d) must remain intact."


def test_tc_ret_04_failed_archival_transaction_rollback(retention_env, monkeypatch):
    """
    TC-RET-04: Failed Archival Transaction Rollback
    Type: Exception / Recovery
    Inputs: System encounters a database error mid-batch during retention processing.
    Expected: Transaction rolls back completely. No partially deleted or corrupted telemetry states.
    Traceability: NFR-02, NFR-14
    """
    client, now_utc = retention_env
    ts_100_days_old = (now_utc - timedelta(days=100)).replace(tzinfo=None).isoformat(timespec="seconds")

    with app.app_context():
        db = db_module.get_db()
        db.execute(
            "INSERT INTO telemetry(device_id, metric, value, reported_at, source_event_id) "
            "VALUES (?, 'temp', 55.0, ?, 'E-ROLLBACK-1')",
            (HOME_A_DEVICE_ID, ts_100_days_old),
        )
        db.execute(
            "INSERT INTO telemetry(device_id, metric, value, reported_at, source_event_id) "
            "VALUES (?, 'temp', 56.0, ?, 'E-ROLLBACK-2')",
            (HOME_A_DEVICE_ID, ts_100_days_old),
        )
        db.commit()

    # Inject a database failure during retention execution (e.g., on commit or secondary step)
    real_get_db = db_module.get_db

    class FailingCommitConnection:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, params=()):
            return self._conn.execute(sql, params)

        def executemany(self, sql, seq):
            return self._conn.executemany(sql, seq)

        def commit(self):
            raise sqlite3.OperationalError("Simulated disk I/O failure during archival batch commit")

        def rollback(self):
            return self._conn.rollback()

        def __getattr__(self, name):
            return getattr(self._conn, name)

    def failing_get_db():
        conn = real_get_db()
        return FailingCommitConnection(conn)

    monkeypatch.setattr(app_module, "get_db", failing_get_db)
    monkeypatch.setattr(db_module, "get_db", failing_get_db)

    with pytest.raises(sqlite3.OperationalError):
        trigger_retention(client, days=90)

    # Restore normal DB handle and verify full rollback (both records still present)
    monkeypatch.setattr(app_module, "get_db", real_get_db)
    monkeypatch.setattr(db_module, "get_db", real_get_db)

    with app.app_context():
        db = real_get_db()
        db.rollback()
        remaining = db.execute(
            "SELECT source_event_id FROM telemetry WHERE source_event_id IN ('E-ROLLBACK-1', 'E-ROLLBACK-2')"
        ).fetchall()
        assert len(remaining) == 2, (
            f"Transaction Rollback Defect (NFR-02/NFR-14): Expected all 2 batch records to roll back on DB error, "
            f"but found {[r['source_event_id'] for r in remaining]}."
        )