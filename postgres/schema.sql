-- FleetGuard schema. Two tables: telemetry_raw (the synthetic sensor history)
-- and anomaly_scenarios (the labeled ground truth the M4 eval harness checks
-- agent diagnoses against). Field set/units on telemetry_raw match fleetpulse's
-- telemetry_event.schema.json (see ../schema/telemetry_event.schema.json).

CREATE TABLE IF NOT EXISTS telemetry_raw (
    id               BIGSERIAL PRIMARY KEY,
    vehicle_id       TEXT        NOT NULL,
    event_time       TIMESTAMPTZ NOT NULL,
    speed_kmh        DOUBLE PRECISION NOT NULL,
    rpm              INTEGER NOT NULL,
    gear             SMALLINT NOT NULL CHECK (gear BETWEEN 1 AND 6),
    throttle_pct     DOUBLE PRECISION NOT NULL,
    brake_pct        DOUBLE PRECISION NOT NULL,
    fuel_level_pct   DOUBLE PRECISION NOT NULL,
    fuel_rate_lh     DOUBLE PRECISION NOT NULL,
    engine_temp_c    DOUBLE PRECISION NOT NULL,
    oil_pressure_bar DOUBLE PRECISION NOT NULL,
    battery_v        DOUBLE PRECISION NOT NULL,
    latitude         DOUBLE PRECISION NOT NULL,
    longitude        DOUBLE PRECISION NOT NULL,
    altitude_m       DOUBLE PRECISION NOT NULL,
    hard_brake       BOOLEAN NOT NULL,
    harsh_accel      BOOLEAN NOT NULL,
    lane_departure   BOOLEAN NOT NULL,
    UNIQUE (vehicle_id, event_time)
);

CREATE INDEX IF NOT EXISTS idx_telemetry_vehicle_time
    ON telemetry_raw (vehicle_id, event_time);

-- Ground truth for the evaluation harness. One row per injected anomaly
-- scenario: the window it occupies, which signal(s) it involves, and the
-- severity tier the agent's compute_severity call should land on for that
-- window.
CREATE TABLE IF NOT EXISTS anomaly_scenarios (
    scenario_id    TEXT PRIMARY KEY,
    vehicle_id     TEXT        NOT NULL,
    start_time     TIMESTAMPTZ NOT NULL,
    end_time       TIMESTAMPTZ NOT NULL,
    anomaly_type   TEXT        NOT NULL,
    severity       TEXT        NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    signals        TEXT[]      NOT NULL,
    description    TEXT        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scenarios_vehicle
    ON anomaly_scenarios (vehicle_id);

-- One row per agent diagnosis run. High-severity incidents land in
-- 'pending_approval' and require a human POST /incidents/{id}/approve or
-- /reject before they're considered closed; low/medium/none severity
-- incidents are auto-closed since only high triggers the gate.
CREATE TABLE IF NOT EXISTS incidents (
    id               BIGSERIAL PRIMARY KEY,
    vehicle_id       TEXT        NOT NULL,
    window_start     TIMESTAMPTZ NOT NULL,
    window_end       TIMESTAMPTZ NOT NULL,
    severity         TEXT        NOT NULL CHECK (severity IN ('none', 'low', 'medium', 'high')),
    signals          TEXT[]      NOT NULL,
    reasoning        TEXT[]      NOT NULL,
    diagnosis        TEXT        NOT NULL,
    tool_call_log    JSONB       NOT NULL,
    status           TEXT        NOT NULL DEFAULT 'auto_closed'
                         CHECK (status IN ('auto_closed', 'pending_approval', 'approved', 'rejected')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_incidents_vehicle
    ON incidents (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_incidents_status
    ON incidents (status);
