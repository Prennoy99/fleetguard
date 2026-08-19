"""Pydantic request/response models for the FastAPI service."""
from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class DiagnoseRequest(BaseModel):
    vehicle_id: str
    start_time: datetime
    end_time: datetime


class IncidentResponse(BaseModel):
    id: int
    vehicle_id: str
    window_start: str
    window_end: str
    severity: str
    signals: list[str]
    reasoning: list[str]
    diagnosis: str
    tool_call_log: list[dict]
    status: str
    created_at: str
    resolved_at: str | None
