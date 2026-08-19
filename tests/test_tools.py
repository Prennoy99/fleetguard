"""Unit tests: query_telemetry, run_fault_classifier, compute_severity,
each tested in isolation, plus an end-to-end check that chaining all three
against the real seeded DB reproduces every one of the 18 labeled scenarios'
ground-truth severity. Requires the local Postgres from docker-compose.yml
to be up and seeded (see generator/generate.py).
"""
from datetime import timedelta

import pytest

from generator.db import get_connection
from generator.scenarios import build_scenarios
from tools.query_telemetry import query_telemetry
from tools.fault_classifier import compute_baseline_stats, run_fault_classifier
from tools.severity import compute_severity

SCENARIOS = {s["scenario_id"]: s for s in build_scenarios()}


@pytest.fixture(scope="module")
def conn():
    connection = get_connection()
    yield connection
    connection.close()


def _diagnose(vehicle_id, start_time, end_time, conn):
    readings = query_telemetry(vehicle_id, start_time, end_time, conn=conn)
    baseline = compute_baseline_stats(vehicle_id, start_time, conn=conn)
    findings = run_fault_classifier(readings, baseline)
    return compute_severity(findings), readings, findings


# --- query_telemetry -------------------------------------------------------

def test_query_telemetry_returns_expected_row_count(conn):
    s = SCENARIOS["S13"]
    rows = query_telemetry(s["vehicle_id"], s["start_time"], s["end_time"], conn=conn)
    assert len(rows) == 12
    assert all(r["vehicle_id"] == "veh-013" for r in rows)


def test_query_telemetry_rows_are_time_ordered(conn):
    s = SCENARIOS["S18"]
    rows = query_telemetry(s["vehicle_id"], s["start_time"], s["end_time"], conn=conn)
    times = [r["event_time"] for r in rows]
    assert times == sorted(times)


def test_query_telemetry_empty_outside_history(conn):
    far_future = SCENARIOS["S01"]["start_time"] + timedelta(days=3650)
    rows = query_telemetry("veh-001", far_future, far_future + timedelta(hours=1), conn=conn)
    assert rows == []


# --- compute_baseline_stats / run_fault_classifier --------------------------

def test_baseline_stats_reflect_normal_driving_oil_pressure(conn):
    s = SCENARIOS["S13"]  # critical_oil_pressure — baseline should look normal, not critical
    baseline = compute_baseline_stats(s["vehicle_id"], s["start_time"], conn=conn)
    assert baseline["oil_pressure_bar"]["n"] > 0
    assert 2.5 < baseline["oil_pressure_bar"]["mean"] < 4.0
    assert baseline["oil_pressure_bar"]["std"] < 1.0


def test_fault_classifier_flags_sustained_critical_oil_dip(conn):
    s = SCENARIOS["S13"]
    readings = query_telemetry(s["vehicle_id"], s["start_time"], s["end_time"], conn=conn)
    baseline = compute_baseline_stats(s["vehicle_id"], s["start_time"], conn=conn)
    findings = run_fault_classifier(readings, baseline)
    oil = findings["continuous"]["oil_pressure_bar"]
    assert all(oil["critical_flags"])
    assert oil["max_consecutive_critical"] == 12


def test_fault_classifier_counts_event_signals(conn):
    s = SCENARIOS["S16"]  # hard_brake_cluster
    readings = query_telemetry(s["vehicle_id"], s["start_time"], s["end_time"], conn=conn)
    baseline = compute_baseline_stats(s["vehicle_id"], s["start_time"], conn=conn)
    findings = run_fault_classifier(readings, baseline)
    assert findings["events"]["hard_brake"]["count"] >= 6
    assert findings["events"]["hard_brake"]["n"] == 12


# --- compute_severity --------------------------------------------------------

def test_compute_severity_high_requires_no_findings_returns_none():
    empty_findings = {
        "continuous": {
            sig: {"flags": [False], "critical_flags": [False], "max_consecutive_flagged": 0,
                  "max_consecutive_critical": 0, "monotonic_drift": False,
                  "z_scores": [0.0], "values": [0.0]}
            for sig in ["engine_temp_c", "oil_pressure_bar", "battery_v", "fuel_rate_lh"]
        },
        "events": {"hard_brake": {"count": 0, "n": 1}, "harsh_accel": {"count": 0, "n": 1}},
    }
    result = compute_severity(empty_findings)
    assert result["severity"] == "none"


def test_compute_severity_single_critical_reading_is_not_high():
    """A lone critical-looking sample (max_consecutive_critical == 1) must not
    be classified high — high severity requires a sustained/breakdown-risk
    pattern, not one noisy reading (this is exactly S01's real shape: a single
    117C sample, labeled low)."""
    findings = {
        "continuous": {
            "engine_temp_c": {"flags": [True], "critical_flags": [True],
                               "max_consecutive_flagged": 1, "max_consecutive_critical": 1,
                               "monotonic_drift": False, "z_scores": [9.0], "values": [117.3]},
            "oil_pressure_bar": {"flags": [False], "critical_flags": [False],
                                  "max_consecutive_flagged": 0, "max_consecutive_critical": 0,
                                  "monotonic_drift": False, "z_scores": [0.0], "values": [3.2]},
            "battery_v": {"flags": [False], "critical_flags": [False],
                          "max_consecutive_flagged": 0, "max_consecutive_critical": 0,
                          "monotonic_drift": False, "z_scores": [0.0], "values": [13.5]},
            "fuel_rate_lh": {"flags": [False], "critical_flags": [False],
                              "max_consecutive_flagged": 0, "max_consecutive_critical": 0,
                              "monotonic_drift": False, "z_scores": [0.0], "values": [3.0]},
        },
        "events": {"hard_brake": {"count": 0, "n": 1}, "harsh_accel": {"count": 0, "n": 1}},
    }
    result = compute_severity(findings)
    assert result["severity"] == "low"
    assert result["signals"] == ["engine_temp_c"]


# --- end-to-end against the real seeded DB: all 18 labeled scenarios -------

@pytest.mark.parametrize("scenario_id", sorted(SCENARIOS.keys()))
def test_all_labeled_scenarios_match_ground_truth_severity(scenario_id, conn):
    s = SCENARIOS[scenario_id]
    result, _, _ = _diagnose(s["vehicle_id"], s["start_time"], s["end_time"], conn)
    assert result["severity"] == s["severity"], (
        f"{scenario_id} ({s['anomaly_type']}): expected {s['severity']}, "
        f"got {result['severity']} — signals {result['signals']}, reasons {result['reasoning']}"
    )


def test_clean_vehicle_normal_window_is_not_high_or_medium(conn):
    """veh-019..veh-025 have no injected scenarios. A random driving-hours
    window on one of them should not read as a developing or critical fault.
    """
    s13 = SCENARIOS["S13"]
    start = s13["start_time"].replace(day=25)  # same hour-of-day, later day, clean vehicle
    end = start + timedelta(minutes=55)
    result, readings, _ = _diagnose("veh-019", start, end, conn)
    assert len(readings) > 0
    assert result["severity"] in ("none", "low")
