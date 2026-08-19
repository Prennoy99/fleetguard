"""Gemini function-calling declarations for the M2 tools, and the name-to-
Python-function dispatch table the orchestrator uses to actually execute a
call the model decides to make.
"""
from google.genai import types

from agent import tool_wrappers


def _window_properties() -> dict:
    return {
        "vehicle_id": types.Schema(type=types.Type.STRING, description="Vehicle identifier, e.g. 'veh-013'."),
        "start_time": types.Schema(type=types.Type.STRING, description="Window start, ISO 8601 UTC timestamp."),
        "end_time": types.Schema(type=types.Type.STRING, description="Window end, ISO 8601 UTC timestamp (inclusive)."),
    }


def _window_schema(description: str) -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties=_window_properties(),
        required=["vehicle_id", "start_time", "end_time"],
        description=description,
    )


FLEET_TOOL = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="query_telemetry",
        description=(
            "Fetch the raw telemetry readings for one vehicle within a time window "
            "(speed, rpm, engine temp, oil pressure, battery voltage, fuel rate, GPS, "
            "and brake/accel/lane-departure event flags). Use this to look at what the "
            "vehicle was actually doing before drawing a conclusion."
        ),
        parameters=_window_schema("The vehicle and time window to fetch telemetry for."),
    ),
    types.FunctionDeclaration(
        name="run_fault_classifier",
        description=(
            "Run the statistical fault detector for one vehicle/window. Compares each "
            "continuous signal (engine_temp_c, oil_pressure_bar, battery_v, fuel_rate_lh) "
            "against the vehicle's own recent baseline and flags readings that deviate "
            "beyond a threshold, plus counts hard_brake/harsh_accel events. Returns the "
            "per-signal findings compute_severity is based on."
        ),
        parameters=_window_schema("The vehicle and time window to run the classifier on."),
    ),
    types.FunctionDeclaration(
        name="compute_severity",
        description=(
            "Compute the authoritative incident severity (none/low/medium/high) for one "
            "vehicle/window, per the project's severity taxonomy. This is the deterministic "
            "result that decides whether the human-approval gate applies (only 'high' does) "
            "— call this once you're ready to finalize the diagnosis, and treat its severity "
            "as authoritative rather than restating your own judgment in the final report."
        ),
        parameters=_window_schema("The vehicle and time window to compute severity for."),
    ),
])

DISPATCH = {
    "query_telemetry": tool_wrappers.query_telemetry,
    "run_fault_classifier": tool_wrappers.run_fault_classifier,
    "compute_severity": tool_wrappers.compute_severity,
}
