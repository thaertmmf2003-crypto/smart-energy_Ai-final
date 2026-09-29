"""
Smart Energy AI - Digital Twin Simulator

Simulates operational actions before execution.

Actions:
- HVAC_SETPOINT_ADJUSTMENT
- EV_CHARGING_SHIFT
- BATTERY_DISCHARGE
- COMBINED_ACTION

This module does NOT control real equipment.
All actions are simulated.
"""

from pathlib import Path

import pandas as pd

# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data" / "processed"

FORECAST_PATH = DATA_DIR / "energy_forecast_results.csv"

HVAC_PATH = DATA_DIR / "hvac_readings.csv"

EV_PATH = DATA_DIR / "ev_charging.csv"

BATTERY_PATH = DATA_DIR / "battery_readings.csv"

EVENTS_PATH = DATA_DIR / "prediction_events.csv"

OUTPUT_PATH = DATA_DIR / "simulation_results.csv"


# =========================================================
# SIMULATION PARAMETERS
# =========================================================

# Simulated reduction from a temporary HVAC adjustment
HVAC_REDUCTION_PERCENT = 15.0

# Fraction of active EV charging that can be shifted
EV_SHIFT_PERCENT = 80.0

# Maximum simulated battery discharge
MAX_BATTERY_DISCHARGE_KW = 25.0


# =========================================================
# LOAD DATA
# =========================================================


def load_data():

    forecast = pd.read_csv(
        FORECAST_PATH,
        parse_dates=["timestamp"],
    )

    hvac = pd.read_csv(
        HVAC_PATH,
        parse_dates=["timestamp"],
    )

    ev = pd.read_csv(
        EV_PATH,
        parse_dates=["timestamp"],
    )

    battery = pd.read_csv(
        BATTERY_PATH,
        parse_dates=["timestamp"],
    )

    events = pd.read_csv(
        EVENTS_PATH,
        parse_dates=["timestamp"],
    )

    return (
        forecast,
        hvac,
        ev,
        battery,
        events,
    )


# =========================================================
# GET CAMPUS STATE
# =========================================================


def get_campus_state(
    timestamp,
    forecast,
    hvac,
    ev,
    battery,
):

    forecast_now = forecast[forecast["timestamp"] == timestamp]

    hvac_now = hvac[hvac["timestamp"] == timestamp]

    ev_now = ev[ev["timestamp"] == timestamp]

    battery_now = battery[battery["timestamp"] == timestamp]

    predicted_load = forecast_now["predicted_energy"].sum()

    hvac_load = hvac_now["hvac_power_kw"].sum()

    ev_load = ev_now["ev_charging_power_kw"].sum()

    # Only B002 has a simulated battery.
    b002_battery = battery_now[battery_now["building_id"] == "B002"]

    if len(b002_battery) > 0:

        battery_soc = float(b002_battery["battery_state_of_charge_percent"].iloc[0])

    else:
        battery_soc = 0.0

    return {
        "predicted_load": predicted_load,
        "hvac_load": hvac_load,
        "ev_load": ev_load,
        "battery_soc": battery_soc,
    }


# =========================================================
# HVAC ACTION
# =========================================================


def simulate_hvac_action(state):

    reduction = state["hvac_load"] * HVAC_REDUCTION_PERCENT / 100

    new_load = max(
        state["predicted_load"] - reduction,
        0,
    )

    return {
        "action": "HVAC_SETPOINT_ADJUSTMENT",
        "estimated_reduction_kw": reduction,
        "new_predicted_load": new_load,
    }


# =========================================================
# EV ACTION
# =========================================================


def simulate_ev_action(state):

    reduction = state["ev_load"] * EV_SHIFT_PERCENT / 100

    new_load = max(
        state["predicted_load"] - reduction,
        0,
    )

    return {
        "action": "EV_CHARGING_SHIFT",
        "estimated_reduction_kw": reduction,
        "new_predicted_load": new_load,
    }


# =========================================================
# BATTERY ACTION
# =========================================================


def simulate_battery_action(state):

    # Keep a minimum SOC reserve.
    if state["battery_soc"] > 30:

        reduction = MAX_BATTERY_DISCHARGE_KW

    else:

        reduction = 0.0

    new_load = max(
        state["predicted_load"] - reduction,
        0,
    )

    return {
        "action": "BATTERY_DISCHARGE",
        "estimated_reduction_kw": reduction,
        "new_predicted_load": new_load,
    }


# =========================================================
# COMBINED ACTION
# =========================================================


def simulate_combined_action(state):

    hvac_result = simulate_hvac_action(state)

    ev_result = simulate_ev_action(state)

    battery_result = simulate_battery_action(state)

    total_reduction = (
        hvac_result["estimated_reduction_kw"]
        + ev_result["estimated_reduction_kw"]
        + battery_result["estimated_reduction_kw"]
    )

    new_load = max(
        state["predicted_load"] - total_reduction,
        0,
    )

    return {
        "action": "COMBINED_ACTION",
        "estimated_reduction_kw": total_reduction,
        "new_predicted_load": new_load,
    }


# =========================================================
# SIMULATE ALL ACTIONS
# =========================================================


def simulate_candidate_actions(state):

    return [
        simulate_hvac_action(state),
        simulate_ev_action(state),
        simulate_battery_action(state),
        simulate_combined_action(state),
    ]


# =========================================================
# MAIN
# =========================================================


def main():

    print("=" * 60)
    print("SMART ENERGY AI - DIGITAL TWIN SIMULATOR")
    print("=" * 60)

    (
        forecast,
        hvac,
        ev,
        battery,
        events,
    ) = load_data()

    # Use peak events only
    peak_events = events[events["event_type"] == "PEAK_DEMAND_RISK"].copy()

    print(
        "\nPeak events available:",
        len(peak_events),
    )

    if peak_events.empty:

        print("No peak events available " "for simulation.")

        return

    simulation_records = []

    # Simulate all peak events
    for _, event in peak_events.iterrows():

        timestamp = event["timestamp"]

        state = get_campus_state(
            timestamp,
            forecast,
            hvac,
            ev,
            battery,
        )

        actions = simulate_candidate_actions(state)

        for result in actions:

            reduction_percent = 0.0

            if state["predicted_load"] > 0:

                reduction_percent = (
                    result["estimated_reduction_kw"] / state["predicted_load"] * 100
                )

            simulation_records.append(
                {
                    "timestamp": timestamp,
                    "event_severity": event["severity"],
                    "action": result["action"],
                    "original_predicted_load": round(
                        state["predicted_load"],
                        2,
                    ),
                    "estimated_reduction_kw": round(
                        result["estimated_reduction_kw"],
                        2,
                    ),
                    "reduction_percent": round(
                        reduction_percent,
                        2,
                    ),
                    "new_predicted_load": round(
                        result["new_predicted_load"],
                        2,
                    ),
                    "battery_soc_percent": round(
                        state["battery_soc"],
                        2,
                    ),
                    "ev_load_kw": round(
                        state["ev_load"],
                        2,
                    ),
                    "hvac_load_kw": round(
                        state["hvac_load"],
                        2,
                    ),
                }
            )

    results = pd.DataFrame(simulation_records)

    results.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print(
        "Simulation rows:",
        len(results),
    )

    print("\nAverage reduction by action:")

    summary = (
        results.groupby("action")
        .agg(
            avg_reduction_kw=(
                "estimated_reduction_kw",
                "mean",
            ),
            avg_reduction_percent=(
                "reduction_percent",
                "mean",
            ),
            avg_new_load=(
                "new_predicted_load",
                "mean",
            ),
        )
        .round(2)
        .sort_values(
            "avg_reduction_kw",
            ascending=False,
        )
    )

    print(summary.to_string())

    print("\nSample simulation:")

    print(results.head(12).to_string(index=False))

    print(
        "\nSaved:",
        OUTPUT_PATH,
    )

    print("\n" + "=" * 60)

    print("DIGITAL TWIN SIMULATION COMPLETE")

    print("=" * 60)


if __name__ == "__main__":
    main()
