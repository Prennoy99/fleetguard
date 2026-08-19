"""Tests for the FastAPI service (app/main.py). /health is public (the
platform health check hits it unauthenticated); everything else requires
the X-API-Key header. The approve/reject round trip exercises the real DB
via agent.incidents_db — no LLM call needed, same reasoning as
test_orchestrator.py's approve/reject tests. /diagnose itself (a live Gemini
call) is validated separately via scripts/manual_diagnose.py and the
evaluation harness, not re-tested here.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("API_KEY", "test-key-for-pytest")

from agent.incidents_db import insert_incident
from app.main import app
from generator.db import get_connection
from generator.scenarios import build_scenarios

SCENARIOS = {s["scenario_id"]: s for s in build_scenarios()}
client = TestClient(app)
AUTH = {"X-API-Key": os.environ["API_KEY"]}


@pytest.fixture(scope="module")
def conn():
    connection = get_connection()
    yield connection
    connection.close()


def test_health_is_public():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_diagnose_requires_api_key():
    resp = client.post("/diagnose", json={
        "vehicle_id": "veh-000", "start_time": "2026-01-01T00:00:00Z", "end_time": "2026-01-01T01:00:00Z",
    })
    assert resp.status_code == 401


def test_diagnose_rejects_wrong_api_key():
    resp = client.post(
        "/diagnose",
        json={"vehicle_id": "veh-000", "start_time": "2026-01-01T00:00:00Z", "end_time": "2026-01-01T01:00:00Z"},
        headers={"X-API-Key": "wrong"},
    )
    assert resp.status_code == 401


def test_get_incident_round_trip(conn):
    s = SCENARIOS["S02"]
    incident = insert_incident(
        conn=conn, vehicle_id=s["vehicle_id"], window_start=s["start_time"], window_end=s["end_time"],
        severity="low", signals=["oil_pressure_bar"], reasoning=["test"], diagnosis="test",
        tool_call_log=[], status="auto_closed",
    )
    resp = client.get(f"/incidents/{incident['id']}", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["severity"] == "low"


def test_get_incident_missing_returns_404(conn):
    resp = client.get("/incidents/999999999", headers=AUTH)
    assert resp.status_code == 404


def test_approve_reject_round_trip(conn):
    s = SCENARIOS["S13"]
    incident = insert_incident(
        conn=conn, vehicle_id=s["vehicle_id"], window_start=s["start_time"], window_end=s["end_time"],
        severity="high", signals=["oil_pressure_bar"], reasoning=["test"], diagnosis="test",
        tool_call_log=[], status="pending_approval",
    )
    resp = client.post(f"/incidents/{incident['id']}/approve", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    # Already resolved -> 409, not a silent re-approve.
    again = client.post(f"/incidents/{incident['id']}/approve", headers=AUTH)
    assert again.status_code == 409


def test_reject_incident(conn):
    s = SCENARIOS["S14"]
    incident = insert_incident(
        conn=conn, vehicle_id=s["vehicle_id"], window_start=s["start_time"], window_end=s["end_time"],
        severity="high", signals=["battery_v"], reasoning=["test"], diagnosis="test",
        tool_call_log=[], status="pending_approval",
    )
    resp = client.post(f"/incidents/{incident['id']}/reject", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
