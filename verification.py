"""
Smart Energy AI - Action Verification

Simulates post-action verification.

Compares:
- Expected load without action
- Expected reduction
- Simulated observed load after action
- Actual achieved reduction
- Performance against expected result

No real equipment is controlled.
"""

from pathlib import Path

import numpy as np
import pandas as pd

# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data" / "processed"

ACTIONS_PATH = DATA_DIR / "optimized_actions.csv"

OUTPUT_PATH = DATA_DIR / "verification_results.csv"

SIMULATION_PATH = DATA_DIR / "simulation_results.csv"

# One verification record per (timestamp, candidate action).
# Used when an alternative action is approved after replanning.
ACTION_VERIFICATION_PATH = DATA_DIR / "verification_by_action.csv"


# =========================================================
# SETTINGS
# =========================================================

RANDOM_SEED = 42

# Simulated real-world execution uncertainty
EXECUTION_MIN_FACTOR = 0.75
EXECUTION_MAX_FACTOR = 1.05

# If achieved reduction is at least 80%
# of expected reduction -> successful
SUCCESS_THRESHOLD = 0.80

np.random.seed(RANDOM_SEED)


# =========================================================
# LOAD ACTIONS
# =========================================================


def load_actions():

    return pd.read_csv(
        ACTIONS_PATH,
        parse_dates=["timestamp"],
    )


# =========================================================
# SIMULATE APPROVAL
# =========================================================


def simulate_human_approval(
    actions,
):

    data = actions.copy()

    # Prototype only:
    # simulate approval so verification can be tested.
    #
    # In final integration, this value will come
    # from the human approval UI.

    data["approval_status"] = "APPROVED"

    return data


# =========================================================
# SIMULATE EXECUTION
# =========================================================


def simulate_execution(row, execution_factor=None):

    expected_reduction = row["estimated_reduction_kw"]

    if execution_factor is None:
        execution_factor = np.random.uniform(
            EXECUTION_MIN_FACTOR,
            EXECUTION_MAX_FACTOR,
        )

    achieved_reduction = expected_reduction * execution_factor

    observed_load = max(
        row["original_predicted_load"] - achieved_reduction,
        0,
    )

    return (
        execution_factor,
        achieved_reduction,
        observed_load,
    )


# =========================================================
# VERIFY ONE ACTION
# =========================================================


def verify_action(row, execution_factor=None):

    (
        execution_factor,
        achieved_reduction,
        observed_load,
    ) = simulate_execution(row, execution_factor)

    expected_reduction = row["estimated_reduction_kw"]

    if expected_reduction > 0:

        performance_ratio = achieved_reduction / expected_reduction

    else:

        performance_ratio = 0.0

    if performance_ratio >= SUCCESS_THRESHOLD:

        verification_status = "SUCCESS"

        needs_replanning = False

    else:

        verification_status = "UNDERPERFORMED"

        needs_replanning = True

    return {
        "timestamp": row["timestamp"],
        "event_severity": row["event_severity"],
        "executed_action": row["recommended_action"],
        "approval_status": row["approval_status"],
        "expected_load_without_action": round(
            row["original_predicted_load"],
            2,
        ),
        "expected_reduction_kw": round(
            expected_reduction,
            2,
        ),
        "expected_load_after_action": round(
            row["new_predicted_load"],
            2,
        ),
        "execution_factor": round(
            execution_factor,
            3,
        ),
        "achieved_reduction_kw": round(
            achieved_reduction,
            2,
        ),
        "observed_load_after_action": round(
            observed_load,
            2,
        ),
        "performance_ratio_percent": round(
            performance_ratio * 100,
            2,
        ),
        "verification_status": verification_status,
        "needs_replanning": needs_replanning,
    }


# =========================================================
# VERIFY APPROVED ACTIONS
# =========================================================


def verify_actions(actions):

    records = []

    approved = actions[actions["approval_status"] == "APPROVED"]

    for _, row in approved.iterrows():

        result = verify_action(row)

        records.append(result)

    return pd.DataFrame(records)


# =========================================================
# MAIN
# =========================================================


def main():

    print("=" * 60)
    print("SMART ENERGY AI - ACTION VERIFICATION")
    print("=" * 60)

    actions = load_actions()

    print(
        "\nRecommendations:",
        len(actions),
    )

    # Prototype human approval
    actions = simulate_human_approval(actions)

    print(
        "Approved actions:",
        (actions["approval_status"] == "APPROVED").sum(),
    )

    # -----------------------------------------------------
    # Verification
    # -----------------------------------------------------

    results = verify_actions(actions)

    print(
        "Verified actions:",
        len(results),
    )

    # -----------------------------------------------------
    # Status distribution
    # -----------------------------------------------------

    print("\nVerification status:")

    print(results["verification_status"].value_counts())

    # -----------------------------------------------------
    # Replanning
    # -----------------------------------------------------

    replanning_count = results["needs_replanning"].sum()

    print(
        "\nActions requiring replanning:",
        replanning_count,
    )

    # -----------------------------------------------------
    # Average performance
    # -----------------------------------------------------

    print("Average performance:")

    print(f"{results['performance_ratio_percent'].mean():.2f}%")

    # -----------------------------------------------------
    # By action
    # -----------------------------------------------------

    print("\nPerformance by action:")

    summary = (
        results.groupby("executed_action")
        .agg(
            count=(
                "executed_action",
                "size",
            ),
            avg_expected_reduction=(
                "expected_reduction_kw",
                "mean",
            ),
            avg_achieved_reduction=(
                "achieved_reduction_kw",
                "mean",
            ),
            avg_performance_percent=(
                "performance_ratio_percent",
                "mean",
            ),
        )
        .round(2)
    )

    print(summary.to_string())

    # -----------------------------------------------------
    # Sample
    # -----------------------------------------------------

    print("\nSample verification results:")

    print(results.head(10).to_string(index=False))

    # -----------------------------------------------------
    # Save
    # -----------------------------------------------------

    results.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print(
        "\nSaved:",
        OUTPUT_PATH,
    )

    print("\n" + "=" * 60)

    print("ACTION VERIFICATION COMPLETE")

    print("=" * 60)


# =========================================================
# PER-ACTION VERIFICATION (for replanned alternatives)
# =========================================================


def _stable_execution_factor(timestamp, action):
    """
    Deterministic execution factor for one (timestamp, action).

    Uses its own seeded generator, so it never touches the global
    NumPy random state that verify_actions() relies on.
    """

    import hashlib

    key = f"{pd.Timestamp(timestamp).isoformat()}|{action}|{RANDOM_SEED}"
    seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16)
    rng = np.random.default_rng(seed)

    return float(rng.uniform(EXECUTION_MIN_FACTOR, EXECUTION_MAX_FACTOR))


def verify_candidate_actions(simulations):
    """
    Verify every simulated candidate action with the same logic
    and threshold as verify_action().
    """

    records = []

    for _, sim in simulations.iterrows():

        row = {
            "timestamp": sim["timestamp"],
            "event_severity": sim["event_severity"],
            "recommended_action": sim["action"],
            "approval_status": "APPROVED",
            "original_predicted_load": sim["original_predicted_load"],
            "estimated_reduction_kw": sim["estimated_reduction_kw"],
            "new_predicted_load": sim["new_predicted_load"],
        }

        factor = _stable_execution_factor(sim["timestamp"], sim["action"])

        records.append(verify_action(row, execution_factor=factor))

    return pd.DataFrame(records)


def build_action_verifications():

    simulations = pd.read_csv(
        SIMULATION_PATH,
        parse_dates=["timestamp"],
    )

    results = verify_candidate_actions(simulations)

    results.to_csv(
        ACTION_VERIFICATION_PATH,
        index=False,
    )

    print(
        "Saved per-action verification:",
        ACTION_VERIFICATION_PATH,
        f"({len(results)} records)",
    )

    return results


if __name__ == "__main__":
    import sys

    if "--by-action-only" in sys.argv:
        build_action_verifications()
    else:
        main()
        build_action_verifications()
