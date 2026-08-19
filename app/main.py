"""FastAPI service. POST /diagnose is the only way a diagnosis run starts —
no autonomous fleet-wide sweep. High-severity incidents land in
pending_approval and are unblocked via POST /incidents/{id}/approve or
/reject, demoed via curl / this app's own /docs Swagger page.
"""
from fastapi import Depends, FastAPI, HTTPException

from agent.incidents_db import approve_incident, get_incident, reject_incident
from agent.orchestrator import diagnose
from app.auth import require_api_key
from app.schemas import DiagnoseRequest, HealthResponse, IncidentResponse
from generator.db import get_connection

app = FastAPI(title="FleetGuard", version="0.1.0")


def _conn():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@app.get("/health", response_model=HealthResponse)
def health() -> dict:
    return {"status": "ok"}


@app.post("/diagnose", response_model=IncidentResponse, dependencies=[Depends(require_api_key)])
def run_diagnose(req: DiagnoseRequest, conn=Depends(_conn)) -> dict:
    return diagnose(req.vehicle_id, req.start_time, req.end_time, conn=conn)


@app.get("/incidents/{incident_id}", response_model=IncidentResponse, dependencies=[Depends(require_api_key)])
def read_incident(incident_id: int, conn=Depends(_conn)) -> dict:
    incident = get_incident(conn, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return incident


@app.post("/incidents/{incident_id}/approve", response_model=IncidentResponse, dependencies=[Depends(require_api_key)])
def approve(incident_id: int, conn=Depends(_conn)) -> dict:
    incident = approve_incident(conn, incident_id)
    if incident is None:
        raise HTTPException(status_code=409, detail="Incident not found or not pending approval.")
    return incident


@app.post("/incidents/{incident_id}/reject", response_model=IncidentResponse, dependencies=[Depends(require_api_key)])
def reject(incident_id: int, conn=Depends(_conn)) -> dict:
    incident = reject_incident(conn, incident_id)
    if incident is None:
        raise HTTPException(status_code=409, detail="Incident not found or not pending approval.")
    return incident
