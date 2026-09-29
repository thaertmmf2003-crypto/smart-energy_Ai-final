"""
Smart Energy AI - ML Dataset Preparation
"""

from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "processed"

OUTPUT_PATH = DATA_DIR / "ml_energy_dataset.csv"


def load_data():

    energy = pd.read_csv(
        DATA_DIR / "energy_readings.csv",
        parse_dates=["timestamp"],
    )

    weather = pd.read_csv(
        DATA_DIR / "weather_data.csv",
        parse_dates=["timestamp"],
    )

    solar = pd.read_csv(
        DATA_DIR / "solar_readings.csv",
        parse_dates=["timestamp"],
    )

    occupancy = pd.read_csv(
        DATA_DIR / "occupancy.csv",
        parse_dates=["timestamp"],
    )

    hvac = pd.read_csv(
        DATA_DIR / "hvac_readings.csv",
        parse_dates=["timestamp"],
    )

    ev = pd.read_csv(
        DATA_DIR / "ev_charging.csv",
        parse_dates=["timestamp"],
    )

    battery = pd.read_csv(
        DATA_DIR / "battery_readings.csv",
        parse_dates=["timestamp"],
    )

    grid = pd.read_csv(
        DATA_DIR / "grid_signals.csv",
        parse_dates=["timestamp"],
    )

    return (
        energy,
        weather,
        solar,
        occupancy,
        hvac,
        ev,
        battery,
        grid,
    )


def build_ml_dataset():

    (
        energy,
        weather,
        solar,
        occupancy,
        hvac,
        ev,
        battery,
        grid,
    ) = load_data()

    # -----------------------------------------------------
    # Start with target data
    # -----------------------------------------------------

    data = energy.copy()

    # -----------------------------------------------------
    # Weather
    # Campus-level data -> merge by timestamp
    # -----------------------------------------------------

    data = data.merge(
        weather,
        on="timestamp",
        how="left",
    )

    # -----------------------------------------------------
    # Building-level datasets
    # -----------------------------------------------------

    data = data.merge(
        solar,
        on=[
            "timestamp",
            "building_id",
        ],
        how="left",
    )

    data = data.merge(
        occupancy,
        on=[
            "timestamp",
            "building_id",
        ],
        how="left",
    )

    data = data.merge(
        hvac,
        on=[
            "timestamp",
            "building_id",
        ],
        how="left",
    )

    data = data.merge(
        ev,
        on=[
            "timestamp",
            "building_id",
        ],
        how="left",
    )

    data = data.merge(
        battery,
        on=[
            "timestamp",
            "building_id",
        ],
        how="left",
    )

    # -----------------------------------------------------
    # Grid
    # Campus-level data
    # -----------------------------------------------------

    data = data.merge(
        grid,
        on="timestamp",
        how="left",
    )

    # -----------------------------------------------------
    # TIME FEATURES
    # -----------------------------------------------------

    data["hour"] = data["timestamp"].dt.hour

    data["day_of_week"] = data["timestamp"].dt.dayofweek

    data["month"] = data["timestamp"].dt.month

    data["day_of_year"] = data["timestamp"].dt.dayofyear

    data["is_weekend"] = (data["day_of_week"] >= 5).astype(int)

    # -----------------------------------------------------
    # CYCLICAL TIME FEATURES
    # -----------------------------------------------------

    import numpy as np

    data["hour_sin"] = np.sin(2 * np.pi * data["hour"] / 24)

    data["hour_cos"] = np.cos(2 * np.pi * data["hour"] / 24)

    data["day_sin"] = np.sin(2 * np.pi * data["day_of_week"] / 7)

    data["day_cos"] = np.cos(2 * np.pi * data["day_of_week"] / 7)

    # -----------------------------------------------------
    # SORT BEFORE LAG FEATURES
    # -----------------------------------------------------

    data = data.sort_values(
        [
            "building_id",
            "timestamp",
        ]
    ).reset_index(drop=True)

    # -----------------------------------------------------
    # HISTORICAL ENERGY FEATURES
    # -----------------------------------------------------

    data["energy_lag_1"] = data.groupby("building_id")["energy"].shift(1)

    data["energy_lag_24"] = data.groupby("building_id")["energy"].shift(24)

    data["energy_lag_168"] = data.groupby("building_id")["energy"].shift(168)

    # -----------------------------------------------------
    # ROLLING FEATURES
    #
    # shift(1) prevents the current target value from
    # leaking into the rolling feature.
    # -----------------------------------------------------

    data["energy_rolling_24_mean"] = data.groupby("building_id")["energy"].transform(
        lambda series: series.shift(1)
        .rolling(
            window=24,
            min_periods=1,
        )
        .mean()
    )

    data["energy_rolling_168_mean"] = data.groupby("building_id")["energy"].transform(
        lambda series: series.shift(1)
        .rolling(
            window=168,
            min_periods=1,
        )
        .mean()
    )

    # -----------------------------------------------------
    # REMOVE INITIAL ROWS WITHOUT FULL LAG HISTORY
    # -----------------------------------------------------

    required_lags = [
        "energy_lag_1",
        "energy_lag_24",
        "energy_lag_168",
    ]

    before = len(data)

    data = data.dropna(subset=required_lags).reset_index(drop=True)

    removed = before - len(data)

    # -----------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------

    print("=" * 60)
    print("SMART ENERGY AI - ML DATASET")
    print("=" * 60)

    print(
        "\nRows before lag cleanup:",
        before,
    )

    print(
        "Rows removed:",
        removed,
    )

    print(
        "Final rows:",
        len(data),
    )

    print(
        "Columns:",
        len(data.columns),
    )

    print(
        "Missing values:",
        data.isnull().sum().sum(),
    )

    print("\nDate range:")

    print(
        data["timestamp"].min(),
        "->",
        data["timestamp"].max(),
    )

    print("\nRows per building:")

    print(data["building_id"].value_counts())

    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

    data.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print(
        "\nSaved:",
        OUTPUT_PATH,
    )

    print("\n" + "=" * 60)
    print("ML DATASET PREPARATION COMPLETE")
    print("=" * 60)

    return data


if __name__ == "__main__":
    build_ml_dataset()
