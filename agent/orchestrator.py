"""Agent orchestration loop: a plain Python loop over Gemini's function-
calling, not a graph framework — the sequence is mostly linear with one
conditional branch, so a state-machine framework wasn't worth the added
dependency.

diagnose() drives the model through: observe -> decide which tool(s) to
call -> diagnose -> assess severity -> if high, pause for human approval ->
structured incident report. The model picks which of the three tools to
call and in what order; the actual severity number that decides the
approval gate always comes from the deterministic compute_severity tool
result, never from parsing the model's prose — the fault detector itself is
a statistical/threshold-based classifier, not an LLM, so the diagnosis stays
explainable and reproducible.
"""
from datetime import datetime

from google.genai import types

from agent import gemini_client, tool_specs
from agent.incidents_db import insert_incident
from agent.prompts import SYSTEM_INSTRUCTION
from generator.db import get_connection

MAX_TOOL_ITERATIONS = 6


def diagnose(vehicle_id: str, start_time: datetime, end_time: datetime, conn=None) -> dict:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=(
                    f"Investigate vehicle {vehicle_id} for the window "
                    f"{start_time.isoformat()} to {end_time.isoformat()}."
                ))],
            )
        ]

        tool_call_log = []
        severity_result = None
        final_text = ""

        for _ in range(MAX_TOOL_ITERATIONS):
            response = gemini_client.generate_content(
                contents=contents,
                tools=[tool_specs.FLEET_TOOL],
                system_instruction=SYSTEM_INSTRUCTION,
            )
            calls = response.function_calls
            if not calls:
                final_text = response.text or ""
                break

            contents.append(response.candidates[0].content)
            response_parts = []
            for call in calls:
                args = dict(call.args or {})
                result = _dispatch(call.name, args, conn)
                if call.name == "compute_severity" and "error" not in result:
                    severity_result = result
                tool_call_log.append({"tool": call.name, "args": args, "result": result})
                response_parts.append(types.Part.from_function_response(name=call.name, response=result))
            contents.append(types.Content(role="user", parts=response_parts))
        else:
            final_text = response.text or ""

        if severity_result is None:
            # The model should always call compute_severity per the system
            # prompt, but a report without a deterministic severity behind it
            # isn't trustworthy — fall back to computing it directly rather
            # than persisting an incident with no real severity backing it.
            args = {
                "vehicle_id": vehicle_id,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            }
            severity_result = _dispatch("compute_severity", args, conn)
            tool_call_log.append({"tool": "compute_severity", "args": args, "result": severity_result, "forced": True})

        severity = severity_result["severity"]
        status = "pending_approval" if severity == "high" else "auto_closed"

        return insert_incident(
            conn=conn,
            vehicle_id=vehicle_id,
            window_start=start_time,
            window_end=end_time,
            severity=severity,
            signals=severity_result["signals"],
            reasoning=severity_result["reasoning"],
            diagnosis=final_text.strip(),
            tool_call_log=tool_call_log,
            status=status,
        )
    finally:
        if owns_conn:
            conn.close()


def _dispatch(name: str, args: dict, conn) -> dict:
    func = tool_specs.DISPATCH.get(name)
    if func is None:
        return {"error": f"unknown tool '{name}'"}
    try:
        return func(conn=conn, **args)
    except Exception as e:
        return {"error": str(e)}
