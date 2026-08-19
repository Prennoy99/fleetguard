"""Evaluation harness. Runs the real agent (agent.orchestrator.diagnose,
live Gemini calls) against all 18 labeled scenarios
(generator.scenarios.build_scenarios — the ground truth) and checks each
result against its label.

A scenario counts as diagnosed correctly when both hold:
  - severity matches the label exactly (the deterministic compute_severity
    result the orchestrator persists — never the model's own prose, same
    "don't trust the LLM for the gate decision" discipline as orchestrator.py)
  - the incident's signals overlap the label's expected signal set (i.e. the
    agent attributed the finding to a real cause, not just the right tier by
    chance)

Fails the build (nonzero exit) if the pass rate drops below --min-hit-rate
(default 0.8 — same bar and flag name used elsewhere in the portfolio).

Usage:
    python -m eval.evaluate [--min-hit-rate 0.8] [--scenario S13]

Requires GEMINI_API_KEY set and the local Postgres seeded (generator.generate).
Writes a full per-scenario report to eval/results.json — every number that
ends up in the README must come from an actual run of this file.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_PATH = os.path.join(REPO_ROOT, "eval", "results.json")

DEFAULT_MIN_HIT_RATE = 0.8


def run_eval(scenario_ids=None, sleep_between=0.0):
    from agent.orchestrator import diagnose
    from generator.db import get_connection
    from generator.scenarios import build_scenarios

    scenarios = build_scenarios()
    if scenario_ids:
        wanted = set(scenario_ids)
        scenarios = [s for s in scenarios if s["scenario_id"] in wanted]

    conn = get_connection()
    results = []
    try:
        for i, s in enumerate(scenarios):
            print(f"[{s['scenario_id']}] {s['anomaly_type']} (expected: {s['severity']}) ... ", end="", flush=True)
            incident = diagnose(s["vehicle_id"], s["start_time"], s["end_time"], conn=conn)

            severity_match = incident["severity"] == s["severity"]
            signals_match = bool(set(incident["signals"]) & set(s["signals"]))
            passed = severity_match and signals_match
            forced = any(entry.get("forced") for entry in incident["tool_call_log"])
            tool_order = [entry["tool"] for entry in incident["tool_call_log"]]

            print("PASS" if passed else "FAIL",
                  f"(got severity={incident['severity']}, signals={incident['signals']}"
                  f"{', forced-fallback' if forced else ''})")

            results.append({
                "scenario_id": s["scenario_id"],
                "anomaly_type": s["anomaly_type"],
                "expected_severity": s["severity"],
                "expected_signals": s["signals"],
                "got_severity": incident["severity"],
                "got_signals": incident["signals"],
                "got_status": incident["status"],
                "severity_match": severity_match,
                "signals_match": signals_match,
                "passed": passed,
                "forced_fallback": forced,
                "tool_call_order": tool_order,
                "incident_id": incident["id"],
            })

            if sleep_between and i < len(scenarios) - 1:
                time.sleep(sleep_between)
    finally:
        conn.close()

    return results


def summarize(results, min_hit_rate):
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    pass_rate = passed / total if total else 0.0
    forced_count = sum(1 for r in results if r["forced_fallback"])

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total_scenarios": total,
        "passed": passed,
        "pass_rate": pass_rate,
        "min_hit_rate": min_hit_rate,
        "gate_passed": pass_rate >= min_hit_rate,
        "forced_fallback_count": forced_count,
        "results": results,
    }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-hit-rate", type=float, default=DEFAULT_MIN_HIT_RATE,
                         help=f"Minimum fraction of scenarios that must pass (default {DEFAULT_MIN_HIT_RATE}).")
    parser.add_argument("--scenario", action="append", default=None,
                         help="Restrict to one or more scenario IDs (e.g. --scenario S13). Repeatable.")
    parser.add_argument("--sleep-between", type=float, default=0.0,
                         help="Seconds to sleep between scenarios, to stay clear of Gemini free-tier rate limits.")
    args = parser.parse_args()

    results = run_eval(scenario_ids=args.scenario, sleep_between=args.sleep_between)
    report = summarize(results, args.min_hit_rate)

    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{report['passed']}/{report['total_scenarios']} scenarios passed "
          f"({report['pass_rate']:.1%}, threshold {report['min_hit_rate']:.0%})")
    if report["forced_fallback_count"]:
        print(f"note: {report['forced_fallback_count']} scenario(s) needed the forced compute_severity "
              f"fallback (model skipped calling it) — severity was still correct, but this is a tool-"
              f"calling reliability signal worth watching.")
    print(f"Full report written to {os.path.relpath(RESULTS_PATH, REPO_ROOT)}")

    if not report["gate_passed"]:
        print("FAIL: pass rate below threshold", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
