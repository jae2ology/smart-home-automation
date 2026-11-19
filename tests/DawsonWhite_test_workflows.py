import hashlib
import hmac
import json

import pytest

import app as homepulse
import db as database
from db import get_db, init_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Create a fresh seeded database for every test."""
    test_db = tmp_path / "homepulse_test.db"
    monkeypatch.setattr(database, "DB_PATH", str(test_db))

    original_exists = homepulse.os.path.exists
    app_db_path = homepulse.os.path.join(
        homepulse.os.path.dirname(homepulse.__file__),
        "app.db"
    )

    monkeypatch.setattr(
        homepulse.os.path,
        "exists",
        lambda path: True if str(path) == app_db_path else original_exists(path),
    )

    homepulse.app.config.update(TESTING=True)

    with homepulse.app.app_context():
        init_db()

        with homepulse.app.test_client() as test_client:
            yield test_client


def login_as(client, user_id, role):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["role"] = role
        session["name"] = "Test User"

def row_count(table):
    return get_db().execute(
        f"SELECT COUNT(*) AS count FROM {table}"
    ).fetchone()["count"]

#Dry run test:

def test_dryTrue_trigger_is_evaluated_without_executing(
    client, monkeypatch
):
    login_as(client, 1, "owner")

    gateway_calls = []

    monkeypatch.setattr(
        homepulse.device_gateway,
        "send",
        lambda *args, **kwargs: gateway_calls.append((args, kwargs)),
    )

    before_runs = row_count("rule_runs")
    before_commands = row_count("device_commands")

    response = client.post(
        "/rules/1/dry-run",
        data={"value": "85"}
    )

    assert response.status_code == 200

    result = response.get_json()

    assert result["evaluated"] is True
    assert result["matched"] is True
    assert result["actions"]

    assert gateway_calls == []
    assert row_count("rule_runs") == before_runs
    assert row_count("device_commands") == before_commands

def test_dryFalse_condition_reports_failed_evaluation(client):
    login_as(client, 1, "owner")

    response = client.post(
        "/rules/1/dry-run",
        data={"value": "72"}
    )

    assert response.status_code == 200

    result = response.get_json()

    assert result["evaluated"] is False
    assert result["matched"] is False
    assert result["failed_conditions"]

def test_dry_does_not_start_cooldown_and_real_event_runs(client):
    login_as(client, 1, "owner")

    rule = get_db().execute(
        "SELECT last_run_at FROM rules WHERE id = 1"
    ).fetchone()

    assert rule["last_run_at"] is None

    client.post(
        "/rules/1/dry-run",
        data={"value": "85"}
    )

    rule_after = get_db().execute(
        "SELECT last_run_at FROM rules WHERE id = 1"
    ).fetchone()

    assert rule_after["last_run_at"] is None

    response = client.post(
        "/api/device/telemetry",
        headers={"X-Device-Token": "token-motion-plain"},
        json={
            "device_id": 2,
            "source_event_id": "TC-DRY-03-REAL-EVENT",
            "metric": "motion",
            "value": 1,
            "reported_at": "2026-11-11T23:00:00"
        }
    )

    assert response.status_code == 201

    rule_run = get_db().execute(
        "SELECT * FROM rule_runs WHERE rule_id = 1"
    ).fetchone()

    assert rule_run is not None

def test_dry_has_no_actuator_alert_or_history_side_effects(
    client, monkeypatch
):
    login_as(client, 1, "owner")

    gateway_calls = []

    monkeypatch.setattr(
        homepulse.device_gateway,
        "send",
        lambda *args, **kwargs: gateway_calls.append((args, kwargs)),
    )

    get_db().execute(
        """
        INSERT INTO rule_actions (rule_id, device_id, command)
        VALUES (2, 1, 'LOCK')
        """
    )
    get_db().commit()

    before_runs = row_count("rule_runs")
    before_commands = row_count("device_commands")
    before_alerts = row_count("alerts")

    response = client.post(
        "/rules/2/dry-run",
        data={"value": "10"}
    )

    assert response.status_code == 200

    assert gateway_calls == []
    assert row_count("rule_runs") == before_runs
    assert row_count("device_commands") == before_commands
    assert row_count("alerts") == before_alerts

def test_dry_non_member_cannot_run_other_homes_rule(client):
    login_as(client, 3, "installer")

    response = client.post(
        "/rules/1/dry-run",
        data={"value": "1"}
    )

    assert response.status_code == 403


#Webhook test:

def test_hook_delivery_uses_hmac_sha256_signature(client, monkeypatch):
    login_as(client, 5, "admin")

    captured = {}

    def fake_post(url, payload, signature):
        captured["url"] = url
        captured["payload"] = payload
        captured["signature"] = signature

        return {
            "status": "DELIVERED",
            "code": 200
        }

    monkeypatch.setattr(
        homepulse.webhook_gateway,
        "post",
        fake_post
    )

    payload = {
        "event_type": "ALERT_CREATED",
        "event_id": "E-HOOK-01"
    }

    response = client.post(
        "/admin/webhooks/1/deliver",
        data={
            "event_id": "E-HOOK-01",
            "payload": json.dumps(payload)
        }
    )

    assert response.status_code == 200

    expected_signature = hmac.new(
        b"sec_key_123",
        json.dumps(payload, sort_keys=True).encode(),
        hashlib.sha256
    ).hexdigest()

    assert captured["signature"] == expected_signature
    assert "plain-webhook-secret" not in json.dumps(captured["payload"])

def test_hook_retry_keeps_original_event_id_and_increments_attempt(
    client, monkeypatch
):
    login_as(client, 5, "admin")

    gateway_calls = []

    def fake_post(url, payload, signature):
        gateway_calls.append(payload)

        attempt = len(gateway_calls)

        if attempt <= 2:
            return {
                "status": "FAILED",
                "code": 503
            }

        return {
            "status": "DELIVERED",
            "code": 200
        }

    monkeypatch.setattr(
        homepulse.webhook_gateway,
        "post",
        fake_post
    )

    get_db().execute(
        """
        INSERT INTO webhook_deliveries
        (webhook_id, event_id, payload, status, attempt, response_code)
        VALUES (1, 'E-HOOK-99', '{"event_type":"DEVICE_OFFLINE"}',
                'FAILED', 1, 503)
        """
    )
    get_db().commit()

    response = client.post("/admin/webhook-retry")

    assert response.status_code == 200

    deliveries = get_db().execute(
        """
        SELECT event_id, attempt
        FROM webhook_deliveries
        WHERE event_id = 'E-HOOK-99'
        ORDER BY attempt
        """
    ).fetchall()

    assert len(gateway_calls) == 3

    assert len(deliveries) == 3

    assert all(
        row["event_id"] == "E-HOOK-99"
        for row in deliveries
    )

    assert [row["attempt"] for row in deliveries] == [1, 2, 3]

    assert [row["response_code"] for row in deliveries] == [
    503, 503, 200
]
def test_hook_stop_retry_after_maximum_attempts(client, monkeypatch):
    login_as(client, 5, "admin")

    gateway_calls = []

    def fake_post(url, payload, signature):
        gateway_calls.append(payload)

        return {
            "status": "FAILED",
            "code": 500
        }

    monkeypatch.setattr(
        homepulse.webhook_gateway,
        "post",
        fake_post
    )

    get_db().execute(
        """
        INSERT INTO webhook_deliveries
        (webhook_id, event_id, payload, status, attempt, response_code)
        VALUES (1, 'E-HOOK-MAX', '{"event_type":"DEVICE_OFFLINE"}',
                'FAILED', 5, 500)
        """
    )
    get_db().commit()

    response = client.post("/admin/webhook-retry")

    assert response.status_code == 200
    assert gateway_calls == []

def test_hook_signing_secret_is_not_in_payload_or_delivery_record(
    client, monkeypatch, caplog
):
    login_as(client, 5, "admin")

    captured = {}

    def fake_post(url, payload, signature):
        captured["payload"] = payload

        return {
            "status": "DELIVERED",
            "code": 200
        }

    monkeypatch.setattr(
        homepulse.webhook_gateway,
        "post",
        fake_post
    )

    response = client.post(
        "/admin/webhooks/1/deliver",
        json={"event_type": "DEVICE_OFFLINE"}
    )

    assert response.status_code == 200

    stored = get_db().execute(
        "SELECT payload FROM webhook_deliveries ORDER BY id DESC LIMIT 1"
    ).fetchone()

    assert "plain-webhook-secret" not in json.dumps(captured["payload"])
    assert "plain-webhook-secret" not in stored["payload"]
    assert "plain-webhook-secret" not in caplog.text

def test_hook_inactive_webhook_is_skipped_without_http_call(
    client, monkeypatch
):
    login_as(client, 5, "admin")

    gateway_calls = []

    def fake_post(url, payload, signature):
        gateway_calls.append(payload)

        return {
            "status": "DELIVERED",
            "code": 200
        }

    monkeypatch.setattr(
        homepulse.webhook_gateway,
        "post",
        fake_post
    )

    get_db().execute(
        "UPDATE webhooks SET active = 0 WHERE id = 1"
    )
    get_db().commit()

    response = client.post(
        "/admin/webhooks/1/deliver",
        json={"event_type": "DEVICE_OFFLINE"}
    )

    assert response.status_code == 200

    result = response.get_json()

    assert result["status"] == "SKIPPED"
    assert gateway_calls == []