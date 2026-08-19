"""LLM-facing wrappers around the M2 tools (tools/query_telemetry.py,
tools/fault_classifier.py, tools/severity.py).

Gemini's function-calling needs simple, self-contained argument shapes — a
plain (vehicle_id, start_time, end_time) string triple for every tool, not
the nested findings/baseline dicts M2's functions pass between each other in
Python. So each wrapper here re-runs whatever upstream M2 steps it needs
internally (query + baseline are cheap: at most a few hundred rows) rather
than asking the model to round-trip complex JSON structures as arguments —
the model's real job is deciding *which* tool to call and when, not
constructing intermediate data.

`conn` is accepted for dependency injection in tests but is never part of
the JSON schema declared to Gemini (see tool_specs.py) — the orchestrator
supplies it directly when dispatching a tool call.
"""
from datetime import datetime, timezone

from tools.fault_classifier import compute_baseline_stats, run_fault_classifier as _run_fault_classifier
from tools.query_telemetry import query_telemetry as _query_telemetry
from tools.severity import compute_severity as _compute_severity


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def query_telemetry(vehicle_id: str, start_time: str, end_time: str, conn=None) -> dict:
    start, end = _parse(start_time), _parse(end_time)
    readings = _query_telemetry(vehicle_id, start, end, conn=conn)
    for r in readings:
        r["event_time"] = r["event_time"].isoformat()
    return {"vehicle_id": vehicle_id, "count": len(readings), "readings": readings}


def run_fault_classifier(vehicle_id: str, start_time: str, end_time: str, conn=None) -> dict:
    start, end = _parse(start_time), _parse(end_time)
    readings = _query_telemetry(vehicle_id, start, end, conn=conn)
    baseline = compute_baseline_stats(vehicle_id, start, conn=conn)
    return _run_fault_classifier(readings, baseline)


def compute_severity(vehicle_id: str, start_time: str, end_time: str, conn=None) -> dict:
    start, end = _parse(start_time), _parse(end_time)
    readings = _query_telemetry(vehicle_id, start, end, conn=conn)
    baseline = compute_baseline_stats(vehicle_id, start, conn=conn)
    findings = _run_fault_classifier(readings, baseline)
    return _compute_severity(findings)
