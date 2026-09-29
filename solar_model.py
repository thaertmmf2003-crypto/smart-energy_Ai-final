"""
Solar Model
Smart Energy, Solar & Grid-Aware Operations AI

Estimate hourly solar PV generation using historical
solar radiation from Open-Meteo.
"""

from pathlib import Path
import pandas as pd

# =========================================================
# PATHS
# =========================================================

BASE_DIRECTORY = Path(__file__).resolve().parent

PROCESSED_DIRECTORY = BASE_DIRECTORY / "data" / "processed"

WEATHER_PATH = PROCESSED_DIRECTORY / "weather_data.csv"

SOLAR_OUTPUT_PATH = PROCESSED_DIRECTORY / "solar_readings.csv"


# =========================================================
# CAMPUS SOLAR CONFIGURATION
# =========================================================

SOLAR_BUILDINGS = {
    "B001": {
        "capacity_kw": 120.0,
        "performance_ratio": 0.80,
    },
    "B002": {
        "capacity_kw": 180.0,
        "performance_ratio": 0.80,
    },
    "B003": {
        "capacity_kw": 150.0,
        "performance_ratio": 0.80,
    },
}


# =========================================================
# CALCULATE SOLAR GENERATION
# =========================================================


def calculate_solar_generation():

    print("=" * 60)
    print("SMART ENERGY AI - SOLAR MODEL")
    print("=" * 60)

    weather = pd.read_csv(
        WEATHER_PATH,
        parse_dates=["timestamp"],
    )

    required_columns = {
        "timestamp",
        "shortwave_radiation_w_m2",
    }

    missing_columns = required_columns - set(weather.columns)

    if missing_columns:
        raise ValueError(f"Missing weather columns: {missing_columns}")

    solar_records = []

    for building_id, config in SOLAR_BUILDINGS.items():

        capacity_kw = config["capacity_kw"]

        performance_ratio = config["performance_ratio"]

        building_solar = weather[
            [
                "timestamp",
                "shortwave_radiation_w_m2",
            ]
        ].copy()

        building_solar["building_id"] = building_id

        # Approximate PV output:
        #
        # PV power =
        # capacity × irradiance / 1000 × performance ratio

        building_solar["solar_generation_kw"] = (
            capacity_kw
            * (building_solar["shortwave_radiation_w_m2"] / 1000.0)
            * performance_ratio
        )

        building_solar["solar_generation_kw"] = (
            building_solar["solar_generation_kw"]
            .clip(
                lower=0,
                upper=capacity_kw,
            )
            .round(3)
        )

        solar_records.append(
            building_solar[
                [
                    "timestamp",
                    "building_id",
                    "solar_generation_kw",
                ]
            ]
        )

    solar = pd.concat(
        solar_records,
        ignore_index=True,
    )

    solar = solar.sort_values(
        [
            "timestamp",
            "building_id",
        ]
    ).reset_index(drop=True)

    return solar


# =========================================================
# SAVE
# =========================================================


def save_solar_data(solar):

    solar.to_csv(
        SOLAR_OUTPUT_PATH,
        index=False,
    )

    print("\nFirst rows:")
    print(solar.head(12).to_string(index=False))

    print("\nRows:", len(solar))

    print("Missing values:", solar["solar_generation_kw"].isna().sum())

    print("Start:", solar["timestamp"].min())

    print("End:", solar["timestamp"].max())

    print("\nSolar summary:")
    print(
        solar.groupby("building_id")["solar_generation_kw"]
        .agg(["mean", "max"])
        .round(2)
    )

    print(f"\nSaved: {SOLAR_OUTPUT_PATH}")


# =========================================================
# MAIN
# =========================================================


def main():

    solar = calculate_solar_generation()

    save_solar_data(solar)

    print("\n" + "=" * 60)
    print("SOLAR DATA PREPARATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
