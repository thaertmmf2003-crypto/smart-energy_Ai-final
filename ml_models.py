"""
Smart Energy AI - Machine Learning Models

Energy demand forecasting using:
- Chronological train/test split
- Random Forest Regressor
- Weekly persistence baseline
- MAE, RMSE and R² evaluation
"""

from pathlib import Path
import pickle

import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_PATH = BASE_DIR / "data" / "processed" / "ml_energy_dataset.csv"

MODEL_DIR = BASE_DIR / "models"

MODEL_PATH = MODEL_DIR / "energy_forecast_model.pkl"


# =========================================================
# FEATURES
# =========================================================

FEATURES = [
    # Weather
    "temperature_c",
    "relative_humidity_percent",
    "cloud_cover_percent",
    "shortwave_radiation_w_m2",
    "wind_speed_kmh",
    "precipitation_mm",
    # Operational
    "occupancy_percent",
    # Time
    "hour",
    "day_of_week",
    "month",
    "day_of_year",
    "is_weekend",
    # Cyclical time
    "hour_sin",
    "hour_cos",
    "day_sin",
    "day_cos",
    # Historical energy
    "energy_lag_1",
    "energy_lag_24",
    "energy_lag_168",
    # Rolling history
    "energy_rolling_24_mean",
    "energy_rolling_168_mean",
]

TARGET = "energy"


# =========================================================
# LOAD DATA
# =========================================================


def load_ml_data():

    data = pd.read_csv(
        DATA_PATH,
        parse_dates=["timestamp"],
    )

    data = data.sort_values("timestamp").reset_index(drop=True)

    return data


# =========================================================
# TRAIN / TEST SPLIT
# =========================================================


def chronological_split(
    data,
    train_ratio=0.80,
):

    # Split by timestamp instead of raw row position.
    # This prevents the same timestamp appearing in both
    # training and testing sets.

    unique_timestamps = (
        data["timestamp"].drop_duplicates().sort_values().reset_index(drop=True)
    )

    split_index = int(len(unique_timestamps) * train_ratio)

    split_timestamp = unique_timestamps.iloc[split_index]

    train_data = data[data["timestamp"] < split_timestamp].copy()

    test_data = data[data["timestamp"] >= split_timestamp].copy()

    return (
        train_data,
        test_data,
        split_timestamp,
    )


# =========================================================
# PREPARE FEATURES
# =========================================================


def prepare_features(
    train_data,
    test_data,
):

    X_train = train_data[FEATURES].copy()

    y_train = train_data[TARGET].copy()

    X_test = test_data[FEATURES].copy()

    y_test = test_data[TARGET].copy()

    return (
        X_train,
        X_test,
        y_train,
        y_test,
    )


# =========================================================
# TRAIN MODEL
# =========================================================


def train_energy_forecast_model(
    X_train,
    y_train,
):

    model = RandomForestRegressor(
        n_estimators=150,
        max_depth=18,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )

    model.fit(
        X_train,
        y_train,
    )

    return model


# =========================================================
# METRICS
# =========================================================


def calculate_metrics(
    y_true,
    predictions,
):

    mae = mean_absolute_error(
        y_true,
        predictions,
    )

    rmse = np.sqrt(
        mean_squared_error(
            y_true,
            predictions,
        )
    )

    r2 = r2_score(
        y_true,
        predictions,
    )

    return {
        "MAE": mae,
        "RMSE": rmse,
        "R2": r2,
    }


# =========================================================
# BASELINE
# =========================================================


def evaluate_weekly_baseline(
    test_data,
):

    # Simple persistence forecast:
    # same building, same hour,
    # one week earlier.

    baseline_predictions = test_data["energy_lag_168"]

    metrics = calculate_metrics(
        test_data[TARGET],
        baseline_predictions,
    )

    return metrics


# =========================================================
# FEATURE IMPORTANCE
# =========================================================


def get_feature_importance(
    model,
):

    importance = pd.DataFrame(
        {
            "feature": FEATURES,
            "importance": model.feature_importances_,
        }
    )

    importance = importance.sort_values(
        "importance",
        ascending=False,
    ).reset_index(drop=True)

    return importance


# =========================================================
# SAVE MODEL
# =========================================================


def save_model(model):

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    package = {
        "model": model,
        "features": FEATURES,
        "target": TARGET,
    }

    with open(
        MODEL_PATH,
        "wb",
    ) as file:

        pickle.dump(
            package,
            file,
        )


# =========================================================
# LOAD SAVED MODEL
# =========================================================


def load_model():
    import joblib
    try:
        return joblib.load(MODEL_PATH)
    except Exception:
        with open(MODEL_PATH, "rb") as file:
            return pickle.load(file)


# =========================================================
# FORECAST
# =========================================================


def forecast_energy_demand(
    model,
    feature_dataframe,
):

    return model.predict(feature_dataframe[FEATURES])


# =========================================================
# MAIN
# =========================================================


def main():

    print("=" * 60)
    print("SMART ENERGY AI - ENERGY FORECAST MODEL")
    print("=" * 60)

    # -----------------------------------------------------
    # Load
    # -----------------------------------------------------

    data = load_ml_data()

    print(
        "\nDataset rows:",
        len(data),
    )

    print(
        "Date range:",
        data["timestamp"].min(),
        "->",
        data["timestamp"].max(),
    )

    # -----------------------------------------------------
    # Chronological split
    # -----------------------------------------------------

    (
        train_data,
        test_data,
        split_timestamp,
    ) = chronological_split(data)

    print(
        "\nSplit timestamp:",
        split_timestamp,
    )

    print(
        "Training rows:",
        len(train_data),
    )

    print(
        "Testing rows:",
        len(test_data),
    )

    print(
        "\nTraining range:",
        train_data["timestamp"].min(),
        "->",
        train_data["timestamp"].max(),
    )

    print(
        "Testing range:",
        test_data["timestamp"].min(),
        "->",
        test_data["timestamp"].max(),
    )

    # Safety check
    assert train_data["timestamp"].max() < test_data["timestamp"].min()

    # -----------------------------------------------------
    # Prepare
    # -----------------------------------------------------

    (
        X_train,
        X_test,
        y_train,
        y_test,
    ) = prepare_features(
        train_data,
        test_data,
    )

    # -----------------------------------------------------
    # Baseline
    # -----------------------------------------------------

    baseline_metrics = evaluate_weekly_baseline(test_data)

    print("\n" + "=" * 60)

    print("WEEKLY BASELINE")

    print("=" * 60)

    print(f"MAE  : " f"{baseline_metrics['MAE']:.4f}")

    print(f"RMSE : " f"{baseline_metrics['RMSE']:.4f}")

    print(f"R²   : " f"{baseline_metrics['R2']:.4f}")

    # -----------------------------------------------------
    # Train Random Forest
    # -----------------------------------------------------

    print("\nTraining Random Forest...")

    model = train_energy_forecast_model(
        X_train,
        y_train,
    )

    # -----------------------------------------------------
    # Predict
    # -----------------------------------------------------

    predictions = model.predict(X_test)

    model_metrics = calculate_metrics(
        y_test,
        predictions,
    )

    print("\n" + "=" * 60)

    print("RANDOM FOREST RESULTS")

    print("=" * 60)

    print(f"MAE  : " f"{model_metrics['MAE']:.4f}")

    print(f"RMSE : " f"{model_metrics['RMSE']:.4f}")

    print(f"R²   : " f"{model_metrics['R2']:.4f}")

    # -----------------------------------------------------
    # Comparison
    # -----------------------------------------------------

    improvement = (
        (baseline_metrics["MAE"] - model_metrics["MAE"]) / baseline_metrics["MAE"] * 100
    )

    print("\nMAE improvement over baseline:" f" {improvement:.2f}%")

    # -----------------------------------------------------
    # Feature importance
    # -----------------------------------------------------

    importance = get_feature_importance(model)

    print("\nTop 10 Features:")

    print(importance.head(10).to_string(index=False))

    # -----------------------------------------------------
    # Save predictions
    # -----------------------------------------------------

    results = test_data[
        [
            "timestamp",
            "building_id",
            TARGET,
        ]
    ].copy()

    results["predicted_energy"] = predictions

    results["absolute_error"] = (results[TARGET] - results["predicted_energy"]).abs()

    prediction_path = DATA_PATH.parent / "energy_forecast_results.csv"

    results.to_csv(
        prediction_path,
        index=False,
    )

    # -----------------------------------------------------
    # Save model
    # -----------------------------------------------------

    save_model(model)

    print("\nModel saved:")

    print(MODEL_PATH)

    print("\nPredictions saved:")

    print(prediction_path)

    print("\n" + "=" * 60)

    print("ENERGY FORECAST MODEL COMPLETE")

    print("=" * 60)


if __name__ == "__main__":
    main()
