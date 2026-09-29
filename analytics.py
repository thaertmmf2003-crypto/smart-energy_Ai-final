"""
Smart Energy AI - Analytics Module

Provides analytical functions for:
- Energy baselines
- Energy deviations
- Energy anomaly detection
- Building load analysis
- Campus load analysis
- After-hours consumption
- HVAC efficiency analysis
- Grid import estimation
- Energy cost estimation
"""

from pathlib import Path

import pandas as pd

# =========================================================
# PATHS
# =========================================================

BASE_DIRECTORY = Path(__file__).resolve().parent

PROCESSED_DIRECTORY = BASE_DIRECTORY / "data" / "processed"


# =========================================================
# BUILDING CONFIGURATION
# =========================================================

BUILDING_WORK_HOURS = {
    "B001": {
        "start": 8,
        "end": 17,
    },
    "B002": {
        "start": 7,
        "end": 20,
    },
    "B003": {
        "start": 8,
        "end": 18,
    },
}


# =========================================================
# DATA LOADING
# =========================================================


def load_energy_data():

    path = PROCESSED_DIRECTORY / "energy_readings.csv"

    dataframe = pd.read_csv(
        path,
        parse_dates=["timestamp"],
    )

    return dataframe


def load_solar_data():

    path = PROCESSED_DIRECTORY / "solar_readings.csv"

    return pd.read_csv(
        path,
        parse_dates=["timestamp"],
    )


def load_hvac_data():

    path = PROCESSED_DIRECTORY / "hvac_readings.csv"

    return pd.read_csv(
        path,
        parse_dates=["timestamp"],
    )


# =========================================================
# ENERGY BASELINE
# =========================================================


def calculate_energy_baseline(
    energy_dataframe,
):

    data = energy_dataframe.copy()

    data["hour"] = data["timestamp"].dt.hour

    data["day_of_week"] = data["timestamp"].dt.dayofweek

    baseline = (
        data.groupby(
            [
                "building_id",
                "day_of_week",
                "hour",
            ]
        )["energy"]
        .mean()
        .reset_index()
    )

    baseline = baseline.rename(columns={"energy": "expected_energy"})

    return baseline


# =========================================================
# ENERGY DEVIATION
# =========================================================


def calculate_energy_deviation_percent(
    energy_dataframe,
    baseline_dataframe,
):

    data = energy_dataframe.copy()

    data["hour"] = data["timestamp"].dt.hour

    data["day_of_week"] = data["timestamp"].dt.dayofweek

    data = data.merge(
        baseline_dataframe,
        on=[
            "building_id",
            "day_of_week",
            "hour",
        ],
        how="left",
    )

    data["energy_deviation_percent"] = (
        (data["energy"] - data["expected_energy"]) / data["expected_energy"] * 100
    )

    return data


# =========================================================
# ENERGY ANOMALY DETECTION
# =========================================================


def detect_energy_anomaly(
    dataframe,
    threshold_percent=25.0,
):

    data = dataframe.copy()

    data["is_energy_anomaly"] = (
        data["energy_deviation_percent"].abs() >= threshold_percent
    )

    return data


# =========================================================
# BUILDING TOTAL LOAD
# =========================================================


def calculate_building_total_load(
    energy_dataframe,
):

    building_load = (
        energy_dataframe.groupby("building_id")["energy"].sum().reset_index()
    )

    building_load = building_load.rename(columns={"energy": "total_energy"})

    return building_load


# =========================================================
# CAMPUS TOTAL LOAD
# =========================================================


def calculate_campus_total_load(
    energy_dataframe,
):

    campus_load = energy_dataframe.groupby("timestamp")["energy"].sum().reset_index()

    campus_load = campus_load.rename(columns={"energy": "campus_energy"})

    return campus_load


# =========================================================
# AFTER-HOURS CONSUMPTION
# =========================================================


def detect_after_hours_consumption(
    energy_dataframe,
):

    data = energy_dataframe.copy()

    data["hour"] = data["timestamp"].dt.hour

    data["day_of_week"] = data["timestamp"].dt.dayofweek

    def is_after_hours(row):

        building = row["building_id"]

        hour = row["hour"]

        day = row["day_of_week"]

        # Saturday / Sunday
        if day >= 5:
            return True

        work_hours = BUILDING_WORK_HOURS[building]

        return not (work_hours["start"] <= hour < work_hours["end"])

    data["is_after_hours"] = data.apply(
        is_after_hours,
        axis=1,
    )

    return data


# =========================================================
# HVAC ANALYSIS
# =========================================================


def analyze_hvac_efficiency(
    energy_dataframe,
    hvac_dataframe,
):

    data = energy_dataframe.merge(
        hvac_dataframe,
        on=[
            "timestamp",
            "building_id",
        ],
        how="inner",
    )

    data["hvac_to_energy_ratio"] = data["hvac_power_kw"] / data["energy"]

    data["hvac_to_energy_ratio"] = (
        data["hvac_to_energy_ratio"]
        .replace(
            [float("inf")],
            0,
        )
        .fillna(0)
    )

    return data


# =========================================================
# GRID IMPORT
# =========================================================


def calculate_grid_import(
    energy_dataframe,
    solar_dataframe,
):

    energy = energy_dataframe.groupby("timestamp")["energy"].sum().reset_index()

    solar = (
        solar_dataframe.groupby("timestamp")["solar_generation_kw"].sum().reset_index()
    )

    data = energy.merge(
        solar,
        on="timestamp",
        how="left",
    )

    data["solar_generation_kw"] = data["solar_generation_kw"].fillna(0)

    data["grid_import"] = data["energy"] - data["solar_generation_kw"]

    data["grid_import"] = data["grid_import"].clip(lower=0)

    return data


# =========================================================
# ENERGY COST
# =========================================================


def calculate_energy_cost(
    energy_value,
    price_per_unit=0.10,
):

    return energy_value * price_per_unit


# =========================================================
# MAIN TEST
# =========================================================


def main():

    print("=" * 60)
    print("SMART ENERGY AI - ANALYTICS")
    print("=" * 60)

    # Load data
    energy = load_energy_data()

    solar = load_solar_data()

    hvac = load_hvac_data()

    print(
        "\nEnergy rows:",
        len(energy),
    )

    # -----------------------------------------------------
    # Baseline
    # -----------------------------------------------------

    baseline = calculate_energy_baseline(energy)

    print(
        "Baseline rows:",
        len(baseline),
    )

    # -----------------------------------------------------
    # Deviation
    # -----------------------------------------------------

    deviation = calculate_energy_deviation_percent(
        energy,
        baseline,
    )

    # -----------------------------------------------------
    # Anomalies
    # -----------------------------------------------------

    anomaly_data = detect_energy_anomaly(deviation)

    anomaly_count = anomaly_data["is_energy_anomaly"].sum()

    print(
        "Detected energy anomalies:",
        anomaly_count,
    )

    # -----------------------------------------------------
    # Building totals
    # -----------------------------------------------------

    building_load = calculate_building_total_load(energy)

    print("\nBuilding totals:")

    print(building_load.to_string(index=False))

    # -----------------------------------------------------
    # Campus
    # -----------------------------------------------------

    campus = calculate_campus_total_load(energy)

    print(
        "\nCampus hourly rows:",
        len(campus),
    )

    # -----------------------------------------------------
    # After hours
    # -----------------------------------------------------

    after_hours = detect_after_hours_consumption(energy)

    print(
        "After-hours rows:",
        after_hours["is_after_hours"].sum(),
    )

    # -----------------------------------------------------
    # HVAC
    # -----------------------------------------------------

    hvac_analysis = analyze_hvac_efficiency(
        energy,
        hvac,
    )

    print(
        "HVAC analysis rows:",
        len(hvac_analysis),
    )

    # -----------------------------------------------------
    # Grid import
    # -----------------------------------------------------

    grid_import = calculate_grid_import(
        energy,
        solar,
    )

    print(
        "Grid import rows:",
        len(grid_import),
    )

    print("\n" + "=" * 60)
    print("ANALYTICS TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
