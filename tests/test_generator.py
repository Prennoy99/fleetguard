import json

import jsonschema
import numpy as np

from generator.config import NUM_VEHICLES, SAMPLES_PER_DAY, NUM_DAYS
from generator.fleet_sim import event_times, generate_vehicle_baseline
from generator.generate import build_fleet, rows_for_vehicle, write_scenarios_json
from generator.scenarios import apply_scenarios_for_vehicle, build_scenarios


def test_baseline_is_deterministic():
    a = generate_vehicle_baseline(0)
    b = generate_vehicle_baseline(0)
    for key in a:
        assert np.array_equal(a[key], b[key])


def test_different_vehicles_differ():
    a = generate_vehicle_baseline(0)
    b = generate_vehicle_baseline(1)
    assert not np.array_equal(a["speed_kmh"], b["speed_kmh"])


def test_baseline_length_matches_config():
    arrays = generate_vehicle_baseline(0)
    expected = NUM_DAYS * SAMPLES_PER_DAY
    for key, values in arrays.items():
        assert len(values) == expected, key


def test_signal_ranges_are_physically_sane():
    arrays = generate_vehicle_baseline(0)
    assert (arrays["speed_kmh"] >= 0).all() and (arrays["speed_kmh"] <= 140).all()
    assert (arrays["gear"] >= 1).all() and (arrays["gear"] <= 6).all()
    assert (arrays["fuel_level_pct"] >= 0).all() and (arrays["fuel_level_pct"] <= 100).all()
    assert (arrays["latitude"] >= -90).all() and (arrays["latitude"] <= 90).all()
    assert (arrays["longitude"] >= -180).all() and (arrays["longitude"] <= 180).all()


def test_build_fleet_row_count():
    times, fleet = build_fleet()
    assert len(fleet) == NUM_VEHICLES
    assert len(times) == NUM_DAYS * SAMPLES_PER_DAY


def test_build_fleet_is_deterministic_across_runs():
    times1, fleet1 = build_fleet()
    times2, fleet2 = build_fleet()
    assert times1 == times2
    for vid in fleet1:
        for key in fleet1[vid]:
            assert np.array_equal(fleet1[vid][key], fleet2[vid][key])


def test_scenarios_count_and_severity_split():
    scenarios = build_scenarios()
    assert len(scenarios) == 18
    counts = {"low": 0, "medium": 0, "high": 0}
    for s in scenarios:
        counts[s["severity"]] += 1
    assert counts == {"low": 6, "medium": 6, "high": 6}


def test_scenario_ids_are_unique():
    scenarios = build_scenarios()
    ids = [s["scenario_id"] for s in scenarios]
    assert len(ids) == len(set(ids))


def test_scenario_windows_are_within_range():
    times, fleet = build_fleet()
    total_samples = len(times)
    for s in build_scenarios():
        assert 0 <= s["start_index"] < total_samples
        assert 0 < s["end_index"] <= total_samples
        assert s["start_index"] < s["end_index"]


def test_high_severity_scenarios_actually_breach_critical_thresholds():
    """Ground-truth sanity check: every 'high' scenario should push its
    signal(s) into the range compute_severity (M2) is expected to call
    high-severity, so the eval harness (M4) has something real to check
    against.
    """
    times, fleet = build_fleet()
    for s in build_scenarios():
        if s["severity"] != "high":
            continue
        arrays = fleet[s["vehicle_id"]]
        window = slice(s["start_index"], s["end_index"])
        if "oil_pressure_bar" in s["signals"]:
            assert (arrays["oil_pressure_bar"][window] < 1.0).all(), s["scenario_id"]
        if "battery_v" in s["signals"] and "temp" not in s["anomaly_type"]:
            assert (arrays["battery_v"][window] < 10.5).all(), s["scenario_id"]
        if "engine_temp_c" in s["signals"]:
            assert (arrays["engine_temp_c"][window] > 115).all(), s["scenario_id"]


def test_rows_for_vehicle_matches_schema():
    with open("schema/telemetry_event.schema.json") as f:
        schema = json.load(f)

    times, fleet = build_fleet()
    vehicle_id = "veh-001"
    rows = list(rows_for_vehicle(vehicle_id, times, fleet[vehicle_id]))
    columns = [
        "vehicle_id", "event_time", "speed_kmh", "rpm", "gear", "throttle_pct",
        "brake_pct", "fuel_level_pct", "fuel_rate_lh", "engine_temp_c",
        "oil_pressure_bar", "battery_v", "latitude", "longitude", "altitude_m",
        "hard_brake", "harsh_accel", "lane_departure",
    ]
    for row in rows[:5] + rows[-5:]:
        event = dict(zip(columns, row))
        event["event_time"] = event["event_time"].isoformat()
        jsonschema.validate(event, schema)


def test_write_scenarios_json_matches_build_scenarios(tmp_path, monkeypatch):
    import generator.generate as gen

    out_path = tmp_path / "scenarios.json"
    monkeypatch.setattr(gen, "SCENARIOS_JSON_PATH", str(out_path))

    scenarios = build_scenarios()
    payload = write_scenarios_json(scenarios)

    assert out_path.exists()
    with open(out_path) as f:
        on_disk = json.load(f)
    assert on_disk == payload
    assert len(payload) == 18
