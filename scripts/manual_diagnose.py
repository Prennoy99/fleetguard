"""M3 manual validation: run the real agent loop (live Gemini call, not the
stubbed tests in tests/test_orchestrator.py) against one labeled scenario and
print what it decided. This is the "hand-scripted end-to-end scenario,
verified against the expected outcome" M3's done-when criterion asks for.

Usage:
    python scripts/manual_diagnose.py [SCENARIO_ID]   # defaults to S13

Requires GEMINI_API_KEY set (via .env or the environment) and the local
Postgres from docker-compose.yml up and seeded.
"""
import json
import sys

from dotenv import load_dotenv

load_dotenv()

from agent.orchestrator import diagnose
from generator.scenarios import build_scenarios


def main():
    scenario_id = sys.argv[1] if len(sys.argv) > 1 else "S13"
    scenarios = {s["scenario_id"]: s for s in build_scenarios()}
    if scenario_id not in scenarios:
        print(f"Unknown scenario '{scenario_id}'. Options: {sorted(scenarios)}")
        sys.exit(1)
    s = scenarios[scenario_id]

    print(f"--- {scenario_id}: {s['anomaly_type']} (expected severity: {s['severity']}) ---")
    print(f"vehicle={s['vehicle_id']}  window={s['start_time']} .. {s['end_time']}\n")

    incident = diagnose(s["vehicle_id"], s["start_time"], s["end_time"])

    print("Tool calls made by the model:")
    for entry in incident["tool_call_log"]:
        forced = " (forced fallback, model skipped it)" if entry.get("forced") else ""
        print(f"  - {entry['tool']}{forced}")

    print("\nFinal incident report:")
    print(incident["diagnosis"])
    print(f"\nseverity   = {incident['severity']}  (expected: {s['severity']})")
    print(f"status     = {incident['status']}")
    print(f"signals    = {incident['signals']}")
    print(f"match      = {'YES' if incident['severity'] == s['severity'] else 'NO'}")
    print("\nFull incident record:")
    print(json.dumps(incident, indent=2, default=str))


if __name__ == "__main__":
    main()
