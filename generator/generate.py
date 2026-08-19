"""Entry point: build the deterministic fleet + inject the 18 labeled
anomaly scenarios, then load everything into Postgres and snapshot the
ground truth to data/scenarios.json.

Usage:
    python -m generator.generate            # generate + load into Postgres
    python -m generator.generate --dry-run   # generate only, no DB required
"""
import argparse
import json
import os

import numpy as np

from generator.config import NUM_VEHICLES, SEED, VEHICLE_IDS
from generator.fleet_sim import event_times, generate_vehicle_baseline
from generator.scenarios import apply_scenarios_for_vehicle, build_scenarios

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_SQL_PATH = os.path.join(REPO_ROOT, "postgres", "schema.sql")
SCENARIOS_JSON_PATH = os.path.join(REPO_ROOT, "data", "scenarios.json")


def build_fleet():
    """Return (times, {vehicle_id: arrays_dict}) for the whole fleet, with
    scenarios already injected.
    """
    times = event_times()
    fleet = {}
    for vidx in range(NUM_VEHICLES):
        arrays = generate_vehicle_baseline(vidx)
        scenario_rng = np.random.default_rng(SEED + 10_000 + vidx)
        apply_scenarios_for_vehicle(vidx, arrays, scenario_rng)
        fleet[VEHICLE_IDS[vidx]] = arrays
    return times, fleet


def rows_for_vehicle(vehicle_id, times, arrays):
    n = len(times)
    for i in range(n):
        yield (
            vehicle_id,
            times[i],
            float(arrays["speed_kmh"][i]),
            int(arrays["rpm"][i]),
            int(arrays["gear"][i]),
            float(arrays["throttle_pct"][i]),
            float(arrays["brake_pct"][i]),
            float(arrays["fuel_level_pct"][i]),
            float(arrays["fuel_rate_lh"][i]),
            float(arrays["engine_temp_c"][i]),
            float(arrays["oil_pressure_bar"][i]),
            float(arrays["battery_v"][i]),
            float(arrays["latitude"][i]),
            float(arrays["longitude"][i]),
            float(arrays["altitude_m"][i]),
            bool(arrays["hard_brake"][i]),
            bool(arrays["harsh_accel"][i]),
            bool(arrays["lane_departure"][i]),
        )


def write_scenarios_json(scenarios):
    os.makedirs(os.path.dirname(SCENARIOS_JSON_PATH), exist_ok=True)
    payload = [
        {
            "scenario_id": s["scenario_id"],
            "vehicle_id": s["vehicle_id"],
            "start_time": s["start_time"].isoformat(),
            "end_time": s["end_time"].isoformat(),
            "anomaly_type": s["anomaly_type"],
            "severity": s["severity"],
            "signals": s["signals"],
            "description": s["description"],
        }
        for s in scenarios
    ]
    with open(SCENARIOS_JSON_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Generate only, skip Postgres")
    args = parser.parse_args()

    times, fleet = build_fleet()
    scenarios = build_scenarios()
    write_scenarios_json(scenarios)

    total_rows = len(times) * len(fleet)
    print(f"Generated {len(fleet)} vehicles x {len(times)} samples = {total_rows} telemetry rows")
    print(f"Generated {len(scenarios)} labeled anomaly scenarios "
          f"({sum(1 for s in scenarios if s['severity'] == 'low')} low / "
          f"{sum(1 for s in scenarios if s['severity'] == 'medium')} medium / "
          f"{sum(1 for s in scenarios if s['severity'] == 'high')} high)")

    if args.dry_run:
        print("--dry-run: skipping Postgres load")
        return

    from generator import db

    conn = db.get_connection()
    try:
        db.apply_schema(conn, SCHEMA_SQL_PATH)
        db.clear_tables(conn)

        for vehicle_id, arrays in fleet.items():
            rows = list(rows_for_vehicle(vehicle_id, times, arrays))
            db.load_telemetry_rows(conn, rows)

        scenario_rows = [
            (s["scenario_id"], s["vehicle_id"], s["start_time"], s["end_time"],
             s["anomaly_type"], s["severity"], s["signals"], s["description"])
            for s in scenarios
        ]
        db.load_scenario_rows(conn, scenario_rows)
        print("Loaded telemetry_raw and anomaly_scenarios into Postgres.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
