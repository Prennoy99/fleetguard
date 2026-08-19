"""Deterministic baseline telemetry simulator.

Produces one 5-minute-sampled time series per vehicle over the full history
window, before any anomaly scenarios are injected (see scenarios.py). Every
vehicle gets its own numpy Generator seeded from config.SEED + vehicle index,
so a single vehicle's series is reproducible in isolation (useful for tests)
and the whole fleet is reproducible together.

Signals and units follow ../schema/telemetry_event.schema.json.
"""
from datetime import timedelta

import numpy as np

from generator.config import (
    NUM_DAYS,
    ORIGIN_LAT,
    ORIGIN_LON,
    SAMPLE_INTERVAL_MINUTES,
    SAMPLES_PER_DAY,
    SEED,
    START_TIME,
)

TOTAL_SAMPLES = NUM_DAYS * SAMPLES_PER_DAY


def event_times() -> list:
    """Timestamps shared by every vehicle (same clock, same length)."""
    step = timedelta(minutes=SAMPLE_INTERVAL_MINUTES)
    return [START_TIME + i * step for i in range(TOTAL_SAMPLES)]


def _activity_curve(rng: np.random.Generator) -> np.ndarray:
    """Smooth 0..1 'how likely this vehicle is driving right now' curve.

    Two rush-hour bumps (7-9am, 5-7pm) plus light midday activity and near-
    zero overnight, repeated every day, with a per-vehicle phase/amplitude
    jitter so the 25 vehicles don't all move in lockstep.
    """
    hours = (np.arange(TOTAL_SAMPLES) % SAMPLES_PER_DAY) * (SAMPLE_INTERVAL_MINUTES / 60.0)
    phase = rng.uniform(-0.5, 0.5)
    amp = rng.uniform(0.85, 1.15)

    def bump(center, width):
        return np.exp(-0.5 * ((hours - center + phase) / width) ** 2)

    morning = bump(8.0, 1.1)
    evening = bump(18.0, 1.3)
    midday = 0.25 * bump(13.0, 3.0)
    activity = amp * np.clip(morning + evening + midday, 0, 1)
    return np.clip(activity, 0.0, 1.0)


def generate_vehicle_baseline(vehicle_index: int) -> dict:
    """Return baseline (pre-anomaly) arrays for one vehicle, keyed by field name."""
    rng = np.random.default_rng(SEED + vehicle_index)

    activity = _activity_curve(rng)
    driving = activity > 0.08

    max_speed = rng.uniform(100, 130)
    speed = np.where(
        driving,
        np.clip(activity * max_speed + rng.normal(0, 6, TOTAL_SAMPLES), 0, 140),
        0.0,
    )
    gear = np.clip((speed // 25).astype(int) + 1, 1, 6)
    rpm = np.where(driving, 900 + speed * 35 + rng.normal(0, 150, TOTAL_SAMPLES), 0).astype(int)
    rpm = np.clip(rpm, 0, 6500)

    throttle = np.where(driving, np.clip(activity * 80 + rng.normal(0, 10, TOTAL_SAMPLES), 0, 100), 0.0)
    brake = np.where(
        driving & (rng.random(TOTAL_SAMPLES) < 0.08),
        rng.uniform(10, 60, TOTAL_SAMPLES),
        0.0,
    )

    # Engine temp: exponential relaxation toward a target that depends on
    # whether the vehicle is currently active (~90C running, ambient ~20C
    # otherwise), so temp rises/falls smoothly across consecutive samples
    # instead of jumping.
    target_temp = np.where(driving, 90.0, 20.0)
    temp = np.empty(TOTAL_SAMPLES)
    temp[0] = 20.0
    for i in range(1, TOTAL_SAMPLES):
        rate = 0.15 if driving[i] else 0.02
        temp[i] = temp[i - 1] + rate * (target_temp[i] - temp[i - 1]) + rng.normal(0, 0.4)
    engine_temp = temp

    oil_pressure = np.where(
        driving,
        np.clip(3.2 + rng.normal(0, 0.25, TOTAL_SAMPLES), 1.5, 5.0),
        0.0,
    )

    # Battery: relaxes toward ~14.1V while running (alternator charging) and
    # toward ~12.4V at rest, much slower than engine temp (batteries hold
    # charge for days, not minutes).
    target_batt = np.where(driving, 14.1, 12.4)
    batt = np.empty(TOTAL_SAMPLES)
    batt[0] = 12.6
    for i in range(1, TOTAL_SAMPLES):
        batt[i] = batt[i - 1] + 0.01 * (target_batt[i] - batt[i - 1]) + rng.normal(0, 0.03)
    battery_v = batt

    fuel_rate = np.where(driving, 1.5 + throttle * 0.04 + rng.normal(0, 0.3, TOTAL_SAMPLES), 0.0)
    fuel_rate = np.clip(fuel_rate, 0, None)
    consumption_per_step = fuel_rate * (SAMPLE_INTERVAL_MINUTES / 60.0) * 0.6
    fuel_level = np.empty(TOTAL_SAMPLES)
    level = rng.uniform(70, 100)
    for i in range(TOTAL_SAMPLES):
        level -= consumption_per_step[i]
        if level < 15:
            level = rng.uniform(85, 100)  # refuel
        fuel_level[i] = level

    heading = np.cumsum(rng.normal(0, 0.05, TOTAL_SAMPLES))
    dist_km = speed * (SAMPLE_INTERVAL_MINUTES / 60.0)
    dlat = np.where(driving, dist_km * np.cos(heading) / 111.0, 0.0)
    dlon = np.where(
        driving,
        dist_km * np.sin(heading) / (111.0 * np.cos(np.radians(ORIGIN_LAT))),
        0.0,
    )
    latitude = ORIGIN_LAT + np.cumsum(dlat) * 0.05
    longitude = ORIGIN_LON + np.cumsum(dlon) * 0.05
    altitude = 520 + rng.normal(0, 15, TOTAL_SAMPLES).cumsum() * 0.01
    altitude = np.clip(altitude, 480, 620)

    # Rare event flags, only possible while driving (fleetpulse README: ~0.2%).
    hard_brake = driving & (rng.random(TOTAL_SAMPLES) < 0.002)
    harsh_accel = driving & (rng.random(TOTAL_SAMPLES) < 0.002)
    lane_departure = driving & (rng.random(TOTAL_SAMPLES) < 0.001)

    return {
        "speed_kmh": speed,
        "rpm": rpm,
        "gear": gear,
        "throttle_pct": throttle,
        "brake_pct": brake,
        "fuel_level_pct": fuel_level,
        "fuel_rate_lh": fuel_rate,
        "engine_temp_c": engine_temp,
        "oil_pressure_bar": oil_pressure,
        "battery_v": battery_v,
        "latitude": latitude,
        "longitude": longitude,
        "altitude_m": altitude,
        "hard_brake": hard_brake,
        "harsh_accel": harsh_accel,
        "lane_departure": lane_departure,
    }
