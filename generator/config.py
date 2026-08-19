"""Fixed parameters for the deterministic batch generator."""
from datetime import datetime, timezone

SEED = 42

NUM_VEHICLES = 25
VEHICLE_IDS = [f"veh-{i:03d}" for i in range(1, NUM_VEHICLES + 1)]

NUM_DAYS = 45
SAMPLE_INTERVAL_MINUTES = 5
SAMPLES_PER_DAY = (24 * 60) // SAMPLE_INTERVAL_MINUTES  # 288

START_TIME = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

# Random-walk origin for latitude/longitude (Munich, matching fleetpulse).
ORIGIN_LAT = 48.1351
ORIGIN_LON = 11.5820
