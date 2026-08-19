"""Unit tests for the agent orchestration loop (agent/orchestrator.py).

The Gemini call itself is stubbed (a scripted sequence of canned responses),
so these tests are deterministic and don't need network access or an API
key — consistent with the fixed temperature=0 used for live calls, just
extended to the test suite itself. What's *not* stubbed is everything
downstream of a tool-call decision: dispatch, the diagnostic tools, and
Postgres persistence all run for real against the live seeded DB, so these
tests genuinely exercise a hand-scripted end-to-end scenario at the
orchestration-logic level. The actual live Gemini integration (does the
model reliably choose to call these tools the way the system prompt asks)
is validated separately via scripts/manual_diagnose.py once a real
GEMINI_API_KEY is available — that's a model-behavior question this stub
can't answer.
"""
from types import SimpleNamespace

import pytest

from agent import orchestrator
from agent.incidents_db import approve_incident, get_incident, insert_incident, reject_incident
from generator.db import get_connection
from generator.scenarios import build_scenarios

SCENARIOS = {s["scenario_id"]: s for s in build_scenarios()}


@pytest.fixture(scope="module")
def conn():
    connection = get_connection()
    yield connection
    connection.close()


class _FakeCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class _FakeResponse:
    def __init__(self, calls=None, text=""):
        self.function_calls = calls or []
        self.text = text
        self.candidates = [SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))]


def _script(monkeypatch, responses):
    """Replace gemini_client.generate_content with a queue of canned responses."""
    queue = list(responses)

    def fake_generate_content(contents, tools, system_instruction):
        assert queue, "orchestrator called generate_content more times than scripted"
        return queue.pop(0)

    monkeypatch.setattr(orchestrator.gemini_client, "generate_content", fake_generate_content)


def test_diagnose_happy_path_calls_tools_in_scripted_order_and_persists(monkeypatch, conn):
    s = SCENARIOS["S02"]  # low, oil_pressure_dip
    window = {"vehicle_id": s["vehicle_id"], "start_time": s["start_time"].isoformat(), "end_time": s["end_time"].isoformat()}
    _script(monkeypatch, [
        _FakeResponse(calls=[_FakeCall("query_telemetry", window)]),
        _FakeResponse(calls=[_FakeCall("compute_severity", window)]),
        _FakeResponse(text="DIAGNOSIS: brief oil pressure dip.\nSEVERITY: low\nSIGNALS: oil_pressure_bar\nRECOMMENDED_ACTION: monitor."),
    ])

    incident = orchestrator.diagnose(s["vehicle_id"], s["start_time"], s["end_time"], conn=conn)

    assert incident["severity"] == "low"
    assert incident["status"] == "auto_closed"
    assert incident["diagnosis"].startswith("DIAGNOSIS:")
    tools_called = [entry["tool"] for entry in incident["tool_call_log"]]
    assert tools_called == ["query_telemetry", "compute_severity"]


def test_diagnose_high_severity_sets_pending_approval(monkeypatch, conn):
    s = SCENARIOS["S13"]  # high, critical_oil_pressure
    window = {"vehicle_id": s["vehicle_id"], "start_time": s["start_time"].isoformat(), "end_time": s["end_time"].isoformat()}
    _script(monkeypatch, [
        _FakeResponse(calls=[_FakeCall("compute_severity", window)]),
        _FakeResponse(text="DIAGNOSIS: critical oil pressure collapse.\nSEVERITY: high\nSIGNALS: oil_pressure_bar\nRECOMMENDED_ACTION: pull vehicle from service immediately."),
    ])

    incident = orchestrator.diagnose(s["vehicle_id"], s["start_time"], s["end_time"], conn=conn)

    assert incident["severity"] == "high"
    assert incident["status"] == "pending_approval"


def test_diagnose_forces_compute_severity_if_model_never_calls_it(monkeypatch, conn):
    """If the model ignores the system prompt's instruction to always call
    compute_severity, the orchestrator must not persist an incident with no
    deterministic severity behind it — it falls back to computing it itself.
    """
    s = SCENARIOS["S05"]  # low, isolated_harsh_accel
    window = {"vehicle_id": s["vehicle_id"], "start_time": s["start_time"].isoformat(), "end_time": s["end_time"].isoformat()}
    _script(monkeypatch, [
        _FakeResponse(calls=[_FakeCall("query_telemetry", window)]),
        _FakeResponse(text="DIAGNOSIS: looked at the data.\nSEVERITY: unknown\nSIGNALS: none\nRECOMMENDED_ACTION: none."),
    ])

    incident = orchestrator.diagnose(s["vehicle_id"], s["start_time"], s["end_time"], conn=conn)

    assert incident["severity"] == "low"  # the real, forced compute_severity result — not "unknown"
    forced_entries = [e for e in incident["tool_call_log"] if e.get("forced")]
    assert len(forced_entries) == 1
    assert forced_entries[0]["tool"] == "compute_severity"


def test_diagnose_handles_unknown_tool_name_gracefully(monkeypatch, conn):
    s = SCENARIOS["S04"]
    window = {"vehicle_id": s["vehicle_id"], "start_time": s["start_time"].isoformat(), "end_time": s["end_time"].isoformat()}
    _script(monkeypatch, [
        _FakeResponse(calls=[_FakeCall("run_diagnostics_v2", window)]),  # hallucinated tool name
        _FakeResponse(calls=[_FakeCall("compute_severity", window)]),
        _FakeResponse(text="DIAGNOSIS: fuel blip.\nSEVERITY: low\nSIGNALS: fuel_rate_lh\nRECOMMENDED_ACTION: monitor."),
    ])

    incident = orchestrator.diagnose(s["vehicle_id"], s["start_time"], s["end_time"], conn=conn)

    assert incident["severity"] == "low"
    first_call = incident["tool_call_log"][0]
    assert first_call["tool"] == "run_diagnostics_v2"
    assert "error" in first_call["result"]


# --- incidents_db approve/reject round trip ---------------------------------

def test_approve_incident_only_affects_pending_approval(conn):
    s = SCENARIOS["S14"]
    incident = insert_incident(
        conn=conn, vehicle_id=s["vehicle_id"], window_start=s["start_time"], window_end=s["end_time"],
        severity="high", signals=["battery_v"], reasoning=["test"], diagnosis="test",
        tool_call_log=[], status="pending_approval",
    )
    approved = approve_incident(conn, incident["id"])
    assert approved["status"] == "approved"
    assert approved["resolved_at"] is not None

    # Approving again (already resolved) is a no-op, not a silent re-approve.
    again = approve_incident(conn, incident["id"])
    assert again is None

    fetched = get_incident(conn, incident["id"])
    assert fetched["status"] == "approved"


def test_reject_incident(conn):
    s = SCENARIOS["S15"]
    incident = insert_incident(
        conn=conn, vehicle_id=s["vehicle_id"], window_start=s["start_time"], window_end=s["end_time"],
        severity="high", signals=["engine_temp_c"], reasoning=["test"], diagnosis="test",
        tool_call_log=[], status="pending_approval",
    )
    rejected = reject_incident(conn, incident["id"])
    assert rejected["status"] == "rejected"
