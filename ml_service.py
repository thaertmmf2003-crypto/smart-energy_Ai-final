"""
Smart Energy AI - ML Service Layer

Provides a clean interface between:
- Data / ML pipeline
- AI Agent
- Backend

The Agent should use these functions instead of
reading processed CSV files directly.
"""

from pathlib import Path

import pandas as pd

# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data" / "processed"

EVENTS_PATH = DATA_DIR / "prediction_events.csv"

SIMULATION_PATH = DATA_DIR / "simulation_results.csv"

ACTIONS_PATH = DATA_DIR / "optimized_actions.csv"

VERIFICATION_PATH = DATA_DIR / "verification_results.csv"

ACTION_VERIFICATION_PATH = DATA_DIR / "verification_by_action.csv"


# =========================================================
# HELPERS
# =========================================================


def _load_csv(path):

    if not path.exists():
        raise FileNotFoundError(f"Required ML output not found: {path}")

    return pd.read_csv(
        path,
        parse_dates=["timestamp"],
    )


def _normalize_timestamp(timestamp):

    return pd.Timestamp(timestamp)


def _records_to_dict(dataframe):

    data = dataframe.copy()

    if "timestamp" in data.columns:

        data["timestamp"] = data["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    return data.to_dict(orient="records")


# =========================================================
# EVENTS
# =========================================================


def get_prediction_events(
    event_type=None,
    severity=None,
    limit=None,
):

    data = _load_csv(EVENTS_PATH)

    if event_type is not None:

        data = data[data["event_type"] == event_type]

    if severity is not None:

        data = data[data["severity"] == severity]

    data = data.sort_values("timestamp")

    if limit is not None:

        data = data.head(limit)

    return _records_to_dict(data)


def get_peak_events(
    severity=None,
    limit=None,
):

    return get_prediction_events(
        event_type="PEAK_DEMAND_RISK",
        severity=severity,
        limit=limit,
    )


def get_energy_anomalies(
    severity=None,
    limit=None,
):

    return get_prediction_events(
        event_type="ENERGY_ANOMALY",
        severity=severity,
        limit=limit,
    )


# =========================================================
# EVENT LOOKUP
# =========================================================


def get_events_at_timestamp(
    timestamp,
):

    timestamp = _normalize_timestamp(timestamp)

    data = _load_csv(EVENTS_PATH)

    data = data[data["timestamp"] == timestamp]

    return _records_to_dict(data)


# =========================================================
# DIGITAL TWIN RESULTS
# =========================================================


def get_simulation_for_event(
    timestamp,
):

    timestamp = _normalize_timestamp(timestamp)

    data = _load_csv(SIMULATION_PATH)

    data = data[data["timestamp"] == timestamp].copy()

    if data.empty:
        return []

    data = data.sort_values(
        "estimated_reduction_kw",
        ascending=False,
    )

    return _records_to_dict(data)


# =========================================================
# RECOMMENDED ACTION
# =========================================================


def get_recommended_action(
    timestamp,
):

    timestamp = _normalize_timestamp(timestamp)

    data = _load_csv(ACTIONS_PATH)

    result = data[data["timestamp"] == timestamp]

    if result.empty:
        return None

    return _records_to_dict(result.head(1))[0]


# =========================================================
# VERIFICATION RESULT
# =========================================================


def get_verification_result(
    timestamp,
):

    timestamp = _normalize_timestamp(timestamp)

    data = _load_csv(VERIFICATION_PATH)

    result = data[data["timestamp"] == timestamp]

    if result.empty:
        return None

    return _records_to_dict(result.head(1))[0]


def get_verification_for_action(
    timestamp,
    action,
):
    """
    Verification record for one specific action at an event.

    The optimizer's recommended action keeps its original record
    from verification_results.csv. Any other candidate (for example
    an alternative chosen during replanning) is read from
    verification_by_action.csv.

    Returns None if no record exists for that action.
    """

    original = get_verification_result(timestamp)

    if original and original.get("executed_action") == action:
        return original

    if not ACTION_VERIFICATION_PATH.exists():
        return None

    timestamp = _normalize_timestamp(timestamp)

    data = _load_csv(ACTION_VERIFICATION_PATH)

    result = data[
        (data["timestamp"] == timestamp)
        & (data["executed_action"] == action)
    ]

    if result.empty:
        return None

    return _records_to_dict(result.head(1))[0]


# =========================================================
# REPLANNING EVENTS
# =========================================================


def get_replanning_events(
    limit=None,
):

    data = _load_csv(VERIFICATION_PATH)

    data = data[data["needs_replanning"] == True].copy()

    data = data.sort_values("timestamp")

    if limit is not None:

        data = data.head(limit)

    return _records_to_dict(data)


# =========================================================
# AGENT CONTEXT
# =========================================================


def get_event_context(
    timestamp,
):
    """
    Returns pre-approval information
    available to the Agent.

    Verification is intentionally excluded
    because it happens only after approval
    and simulated execution.
    """

    return {
        "events": get_events_at_timestamp(timestamp),
        "candidate_actions": get_simulation_for_event(timestamp),
        "recommendation": get_recommended_action(timestamp),
    }


# =========================================================
# SYSTEM SUMMARY
# =========================================================


def get_ml_summary():

    events = _load_csv(EVENTS_PATH)

    simulations = _load_csv(SIMULATION_PATH)

    actions = _load_csv(ACTIONS_PATH)

    verification = _load_csv(VERIFICATION_PATH)

    success_count = verification["verification_status"].eq("SUCCESS").sum()

    underperformed_count = (
        verification["verification_status"].eq("UNDERPERFORMED").sum()
    )

    return {
        "total_events": int(len(events)),
        "energy_anomalies": int((events["event_type"] == "ENERGY_ANOMALY").sum()),
        "peak_demand_events": int((events["event_type"] == "PEAK_DEMAND_RISK").sum()),
        "candidate_simulations": int(len(simulations)),
        "optimized_actions": int(len(actions)),
        "successful_actions": int(success_count),
        "underperformed_actions": int(underperformed_count),
        "replanning_required": int(verification["needs_replanning"].sum()),
    }


# =========================================================
# TEST
# =========================================================


def main():

    print("=" * 60)
    print("SMART ENERGY AI - ML SERVICE TEST")
    print("=" * 60)

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print("\nML Summary:")

    summary = get_ml_summary()

    for key, value in summary.items():

        print(f"{key}: {value}")

    # -----------------------------------------------------
    # Get one peak event
    # -----------------------------------------------------

    peak_events = get_peak_events(limit=1)

    if not peak_events:

        print("\nNo peak events found.")

        return

    event = peak_events[0]

    timestamp = event["timestamp"]

    print("\nSelected event:")

    print(event)

    # -----------------------------------------------------
    # Complete Agent context
    # -----------------------------------------------------

    context = get_event_context(timestamp)

    print("\nCandidate actions:")

    for action in context["candidate_actions"]:

        print(
            action["action"],
            "| Reduction:",
            action["estimated_reduction_kw"],
        )

    print("\nRecommended action:")

    print(context["recommendation"])

    # -----------------------------------------------------
    # Replanning
    # -----------------------------------------------------

    replanning = get_replanning_events(limit=3)

    print("\nReplanning sample:")

    for item in replanning:

        print(
            item["timestamp"],
            "|",
            item["executed_action"],
            "| Performance:",
            item["performance_ratio_percent"],
            "%",
        )

    print("\n" + "=" * 60)

    print("ML SERVICE TEST COMPLETE")

    print("=" * 60)


if __name__ == "__main__":
    main()
