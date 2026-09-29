"""
Smart Energy AI - Prediction Engine

Uses energy forecast results to:
1. Detect forecast residual anomalies
2. Calculate campus predicted demand
3. Detect peak demand risk
4. Generate events for the AI Agent
"""

from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data" / "processed"

FORECAST_PATH = DATA_DIR / "energy_forecast_results.csv"

GRID_PATH = DATA_DIR / "grid_signals.csv"

OUTPUT_PATH = DATA_DIR / "prediction_events.csv"


# =========================================================
# SETTINGS
# =========================================================

# Residual threshold:
# error larger than this percentage of predicted demand
ANOMALY_THRESHOLD_PERCENT = 25.0

# Campus demand / grid limit thresholds
PEAK_WARNING_RATIO = 0.80
PEAK_HIGH_RATIO = 0.90


# =========================================================
# LOAD DATA
# =========================================================


def load_data():

    forecast = pd.read_csv(
        FORECAST_PATH,
        parse_dates=["timestamp"],
    )

    grid = pd.read_csv(
        GRID_PATH,
        parse_dates=["timestamp"],
    )

    return forecast, grid


# =========================================================
# ENERGY ANOMALIES
# =========================================================


def detect_forecast_anomalies(
    forecast,
):

    data = forecast.copy()

    denominator = data["predicted_energy"].abs().clip(lower=1.0)

    data["residual_percent"] = (
        (data["energy"] - data["predicted_energy"]) / denominator * 100
    )

    data["is_energy_anomaly"] = (
        data["residual_percent"].abs() >= ANOMALY_THRESHOLD_PERCENT
    )

    return data


# =========================================================
# CAMPUS FORECAST
# =========================================================


def calculate_campus_forecast(
    forecast,
):

    campus = (
        forecast.groupby("timestamp")
        .agg(
            actual_campus_energy=(
                "energy",
                "sum",
            ),
            predicted_campus_energy=(
                "predicted_energy",
                "sum",
            ),
        )
        .reset_index()
    )

    return campus


# =========================================================
# PEAK RISK
# =========================================================


def detect_peak_risk(
    campus,
    grid,
):

    data = campus.merge(
        grid[
            [
                "timestamp",
                "grid_import_limit_kw",
                "grid_status",
                "grid_stress_level",
            ]
        ],
        on="timestamp",
        how="left",
    )

    # Physical / simulated grid limit ratio
    data["grid_limit_ratio"] = (
        data["predicted_campus_energy"] / data["grid_import_limit_kw"]
    )

    # Historical demand thresholds
    threshold_elevated = data["predicted_campus_energy"].quantile(0.90)

    threshold_high = data["predicted_campus_energy"].quantile(0.95)

    threshold_critical = data["predicted_campus_energy"].quantile(0.99)

    def classify_risk(predicted_load):

        if predicted_load >= threshold_critical:
            return "CRITICAL"

        if predicted_load >= threshold_high:
            return "HIGH"

        if predicted_load >= threshold_elevated:
            return "ELEVATED"

        return "NORMAL"

    data["peak_risk"] = data["predicted_campus_energy"].apply(classify_risk)

    # Keep percentage relative to the simulated
    # grid import limit for reporting.
    data["predicted_load_ratio"] = data["grid_limit_ratio"]

    print("\nPeak thresholds:")

    print(f"ELEVATED >= " f"{threshold_elevated:.2f}")

    print(f"HIGH     >= " f"{threshold_high:.2f}")

    print(f"CRITICAL >= " f"{threshold_critical:.2f}")

    return data


# =========================================================
# BUILD AGENT EVENTS
# =========================================================


def build_events(
    anomaly_data,
    peak_data,
):

    events = []

    # -----------------------------------------------------
    # Energy anomaly events
    # -----------------------------------------------------

    anomalies = anomaly_data[anomaly_data["is_energy_anomaly"]]

    for _, row in anomalies.iterrows():

        events.append(
            {
                "timestamp": row["timestamp"],
                "event_type": "ENERGY_ANOMALY",
                "building_id": row["building_id"],
                "severity": (
                    "HIGH" if abs(row["residual_percent"]) >= 50 else "ELEVATED"
                ),
                "value": round(
                    row["residual_percent"],
                    2,
                ),
                "description": (
                    "Actual energy differs " "significantly from forecast."
                ),
            }
        )

    # -----------------------------------------------------
    # Peak demand events
    # -----------------------------------------------------

    peaks = peak_data[
        peak_data["peak_risk"].isin(
            [
                "ELEVATED",
                "HIGH",
                "CRITICAL",
            ]
        )
    ]

    for _, row in peaks.iterrows():

        events.append(
            {
                "timestamp": row["timestamp"],
                "event_type": "PEAK_DEMAND_RISK",
                "building_id": "CAMPUS",
                "severity": row["peak_risk"],
                "value": round(
                    row["predicted_load_ratio"] * 100,
                    2,
                ),
                "description": (
                    "Predicted campus demand "
                    "is unusually high relative "
                    "to historical forecast levels."
                ),
            }
        )

    events_dataframe = pd.DataFrame(events)

    if not events_dataframe.empty:

        events_dataframe = events_dataframe.sort_values("timestamp").reset_index(
            drop=True
        )

    return events_dataframe


# =========================================================
# MAIN
# =========================================================


def main():

    print("=" * 60)
    print("SMART ENERGY AI - PREDICTION ENGINE")
    print("=" * 60)

    forecast, grid = load_data()

    print(
        "\nForecast rows:",
        len(forecast),
    )

    # -----------------------------------------------------
    # Anomalies
    # -----------------------------------------------------

    anomaly_data = detect_forecast_anomalies(forecast)

    anomaly_count = anomaly_data["is_energy_anomaly"].sum()

    print(
        "Forecast anomalies:",
        anomaly_count,
    )

    # -----------------------------------------------------
    # Campus forecast
    # -----------------------------------------------------

    campus = calculate_campus_forecast(forecast)

    print(
        "Campus forecast rows:",
        len(campus),
    )

    # -----------------------------------------------------
    # Peak risk
    # -----------------------------------------------------

    peak_data = detect_peak_risk(
        campus,
        grid,
    )

    print("\nPeak risk distribution:")

    print(peak_data["peak_risk"].value_counts())

    # -----------------------------------------------------
    # Events
    # -----------------------------------------------------

    events = build_events(
        anomaly_data,
        peak_data,
    )

    print(
        "\nGenerated agent events:",
        len(events),
    )

    if not events.empty:

        print("\nEvent types:")

        print(events["event_type"].value_counts())

        print("\nSample events:")

        print(events.head(10).to_string(index=False))

        events.to_csv(
            OUTPUT_PATH,
            index=False,
        )

        print(
            "\nSaved:",
            OUTPUT_PATH,
        )

    else:

        print("\nNo events generated.")

    print("\n" + "=" * 60)

    print("PREDICTION ENGINE COMPLETE")

    print("=" * 60)


if __name__ == "__main__":
    main()
