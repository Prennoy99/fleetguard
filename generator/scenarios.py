"""The 18 labeled anomaly scenarios — ground truth for the evaluation
harness. Each scenario names a vehicle, a time window, an anomaly
type/severity/signal set, and an "effect" that mutates that vehicle's
baseline arrays (from fleet_sim.generate_vehicle_baseline) within the window.

Severity tiers, 6 scenarios each:
  low    - single-sample deviation, one signal, no sustained pattern
  medium - sustained (3+ samples) deviation, or two signals moving together
  high   - safety/breakdown-relevant, sustained, should trigger the
           human-approval gate
"""
from datetime import timedelta

import numpy as np

from generator.config import SAMPLE_INTERVAL_MINUTES, SAMPLES_PER_DAY, START_TIME, VEHICLE_IDS

LOW_DURATION = 1
MEDIUM_DURATION = 6   # 30 minutes
HIGH_DURATION = 12    # 60 minutes


def _window(vehicle_index: int, day_offset: int, hour: float, duration: int):
    start_idx = day_offset * SAMPLES_PER_DAY + int(hour * 60 / SAMPLE_INTERVAL_MINUTES)
    end_idx = start_idx + duration
    return start_idx, end_idx


def _effect_temp_spike(arr, s, e, rng):
    arr["engine_temp_c"][s:e] += 25.0


def _effect_oil_dip(arr, s, e, rng):
    arr["oil_pressure_bar"][s:e] = np.maximum(arr["oil_pressure_bar"][s:e] - 1.5, 0.2)


def _effect_battery_dip(arr, s, e, rng):
    arr["battery_v"][s:e] -= 1.2


def _effect_fuel_spike(arr, s, e, rng):
    arr["fuel_rate_lh"][s:e] *= 2.5


def _effect_accel_isolated(arr, s, e, rng):
    arr["harsh_accel"][s:e] = True


def _effect_brake_isolated(arr, s, e, rng):
    arr["hard_brake"][s:e] = True


def _effect_temp_sustained(arr, s, e, rng):
    ramp = np.linspace(5.0, 20.0, e - s)
    arr["engine_temp_c"][s:e] += ramp


def _effect_oil_sustained(arr, s, e, rng):
    arr["oil_pressure_bar"][s:e] = np.maximum(arr["oil_pressure_bar"][s:e] - 1.0, 0.5)


def _effect_battery_declining(arr, s, e, rng):
    decline = np.linspace(0.0, 1.5, e - s)
    arr["battery_v"][s:e] -= decline


def _effect_cross_temp_oil(arr, s, e, rng):
    arr["engine_temp_c"][s:e] += 15.0
    arr["oil_pressure_bar"][s:e] = np.maximum(arr["oil_pressure_bar"][s:e] - 1.0, 0.5)


def _effect_fuel_inefficiency(arr, s, e, rng):
    arr["fuel_rate_lh"][s:e] *= 1.8


def _effect_brake_accel_elevated(arr, s, e, rng):
    n = e - s
    arr["hard_brake"][s:e] |= rng.random(n) < 0.4
    arr["harsh_accel"][s:e] |= rng.random(n) < 0.4


def _effect_oil_critical(arr, s, e, rng):
    arr["oil_pressure_bar"][s:e] = rng.uniform(0.2, 0.5, e - s)


def _effect_battery_collapse(arr, s, e, rng):
    arr["battery_v"][s:e] = rng.uniform(9.0, 9.8, e - s)


def _effect_temp_severe(arr, s, e, rng):
    arr["engine_temp_c"][s:e] = rng.uniform(122, 130, e - s)


def _effect_brake_cluster(arr, s, e, rng):
    n = e - s
    arr["hard_brake"][s:e] |= rng.random(n) < 0.85


def _effect_accel_cluster(arr, s, e, rng):
    n = e - s
    arr["harsh_accel"][s:e] |= rng.random(n) < 0.85


def _effect_combined_critical(arr, s, e, rng):
    arr["engine_temp_c"][s:e] = rng.uniform(122, 130, e - s)
    arr["oil_pressure_bar"][s:e] = rng.uniform(0.2, 0.5, e - s)


# (scenario_id, vehicle_index, day_offset, hour, duration, anomaly_type,
#  severity, signals, description, effect_fn)
_DEFS = [
    ("S01", 0, 3, 10.0, LOW_DURATION, "engine_temp_spike", "low",
     ["engine_temp_c"], "Single-reading engine temperature spike, no sustained pattern.",
     _effect_temp_spike),
    ("S02", 1, 4, 10.0, LOW_DURATION, "oil_pressure_dip", "low",
     ["oil_pressure_bar"], "Single-reading oil pressure dip, recovers immediately.",
     _effect_oil_dip),
    ("S03", 2, 5, 10.0, LOW_DURATION, "battery_voltage_dip", "low",
     ["battery_v"], "Single-reading battery voltage dip.",
     _effect_battery_dip),
    ("S04", 3, 6, 10.0, LOW_DURATION, "fuel_rate_blip", "low",
     ["fuel_rate_lh"], "Single-reading fuel consumption blip.",
     _effect_fuel_spike),
    ("S05", 4, 7, 10.0, LOW_DURATION, "isolated_harsh_accel", "low",
     ["harsh_accel"], "One isolated harsh-acceleration event, not part of a cluster.",
     _effect_accel_isolated),
    ("S06", 5, 8, 10.0, LOW_DURATION, "isolated_hard_brake", "low",
     ["hard_brake"], "One isolated hard-braking event, not part of a cluster.",
     _effect_brake_isolated),

    ("S07", 6, 9, 9.0, MEDIUM_DURATION, "sustained_overheating", "medium",
     ["engine_temp_c"], "Engine temperature ramps up and stays elevated for 30 minutes.",
     _effect_temp_sustained),
    ("S08", 7, 10, 9.0, MEDIUM_DURATION, "sustained_low_oil_pressure", "medium",
     ["oil_pressure_bar"], "Oil pressure stays below baseline for 30 minutes.",
     _effect_oil_sustained),
    ("S09", 8, 11, 9.0, MEDIUM_DURATION, "battery_degradation_trend", "medium",
     ["battery_v"], "Battery voltage declines steadily over 30 minutes.",
     _effect_battery_declining),
    ("S10", 9, 12, 9.0, MEDIUM_DURATION, "temp_oil_cross_signal", "medium",
     ["engine_temp_c", "oil_pressure_bar"],
     "Rising engine temperature and dropping oil pressure together — developing fault.",
     _effect_cross_temp_oil),
    ("S11", 10, 13, 9.0, MEDIUM_DURATION, "sustained_fuel_inefficiency", "medium",
     ["fuel_rate_lh"], "Fuel consumption stays elevated relative to speed for 30 minutes.",
     _effect_fuel_inefficiency),
    ("S12", 11, 14, 9.0, MEDIUM_DURATION, "elevated_brake_accel_rate", "medium",
     ["hard_brake", "harsh_accel"],
     "Hard-brake/harsh-accel frequency elevated above baseline for 30 minutes, short of a dense cluster.",
     _effect_brake_accel_elevated),

    ("S13", 12, 15, 9.0, HIGH_DURATION, "critical_oil_pressure", "high",
     ["oil_pressure_bar"], "Oil pressure collapses to a critical level for a full hour.",
     _effect_oil_critical),
    ("S14", 13, 16, 9.0, HIGH_DURATION, "battery_collapse", "high",
     ["battery_v"], "Battery voltage collapses toward no-start territory for a full hour.",
     _effect_battery_collapse),
    ("S15", 14, 17, 9.0, HIGH_DURATION, "severe_overheating", "high",
     ["engine_temp_c"], "Engine temperature holds at a severe, breakdown-risk level for a full hour.",
     _effect_temp_severe),
    ("S16", 15, 18, 9.0, HIGH_DURATION, "hard_brake_cluster", "high",
     ["hard_brake"], "Dense cluster of hard-braking events within an hour — safety risk.",
     _effect_brake_cluster),
    ("S17", 16, 19, 9.0, HIGH_DURATION, "harsh_accel_cluster", "high",
     ["harsh_accel"], "Dense cluster of harsh-acceleration events within an hour — safety risk.",
     _effect_accel_cluster),
    ("S18", 17, 20, 9.0, HIGH_DURATION, "cascading_temp_oil_failure", "high",
     ["engine_temp_c", "oil_pressure_bar"],
     "Severe overheating and critical oil pressure simultaneously — cascading failure risk.",
     _effect_combined_critical),
]


def build_scenarios() -> list[dict]:
    """Materialize scenario metadata (id, vehicle, window, labels) without
    applying effects — used both to drive generation and as the exported
    ground-truth table.
    """
    out = []
    for (sid, vidx, day, hour, dur, atype, sev, signals, desc, _fn) in _DEFS:
        s_idx, e_idx = _window(vidx, day, hour, dur)
        start_time = START_TIME + timedelta(minutes=s_idx * SAMPLE_INTERVAL_MINUTES)
        end_time = START_TIME + timedelta(minutes=(e_idx - 1) * SAMPLE_INTERVAL_MINUTES)
        out.append({
            "scenario_id": sid,
            "vehicle_id": VEHICLE_IDS[vidx],
            "vehicle_index": vidx,
            "start_index": s_idx,
            "end_index": e_idx,
            "start_time": start_time,
            "end_time": end_time,
            "anomaly_type": atype,
            "severity": sev,
            "signals": signals,
            "description": desc,
        })
    return out


def apply_scenarios_for_vehicle(vehicle_index: int, arrays: dict, rng: np.random.Generator) -> dict:
    """Mutate one vehicle's baseline arrays in place for every scenario that
    targets it, returning the same dict for convenience.
    """
    for (sid, vidx, day, hour, dur, atype, sev, signals, desc, fn) in _DEFS:
        if vidx != vehicle_index:
            continue
        s_idx, e_idx = _window(vidx, day, hour, dur)
        fn(arrays, s_idx, e_idx, rng)
    return arrays
