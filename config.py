"""Smart Energy AI - config.py."""

"""
Central configuration for the Smart Energy AI project.

This file contains shared paths, campus definitions,
units, thresholds, and simulation settings.
"""

from pathlib import Path

# =========================================================
# PROJECT PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIRECTORY = BASE_DIR / "data"
MODEL_DIRECTORY = BASE_DIR / "models"
DOCUMENT_DIRECTORY = BASE_DIR / "documents"
VECTOR_STORE_DIRECTORY = BASE_DIR / "vector_store"


# =========================================================
# CAMPUS BUILDINGS
# =========================================================

BUILDINGS = {
    "B001": {
        "building_name": "Administration",
        "building_type": "administration",
        # Real floor area from Building Data Genome 2 (Robin_office_Gayle)
        "floor_area_m2": 4161,
        # Simulated operational assumptions below (not measured values)
        "maximum_power_kw": 500,
        "working_start_hour": 8,
        "working_end_hour": 17,
        "has_solar": True,
        "has_ev_charging": True,
        "has_battery": False,
    },
    "B002": {
        "building_name": "Labs",
        "building_type": "laboratory",
        # Real floor area from Building Data Genome 2 (Robin_education_Megan)
        "floor_area_m2": 7579,
        # Simulated operational assumptions below (not measured values)
        "maximum_power_kw": 700,
        "working_start_hour": 7,
        "working_end_hour": 20,
        "has_solar": True,
        "has_ev_charging": False,
        "has_battery": True,
    },
    "B003": {
        "building_name": "Classrooms",
        "building_type": "classroom",
        # Real floor area from Building Data Genome 2 (Robin_education_Kiera)
        "floor_area_m2": 4703,
        # Simulated operational assumptions below (not measured values)
        "maximum_power_kw": 550,
        "working_start_hour": 8,
        "working_end_hour": 18,
        "has_solar": True,
        "has_ev_charging": False,
        "has_battery": False,
    },
}


# =========================================================
# SIMULATION SETTINGS
# =========================================================

SIMULATION_START_DATE = "2026-07-01"
SIMULATION_END_DATE = "2026-09-20"

DATA_FREQUENCY = "1h"

RANDOM_SEED = 42


# =========================================================
# STANDARD UNITS
# =========================================================

POWER_UNIT = "kW"
ENERGY_UNIT = "kWh"
TEMPERATURE_UNIT = "C"
OCCUPANCY_UNIT = "%"
CURRENCY = "JOD"


# =========================================================
# GRID SETTINGS
# =========================================================

CAMPUS_PEAK_LIMIT_KW = 850.0

GRID_STATUS_NORMAL = "NORMAL"
GRID_STATUS_ELEVATED = "ELEVATED"
GRID_STATUS_HIGH = "HIGH"
GRID_STATUS_CRITICAL = "CRITICAL"


# =========================================================
# FUTURE ANALYTICS THRESHOLDS
# =========================================================

ENERGY_ANOMALY_THRESHOLD_PERCENT = 25.0

SOLAR_UNDERPERFORMANCE_THRESHOLD_PERCENT = 20.0

LOW_OCCUPANCY_THRESHOLD_PERCENT = 25.0

HIGH_HVAC_LOAD_THRESHOLD_PERCENT = 75.0


# =========================================================
# DATA FILE PATHS
# =========================================================

BUILDINGS_DATA_PATH = DATA_DIRECTORY / "buildings.csv"

ENERGY_DATA_PATH = DATA_DIRECTORY / "energy_readings.csv"

OCCUPANCY_DATA_PATH = DATA_DIRECTORY / "occupancy.csv"

HVAC_DATA_PATH = DATA_DIRECTORY / "hvac_readings.csv"

SOLAR_DATA_PATH = DATA_DIRECTORY / "solar_readings.csv"

EV_CHARGING_DATA_PATH = DATA_DIRECTORY / "ev_charging.csv"

BATTERY_DATA_PATH = DATA_DIRECTORY / "battery_readings.csv"

GRID_SIGNALS_DATA_PATH = DATA_DIRECTORY / "grid_signals.csv"

ANOMALY_LABELS_DATA_PATH = DATA_DIRECTORY / "anomaly_labels.csv"
