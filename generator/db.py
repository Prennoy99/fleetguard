"""Postgres connection + bulk loaders. Reused by later milestones' query
tools, not just the generator, so it lives at this shared path rather than
inside generate.py.
"""
import os

import psycopg2
import psycopg2.extras

TELEMETRY_COLUMNS = [
    "vehicle_id", "event_time", "speed_kmh", "rpm", "gear", "throttle_pct",
    "brake_pct", "fuel_level_pct", "fuel_rate_lh", "engine_temp_c",
    "oil_pressure_bar", "battery_v", "latitude", "longitude", "altitude_m",
    "hard_brake", "harsh_accel", "lane_departure",
]

SCENARIO_COLUMNS = [
    "scenario_id", "vehicle_id", "start_time", "end_time", "anomaly_type",
    "severity", "signals", "description",
]


def get_connection():
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://fleetguard:fleetguard@localhost:5432/fleetguard",
    )
    return psycopg2.connect(dsn)


def apply_schema(conn, schema_path: str):
    with open(schema_path) as f:
        ddl = f.read()
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


def clear_tables(conn):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE telemetry_raw, anomaly_scenarios RESTART IDENTITY")
    conn.commit()


def load_telemetry_rows(conn, rows):
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO telemetry_raw ({', '.join(TELEMETRY_COLUMNS)}) VALUES %s "
            f"ON CONFLICT (vehicle_id, event_time) DO NOTHING",
            rows,
        )
    conn.commit()


def load_scenario_rows(conn, rows):
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO anomaly_scenarios ({', '.join(SCENARIO_COLUMNS)}) VALUES %s "
            f"ON CONFLICT (scenario_id) DO NOTHING",
            rows,
        )
    conn.commit()
