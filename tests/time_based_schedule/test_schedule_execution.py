from datetime import datetime, timezone
import os
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo
import pytest

# Add project root (`smart-home-automation/`) to sys.path so `db` and `app` resolve
# regardless of whether pytest is invoked from the root or a subdirectory.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app as app_module
import db as db_module
from app import app

# Homes in seed.sql:
#   id=1 -> 'Maple House' (timezone='America/New_York')
#   id=2 -> 'Coastal Condo' (timezone='America/New_York')
HOME_1_ID = 1
HOME_2_ID = 2


class MockDateTime(datetime):
    """Deterministic clock replacement for `app.datetime` during schedule tests."""

    _current_utc: datetime = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)

    @classmethod
    def set_utc(cls, dt_utc: datetime):
        assert dt_utc.tzinfo is not None, "Provide a timezone-aware UTC datetime"
        cls._current_utc = dt_utc.astimezone(timezone.utc)

    @classmethod
    def utcnow(cls):
        # `app.py` calls `datetime.utcnow()` (naive UTC)
        return cls._current_utc.replace(tzinfo=None)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._current_utc.replace(tzinfo=None)
        return cls._current_utc.astimezone(tz)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    Redirects `db.DB_PATH` to a fresh temporary SQLite file, runs `db.init_db()`,
    clears default seeded schedules so each test controls its exact schedule setup,
    and monkeypatches `app.datetime` with `MockDateTime`.
    """
    test_db_path = tmp_path / "test_schedules.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(test_db_path))
    monkeypatch.setattr(app, "before_request_funcs", {None: []})
    monkeypatch.setattr(app_module, "datetime", MockDateTime)

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db_module.init_db()
        db = db_module.get_db()
        # Remove seeded schedule so test cases evaluate only the target schedule(s)
        db.execute("DELETE FROM schedule_runs")
        db.execute("DELETE FROM schedules")
        db.commit()

    with app.test_client() as test_client:
        yield test_client


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

def test_tc_sched_01_standard_timezone_schedule_trigger(client):
    """
    TC-SCHED-01: Standard Timezone Schedule Trigger
    Type: Positive
    Inputs: Schedule set for 07:00 AM daily in America/New_York (UTC-5). Server is in UTC.
    Expected: Schedule runs at exact local 07:00 AM (12:00 PM UTC). schedule_runs record logged.
    Traceability: FR-27, BR-07
    """
    # Standard Time (EST = UTC-5): 2026-11-16 07:00 America/New_York == 2026-11-16 12:00 UTC
    target_utc = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    MockDateTime.set_utc(target_utc)

    with app.app_context():
        db = db_module.get_db()
        cur = db.execute(
            "INSERT INTO schedules(home_id, name, timezone, cron_hour, cron_minute, weekday_mask, scene_id, enabled) "
            "VALUES (?, 'Morning Routine', 'America/New_York', 7, 0, '0,1,2,3,4,5,6', 1, 1)",
            (HOME_1_ID,),
        )
        schedule_id = cur.lastrowid
        db.commit()

    login_as_admin(client)

    with patch.object(app_module.device_gateway, "send", return_value={"status": "ACK"}) as mock_send:
        resp = client.post("/jobs/schedules")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ran"] == 1, (
        f"Timezone Defect (FR-27/BR-07): Schedule set for 07:00 America/New_York did not trigger "
        f"at 12:00 UTC (ran={body['ran']}; app.py compares cron_hour against server UTC hour)."
    )
    assert mock_send.called

    with app.app_context():
        db = db_module.get_db()
        runs = db.execute("SELECT * FROM schedule_runs WHERE schedule_id = ?", (schedule_id,)).fetchall()
        assert len(runs) == 1
        assert runs[0]["status"] == "SUCCESS"


def test_tc_sched_02_weekday_mask_filtering(client):
    """
    TC-SCHED-02: Weekday Mask Filtering
    Type: Positive
    Inputs: Schedule configured for Mon-Fri ('0,1,2,3,4') at 08:00 AM. Simulate Saturday 08:00 AM.
    Expected: Schedule evaluator skips execution. No action or schedule_runs record generated.
    Traceability: FR-27
    """
    # 2026-11-21 is a Saturday (weekday() == 5)
    saturday_utc = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)
    MockDateTime.set_utc(saturday_utc)

    with app.app_context():
        db = db_module.get_db()
        cur = db.execute(
            "INSERT INTO schedules(home_id, name, timezone, cron_hour, cron_minute, weekday_mask, scene_id, enabled) "
            "VALUES (?, 'Weekday Wakeup', 'UTC', 8, 0, '0,1,2,3,4', 1, 1)",
            (HOME_1_ID,),
        )
        schedule_id = cur.lastrowid
        db.commit()

    login_as_admin(client)

    with patch.object(app_module.device_gateway, "send", return_value={"status": "ACK"}) as mock_send:
        resp = client.post("/jobs/schedules")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ran"] == 0, (
        f"Weekday Mask Defect (FR-27): Schedule with Mon-Fri mask ('0,1,2,3,4') executed on Saturday "
        f"(ran={body['ran']}; app.py ignores weekday_mask)."
    )
    assert not mock_send.called

    with app.app_context():
        db = db_module.get_db()
        runs = db.execute("SELECT * FROM schedule_runs WHERE schedule_id = ?", (schedule_id,)).fetchall()
        assert len(runs) == 0


def test_tc_sched_03_dst_spring_forward_skipped_hour(client):
    """
    TC-SCHED-03: DST Spring-Forward (Skipped Hour)
    Type: Boundary / Edge
    Inputs: Schedule set for 02:30 AM in America/New_York. On DST Spring-Forward night
            (2026-03-08), local clocks jump from 01:59:59 EST (06:59:59 UTC) to 03:00:00 EDT (07:00:00 UTC).
    Expected: Policy applied cleanly at 03:00 AM transition without missing or looping; exactly 1 run recorded.
    Traceability: FR-28, FR-29
    """
    with app.app_context():
        db = db_module.get_db()
        cur = db.execute(
            "INSERT INTO schedules(home_id, name, timezone, cron_hour, cron_minute, weekday_mask, scene_id, enabled) "
            "VALUES (?, 'DST Spring Forward Test', 'America/New_York', 2, 30, '0,1,2,3,4,5,6', 1, 1)",
            (HOME_1_ID,),
        )
        schedule_id = cur.lastrowid
        db.commit()

    login_as_admin(client)

    # Simulate scheduler ticks across the spring-forward boundary:
    # 01:59 EST (06:59 UTC) -> 03:00 EDT (07:00 UTC) -> 03:01 EDT (07:01 UTC)
    ticks_utc = [
        datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc),
        datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc),
        datetime(2026, 3, 8, 7, 1, tzinfo=timezone.utc),
    ]

    for tick in ticks_utc:
        MockDateTime.set_utc(tick)
        resp = client.post("/jobs/schedules")
        assert resp.status_code == 200

    with app.app_context():
        db = db_module.get_db()
        runs = db.execute("SELECT * FROM schedule_runs WHERE schedule_id = ?", (schedule_id,)).fetchall()
        assert len(runs) == 1, (
            f"DST Spring-Forward Defect (FR-28/FR-29): Expected exactly 1 run for skipped 02:30 AM "
            f"America/New_York occurrence, but recorded {len(runs)} runs."
        )


def test_tc_sched_04_dst_fall_back_repeated_hour(client):
    """
    TC-SCHED-04: DST Fall-Back (Repeated Hour)
    Type: Boundary / Edge
    Inputs: Schedule set for 01:30 AM in America/New_York. On DST Fall-Back night (2026-11-01),
            01:30 AM occurs twice:
              Pass 1: 01:30 EDT (UTC-4) == 05:30 UTC
              Pass 2: 01:30 EST (UTC-5) == 06:30 UTC
    Expected: Executes on the first pass and does NOT duplicate execution on the second pass ("at most once").
    Traceability: FR-28, FR-29, BR-07, UC-04
    """
    with app.app_context():
        db = db_module.get_db()
        cur = db.execute(
            "INSERT INTO schedules(home_id, name, timezone, cron_hour, cron_minute, weekday_mask, scene_id, enabled) "
            "VALUES (?, 'DST Fall Back Test', 'America/New_York', 1, 30, '0,1,2,3,4,5,6', 1, 1)",
            (HOME_1_ID,),
        )
        schedule_id = cur.lastrowid
        db.commit()

    login_as_admin(client)

    # Pass 1: 01:30 AM EDT (05:30 UTC)
    MockDateTime.set_utc(datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc))
    resp_pass_1 = client.post("/jobs/schedules")
    assert resp_pass_1.status_code == 200

    # Pass 2: 01:30 AM EST (06:30 UTC) — repeated local wall-clock time 1 hour later
    MockDateTime.set_utc(datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc))
    resp_pass_2 = client.post("/jobs/schedules")
    assert resp_pass_2.status_code == 200

    with app.app_context():
        db = db_module.get_db()
        runs = db.execute("SELECT * FROM schedule_runs WHERE schedule_id = ?", (schedule_id,)).fetchall()
        assert len(runs) == 1, (
            f"DST Fall-Back Defect (FR-28/FR-29/BR-07/UC-04): Expected exactly 1 execution across repeated "
            f"01:30 AM hour, but recorded {len(runs)} runs."
        )


def test_tc_sched_05_multiple_homes_with_different_timezones(client):
    """
    TC-SCHED-05: Multiple Homes with Different Timezones
    Type: Concurrent / Multi-Timezone
    Inputs:
      - Schedule 1 (Home 1): 06:00 PM (18:00) in Europe/London (UTC+0 in Nov) -> triggers at 18:00 UTC.
      - Schedule 2 (Home 2): 06:00 PM (18:00) in America/Los_Angeles (UTC-8 in Nov) -> triggers at 02:00 UTC next day.
    Expected: Each schedule runs only at its respective local 06:00 PM time, independent of server UTC clock.
    Traceability: FR-27, BR-07
    """
    with app.app_context():
        db = db_module.get_db()
        db.execute("UPDATE homes SET timezone = 'Europe/London' WHERE id = ?", (HOME_1_ID,))
        db.execute("UPDATE homes SET timezone = 'America/Los_Angeles' WHERE id = ?", (HOME_2_ID,))

        cur1 = db.execute(
            "INSERT INTO schedules(home_id, name, timezone, cron_hour, cron_minute, weekday_mask, scene_id, enabled) "
            "VALUES (?, 'London Evening', 'Europe/London', 18, 0, '0,1,2,3,4,5,6', 1, 1)",
            (HOME_1_ID,),
        )
        sched_london_id = cur1.lastrowid

        cur2 = db.execute(
            "INSERT INTO schedules(home_id, name, timezone, cron_hour, cron_minute, weekday_mask, scene_id, enabled) "
            "VALUES (?, 'LA Evening', 'America/Los_Angeles', 18, 0, '0,1,2,3,4,5,6', 1, 1)",
            (HOME_2_ID,),
        )
        sched_la_id = cur2.lastrowid
        db.commit()

    login_as_admin(client)

    # Tick A: 18:00 UTC == 18:00 Europe/London (triggers), 10:00 America/Los_Angeles (must NOT trigger)
    MockDateTime.set_utc(datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc))
    resp_a = client.post("/jobs/schedules")
    assert resp_a.status_code == 200
    assert resp_a.get_json()["ran"] == 1, (
        "Multi-Timezone Defect (FR-27/BR-07): Expected only Europe/London schedule to run at 18:00 UTC."
    )

    with app.app_context():
        db = db_module.get_db()
        london_runs = db.execute("SELECT * FROM schedule_runs WHERE schedule_id = ?", (sched_london_id,)).fetchall()
        la_runs_early = db.execute("SELECT * FROM schedule_runs WHERE schedule_id = ?", (sched_la_id,)).fetchall()
        assert len(london_runs) == 1
        assert len(la_runs_early) == 0

    # Tick B: 02:00 UTC next day == 18:00 America/Los_Angeles (triggers), 02:00 Europe/London (must NOT trigger)
    MockDateTime.set_utc(datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc))
    resp_b = client.post("/jobs/schedules")
    assert resp_b.status_code == 200
    assert resp_b.get_json()["ran"] == 1, (
        "Multi-Timezone Defect (FR-27/BR-07): Expected America/Los_Angeles schedule to run at 02:00 UTC (18:00 PST)."
    )

    with app.app_context():
        db = db_module.get_db()
        la_runs = db.execute("SELECT * FROM schedule_runs WHERE schedule_id = ?", (sched_la_id,)).fetchall()
        assert len(la_runs) == 1