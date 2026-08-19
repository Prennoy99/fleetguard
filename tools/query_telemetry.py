"""M2 diagnostic tool: query_telemetry(vehicle_id, window).

Pure data access — fetches raw telemetry rows for one vehicle within a time
window from Postgres. No interpretation happens here; that's fault_classifier
and severity's job. Kept separate so the agent (M3) can call it standalone.
"""
from datetime import datetime

from generator.db import TELEMETRY_COLUMNS, get_connection


def query_telemetry(
    vehicle_id: str,
    start_time: datetime,
    end_time: datetime,
    conn=None,
) -> list[dict]:
    """Return telemetry_raw rows for `vehicle_id` in [start_time, end_time],
    ordered by event_time, one dict per row keyed by column name.
    """
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {", ".join(TELEMETRY_COLUMNS)}
                FROM telemetry_raw
                WHERE vehicle_id = %s AND event_time BETWEEN %s AND %s
                ORDER BY event_time
                """,
                (vehicle_id, start_time, end_time),
            )
            rows = cur.fetchall()
    finally:
        if owns_conn:
            conn.close()
    return [dict(zip(TELEMETRY_COLUMNS, row)) for row in rows]
