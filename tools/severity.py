"""Diagnostic tool: compute_severity(...) — implements the severity taxonomy
on top of run_fault_classifier's findings.

  low    - single-signal deviation, single reading, no sustained pattern.
  medium - sustained deviation (3+ consecutive readings) on one signal, OR
           two+ signals deviating in the same window (cross-signal), OR an
           elevated (but not dense) rate of hard_brake/harsh_accel events.
  high   - a critical absolute breach (near-zero oil pressure, battery
           collapse, severe overheating) sustained for 3+ consecutive
           readings, or a dense cluster of hard_brake/harsh_accel events.
           Only high triggers the human-approval gate.

A single-reading critical breach (e.g. one 117C sample) is deliberately
*not* high on its own — high severity is tied to sustained/breakdown risk,
not a single noisy sample, so the sustained-count check applies to critical
breaches too, not just the mild z-score ones.
"""
SUSTAINED_MIN = 3
EVENT_ELEVATED_COUNT = 2
EVENT_CLUSTER_COUNT = 6


def _sustained_reason(signal: str, info: dict) -> str:
    if info["max_consecutive_flagged"] >= SUSTAINED_MIN:
        return f"{signal} sustained deviation for {info['max_consecutive_flagged']} consecutive readings"
    return f"{signal} shows a consistent one-directional drift across the window"


def compute_severity(findings: dict) -> dict:
    continuous = findings["continuous"]
    events = findings["events"]

    critical_sustained = [
        signal for signal, info in continuous.items()
        if info["max_consecutive_critical"] >= SUSTAINED_MIN
    ]
    event_clusters = [
        signal for signal, info in events.items()
        if info["count"] >= EVENT_CLUSTER_COUNT
    ]
    if critical_sustained or event_clusters:
        reasons = [
            f"{s} breached its critical threshold for {continuous[s]['max_consecutive_critical']} "
            f"consecutive readings" for s in critical_sustained
        ] + [
            f"{s} cluster: {events[s]['count']}/{events[s]['n']} readings in window" for s in event_clusters
        ]
        return {"severity": "high", "signals": sorted(set(critical_sustained + event_clusters)), "reasoning": reasons}

    anomalous_continuous = [s for s, info in continuous.items() if any(info["flags"])]
    sustained_mild = [
        s for s, info in continuous.items()
        if info["max_consecutive_flagged"] >= SUSTAINED_MIN or info["monotonic_drift"]
    ]
    # Cross-signal requires each contributing signal to show more than one
    # flagged reading — a single coincidental flagged sample on an otherwise
    # unrelated signal (normal noise, ~a few percent of readings at 2 sigma)
    # isn't "two signals moving together", it's noise landing next to a real
    # single-signal anomaly (still correctly caught below as "low").
    cross_signal_contributors = [s for s, info in continuous.items() if sum(info["flags"]) >= 2]
    cross_signal = len(cross_signal_contributors) >= 2
    event_elevated = [
        signal for signal, info in events.items()
        if EVENT_ELEVATED_COUNT <= info["count"] < EVENT_CLUSTER_COUNT
    ]
    if sustained_mild or cross_signal or event_elevated:
        medium_signals = set(sustained_mild) | set(event_elevated)
        reasons = [_sustained_reason(s, continuous[s]) for s in sustained_mild] + [
            f"{s} elevated rate: {events[s]['count']}/{events[s]['n']} readings" for s in event_elevated
        ]
        if cross_signal:
            medium_signals |= set(cross_signal_contributors)
            reasons.append(
                f"cross-signal deviation: {', '.join(sorted(cross_signal_contributors))} deviated together"
            )
        return {"severity": "medium", "signals": sorted(medium_signals), "reasoning": reasons}

    low_signals = set(anomalous_continuous)
    reasons = [f"{s} isolated deviation" for s in anomalous_continuous]
    for signal, info in events.items():
        if info["count"] == 1:
            low_signals.add(signal)
            reasons.append(f"{signal} isolated event")
    if low_signals:
        return {"severity": "low", "signals": sorted(low_signals), "reasoning": reasons}

    return {"severity": "none", "signals": [], "reasoning": ["no deviation detected"]}
