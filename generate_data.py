"""
Synthetic Operational Data Generator
Smart Energy, Solar & Grid-Aware Operations AI

Generates simulated campus operational data aligned
with the real BDG2 electricity timestamps.

Synthetic datasets:
- Occupancy
- HVAC
- EV charging
- Battery
- Grid signals
- Known anomaly labels
"""

from pathlib import Path

import numpy as np
import pandas as pd

# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIRECTORY = Path(__file__).resolve().parent

PROCESSED_DIRECTORY = BASE_DIRECTORY / "data" / "processed"

ENERGY_PATH = PROCESSED_DIRECTORY / "energy_readings.csv"

RANDOM_SEED = 42

np.random.seed(RANDOM_SEED)


# =========================================================
# BUILDING CONFIGURATION
# =========================================================

BUILDINGS = {
    "B001": {
        "type": "administration",
        "work_start": 8,
        "work_end": 17,
        "has_ev": True,
        "has_battery": False,
    },
    "B002": {
        "type": "laboratory",
        "work_start": 7,
        "work_end": 20,
        "has_ev": False,
        "has_battery": True,
    },
    "B003": {
        "type": "classroom",
        "work_start": 8,
        "work_end": 18,
        "has_ev": False,
        "has_battery": False,
    },
}


# =========================================================
# LOAD TIMELINE
# =========================================================


def load_timeline():

    energy = pd.read_csv(
        ENERGY_PATH,
        usecols=["timestamp"],
        parse_dates=["timestamp"],
    )

    timestamps = (
        energy["timestamp"].drop_duplicates().sort_values().reset_index(drop=True)
    )

    print(
        "Timeline:",
        timestamps.min(),
        "->",
        timestamps.max(),
    )

    print("Hours:", len(timestamps))

    return timestamps


# =========================================================
# OCCUPANCY
# =========================================================


def generate_occupancy(timestamps):

    records = []

    for building_id, config in BUILDINGS.items():

        for timestamp in timestamps:

            hour = timestamp.hour
            weekday = timestamp.weekday()

            # Weekend
            if weekday >= 5:
                occupancy = np.random.normal(
                    5,
                    3,
                )

            # Working hours
            elif config["work_start"] <= hour < config["work_end"]:
                occupancy = np.random.normal(
                    72,
                    15,
                )

            # Before / after work
            else:
                occupancy = np.random.normal(
                    10,
                    5,
                )

            occupancy = np.clip(
                occupancy,
                0,
                100,
            )

            records.append(
                {
                    "timestamp": timestamp,
                    "building_id": building_id,
                    "occupancy_percent": round(
                        occupancy,
                        2,
                    ),
                }
            )

    return pd.DataFrame(records)


# =========================================================
# HVAC
# =========================================================


def generate_hvac(timestamps, occupancy):

    weather_path = PROCESSED_DIRECTORY / "weather_data.csv"

    weather = pd.read_csv(
        weather_path,
        parse_dates=["timestamp"],
    )

    weather = weather[
        [
            "timestamp",
            "temperature_c",
        ]
    ]

    data = occupancy.merge(
        weather,
        on="timestamp",
        how="left",
    )

    # HVAC reacts to occupancy and deviation
    # from comfortable indoor conditions.
    temperature_effect = (data["temperature_c"] - 21).abs()

    base_hvac = 10 + data["occupancy_percent"] * 0.45 + temperature_effect * 2.2

    noise = np.random.normal(
        0,
        5,
        len(data),
    )

    data["hvac_power_kw"] = (base_hvac + noise).clip(lower=3).round(2)

    return data[
        [
            "timestamp",
            "building_id",
            "hvac_power_kw",
        ]
    ]


# =========================================================
# EV CHARGING
# =========================================================


def generate_ev_charging(timestamps):

    records = []

    for building_id, config in BUILDINGS.items():

        for timestamp in timestamps:

            power = 0.0

            if config["has_ev"]:

                hour = timestamp.hour
                weekday = timestamp.weekday()

                if weekday < 5 and 8 <= hour <= 17:

                    if np.random.random() < 0.45:
                        power = np.random.uniform(
                            10,
                            55,
                        )

            records.append(
                {
                    "timestamp": timestamp,
                    "building_id": building_id,
                    "ev_charging_power_kw": round(
                        power,
                        2,
                    ),
                }
            )

    return pd.DataFrame(records)


# =========================================================
# BATTERY
# =========================================================


def generate_battery(timestamps):

    records = []

    battery_soc = 70.0

    for building_id, config in BUILDINGS.items():

        if config["has_battery"]:
            battery_soc = 70.0

        for timestamp in timestamps:

            power = 0.0

            if config["has_battery"]:

                hour = timestamp.hour

                # Charge during low-demand night hours
                if 1 <= hour <= 5:
                    power = -20.0
                    battery_soc += 2.0

                # Discharge during evening peak
                elif 17 <= hour <= 20:
                    power = 25.0
                    battery_soc -= 2.5

                battery_soc = np.clip(
                    battery_soc,
                    20,
                    95,
                )

                soc = battery_soc

            else:
                soc = 0.0

            records.append(
                {
                    "timestamp": timestamp,
                    "building_id": building_id,
                    "battery_state_of_charge_percent": round(float(soc), 2),
                    "battery_power_kw": round(power, 2),
                }
            )

    return pd.DataFrame(records)


# =========================================================
# GRID SIGNALS
# =========================================================


def generate_grid_signals(timestamps):

    records = []

    for timestamp in timestamps:

        hour = timestamp.hour

        if 17 <= hour <= 20:

            stress = np.random.uniform(
                0.65,
                0.90,
            )

        elif 8 <= hour <= 16:

            stress = np.random.uniform(
                0.35,
                0.65,
            )

        else:

            stress = np.random.uniform(
                0.15,
                0.40,
            )

        if stress >= 0.85:
            status = "CRITICAL"

        elif stress >= 0.70:
            status = "HIGH"

        elif stress >= 0.50:
            status = "ELEVATED"

        else:
            status = "NORMAL"

        records.append(
            {
                "timestamp": timestamp,
                "grid_status": status,
                "grid_stress_level": round(stress, 3),
                "grid_import_limit_kw": 850.0,
            }
        )

    return pd.DataFrame(records)


# =========================================================
# ANOMALY LABELS
# =========================================================


def generate_anomaly_labels(timestamps):

    records = []

    # Controlled demo incidents.
    # These are labels for scenarios that the project
    # can later inject/detect.

    scenario_times = [
        timestamps.iloc[len(timestamps) // 4],
        timestamps.iloc[len(timestamps) // 2],
        timestamps.iloc[3 * len(timestamps) // 4],
    ]

    records.append(
        {
            "timestamp": scenario_times[0],
            "building_id": "B002",
            "anomaly_type": "ENERGY_ANOMALY",
            "anomaly_description": "Laboratory energy consumption significantly above expected baseline.",
        }
    )

    records.append(
        {
            "timestamp": scenario_times[1],
            "building_id": "B001",
            "anomaly_type": "SOLAR_UNDERPERFORMANCE",
            "anomaly_description": "Solar generation significantly below expected production.",
        }
    )

    records.append(
        {
            "timestamp": scenario_times[2],
            "building_id": "CAMPUS",
            "anomaly_type": "PEAK_DEMAND_RISK",
            "anomaly_description": "Campus demand approaching simulated grid import limit.",
        }
    )

    return pd.DataFrame(records)


# =========================================================
# SAVE
# =========================================================


def save_dataset(
    dataframe,
    filename,
):

    path = PROCESSED_DIRECTORY / filename

    dataframe.to_csv(
        path,
        index=False,
    )

    print(f"{filename:<25}" f"{len(dataframe):>8} rows")


# =========================================================
# MAIN
# =========================================================


def main():

    print("=" * 60)
    print("SMART ENERGY AI - OPERATIONAL DATA GENERATOR")
    print("=" * 60)

    timestamps = load_timeline()

    print("\nGenerating datasets...\n")

    occupancy = generate_occupancy(timestamps)

    hvac = generate_hvac(
        timestamps,
        occupancy,
    )

    ev = generate_ev_charging(timestamps)

    battery = generate_battery(timestamps)

    grid = generate_grid_signals(timestamps)

    anomalies = generate_anomaly_labels(timestamps)

    print("\nSaving datasets...\n")

    save_dataset(
        occupancy,
        "occupancy.csv",
    )

    save_dataset(
        hvac,
        "hvac_readings.csv",
    )

    save_dataset(
        ev,
        "ev_charging.csv",
    )

    save_dataset(
        battery,
        "battery_readings.csv",
    )

    save_dataset(
        grid,
        "grid_signals.csv",
    )

    save_dataset(
        anomalies,
        "anomaly_labels.csv",
    )

    print("\n" + "=" * 60)
    print("SYNTHETIC OPERATIONAL DATA COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
