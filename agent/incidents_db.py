"""Persistence for the incidents table — the human-approval gate. High-
severity incidents land in 'pending_approval'; a human resolves them via
approve_incident/reject_incident (POST /incidents/{id}/approve|reject in
app/main.py call these directly). Everything else is 'auto_closed'
immediately since only 'high' severity triggers the gate.
"""
import psycopg2.extras


def insert_incident(
    conn,
    vehicle_id: str,
    window_start,
    window_end,
    severity: str,
    signals: list,
    reasoning: list,
    diagnosis: str,
    tool_call_log: list,
    status: str,
) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incidents
                (vehicle_id, window_start, window_end, severity, signals,
                 reasoning, diagnosis, tool_call_log, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                vehicle_id, window_start, window_end, severity, signals,
                reasoning, diagnosis, psycopg2.extras.Json(tool_call_log), status,
            ),
        )
        (incident_id,) = cur.fetchone()
    conn.commit()
    return get_incident(conn, incident_id)


def get_incident(conn, incident_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, vehicle_id, window_start, window_end, severity, signals,
                   reasoning, diagnosis, tool_call_log, status, created_at, resolved_at
            FROM incidents WHERE id = %s
            """,
            (incident_id,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def _row_to_dict(row) -> dict:
    (id_, vehicle_id, window_start, window_end, severity, signals, reasoning,
     diagnosis, tool_call_log, status, created_at, resolved_at) = row
    return {
        "id": id_,
        "vehicle_id": vehicle_id,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "severity": severity,
        "signals": signals,
        "reasoning": reasoning,
        "diagnosis": diagnosis,
        "tool_call_log": tool_call_log,
        "status": status,
        "created_at": created_at.isoformat(),
        "resolved_at": resolved_at.isoformat() if resolved_at else None,
    }


def _set_status_if_pending(conn, incident_id: int, status: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE incidents SET status = %s, resolved_at = now()
            WHERE id = %s AND status = 'pending_approval'
            RETURNING id
            """,
            (status, incident_id),
        )
        row = cur.fetchone()
    conn.commit()
    return get_incident(conn, incident_id) if row else None


def approve_incident(conn, incident_id: int) -> dict | None:
    return _set_status_if_pending(conn, incident_id, "approved")


def reject_incident(conn, incident_id: int) -> dict | None:
    return _set_status_if_pending(conn, incident_id, "rejected")
