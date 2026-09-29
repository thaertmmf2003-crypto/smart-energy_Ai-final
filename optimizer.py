"""
Smart Energy AI - Action Optimizer

Selects the most appropriate simulated action
for each peak-demand event.

The optimizer considers:
- Event severity
- Estimated load reduction
- Battery SOC
- EV charging availability
- HVAC operational impact

No real equipment is controlled.
"""

from pathlib import Path

import pandas as pd

# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data" / "processed"

SIMULATION_PATH = DATA_DIR / "simulation_results.csv"

OUTPUT_PATH = DATA_DIR / "optimized_actions.csv"


# =========================================================
# CONSTRAINTS
# =========================================================

MIN_BATTERY_SOC = 30.0

MIN_USEFUL_REDUCTION_KW = 1.0


# =========================================================
# ACTION COST / IMPACT
# Lower = less operational disruption
# =========================================================

ACTION_IMPACT = {
    "EV_CHARGING_SHIFT": 1,
    "BATTERY_DISCHARGE": 2,
    "HVAC_SETPOINT_ADJUSTMENT": 3,
    "COMBINED_ACTION": 4,
}


# =========================================================
# LOAD DATA
# =========================================================


def load_simulation_results():

    return pd.read_csv(
        SIMULATION_PATH,
        parse_dates=["timestamp"],
    )


# =========================================================
# VALIDATE ACTION
# =========================================================


def constraint_checks(row):
    """
    Evaluate every optimizer constraint for one candidate and
    return a list of checks with a human-readable detail.

    validate_action() is defined from this function, so the
    explanation shown to operators is the same logic that
    accepts or rejects the candidate.
    """

    action = row["action"]

    reduction = row["estimated_reduction_kw"]

    uses_battery = action in [
        "BATTERY_DISCHARGE",
        "COMBINED_ACTION",
    ]

    uses_ev = action in [
        "EV_CHARGING_SHIFT",
        "COMBINED_ACTION",
    ]

    checks = []

    # Must produce a useful reduction
    checks.append(
        {
            "rule": "MIN_USEFUL_REDUCTION",
            "applies": True,
            "passed": bool(reduction >= MIN_USEFUL_REDUCTION_KW),
            "detail": (
                f"Estimated reduction {reduction:.2f} kW "
                f"(minimum {MIN_USEFUL_REDUCTION_KW:g} kW)"
            ),
        }
    )

    # Battery reserve constraint
    soc = row.get("battery_soc_percent") if hasattr(row, "get") else row["battery_soc_percent"]
    checks.append(
        {
            "rule": "BATTERY_SOC_RESERVE",
            "applies": uses_battery,
            "passed": bool(not uses_battery or soc > MIN_BATTERY_SOC),
            "detail": (
                f"Battery SOC {soc:.1f}% (must be above {MIN_BATTERY_SOC:g}%)"
                if uses_battery
                else "Not applicable: action does not use the battery"
            ),
        }
    )

    # EV shift requires active EV load
    ev_load = row.get("ev_load_kw") if hasattr(row, "get") else row["ev_load_kw"]
    checks.append(
        {
            "rule": "ACTIVE_EV_LOAD",
            "applies": uses_ev,
            "passed": bool(not uses_ev or ev_load > 0),
            "detail": (
                f"Active EV charging load {ev_load:.2f} kW (must be above 0 kW)"
                if uses_ev
                else "Not applicable: action does not shift EV charging"
            ),
        }
    )

    return checks


def validate_action(row):

    return all(check["passed"] for check in constraint_checks(row))


# =========================================================
# CALCULATE ACTION SCORE
# =========================================================


def score_breakdown(row):
    """
    Return every term of the optimization score for one candidate.

    calculate_action_score() returns breakdown["score"], so the
    explanation and the ranking always use the same numbers.
    """

    reduction = row["estimated_reduction_kw"]

    impact = ACTION_IMPACT[row["action"]]

    severity = row["event_severity"]

    # -----------------------------------------------------
    # Severity changes how aggressively we respond
    # -----------------------------------------------------

    if severity == "CRITICAL":

        # Reduction is dominant
        reduction_weight = 1.00
        impact_penalty = 2.0

    elif severity == "HIGH":

        reduction_weight = 0.90
        impact_penalty = 4.0

    else:

        # ELEVATED:
        # prefer less disruptive actions
        reduction_weight = 0.75
        impact_penalty = 6.0

    score = reduction * reduction_weight - impact * impact_penalty

    return {
        "severity": severity,
        "estimated_reduction_kw": float(reduction),
        "reduction_weight": reduction_weight,
        "reduction_term": float(reduction * reduction_weight),
        "disruption_rank": impact,
        "impact_penalty": impact_penalty,
        "penalty_term": float(impact * impact_penalty),
        "score": float(score),
    }


def calculate_action_score(row):

    return score_breakdown(row)["score"]


# =========================================================
# SELECT BEST ACTION
# =========================================================


def select_best_action(
    event_group,
):

    candidates = event_group.copy()

    candidates["is_valid"] = candidates.apply(
        validate_action,
        axis=1,
    )

    candidates = candidates[candidates["is_valid"]].copy()

    if candidates.empty:
        return None

    candidates["optimization_score"] = candidates.apply(
        calculate_action_score,
        axis=1,
    )

    candidates = candidates.sort_values(
        [
            "optimization_score",
            "estimated_reduction_kw",
        ],
        ascending=[
            False,
            False,
        ],
    )

    return candidates.iloc[0]


# =========================================================
# BUILD RECOMMENDATION
# =========================================================


def build_recommendation(row):

    action = row["action"]

    if action == "EV_CHARGING_SHIFT":

        return "Temporarily shift flexible EV " "charging to a later period."

    if action == "BATTERY_DISCHARGE":

        return "Discharge the simulated campus " "battery during the peak period."

    if action == "HVAC_SETPOINT_ADJUSTMENT":

        return "Apply a temporary simulated HVAC " "setpoint adjustment."

    if action == "COMBINED_ACTION":

        return "Apply a coordinated simulated " "HVAC, EV charging and battery action."

    return "No recommendation available."


# =========================================================
# OPTIMIZE ALL EVENTS
# =========================================================


def optimize_actions(
    simulation_data,
):

    recommendations = []

    grouped = simulation_data.groupby("timestamp")

    for timestamp, group in grouped:

        best = select_best_action(group)

        if best is None:
            continue

        recommendations.append(
            {
                "timestamp": timestamp,
                "event_severity": best["event_severity"],
                "recommended_action": best["action"],
                "original_predicted_load": round(
                    best["original_predicted_load"],
                    2,
                ),
                "estimated_reduction_kw": round(
                    best["estimated_reduction_kw"],
                    2,
                ),
                "reduction_percent": round(
                    best["reduction_percent"],
                    2,
                ),
                "new_predicted_load": round(
                    best["new_predicted_load"],
                    2,
                ),
                "optimization_score": round(
                    best["optimization_score"],
                    2,
                ),
                "battery_soc_percent": round(
                    best["battery_soc_percent"],
                    2,
                ),
                "recommendation": build_recommendation(best),
                # Human-in-the-loop
                "approval_status": "PENDING",
            }
        )

    return pd.DataFrame(recommendations)


# =========================================================
# MAIN
# =========================================================


def main():

    print("=" * 60)
    print("SMART ENERGY AI - ACTION OPTIMIZER")
    print("=" * 60)

    simulation_data = load_simulation_results()

    print(
        "\nSimulation rows:",
        len(simulation_data),
    )

    recommendations = optimize_actions(simulation_data)

    print(
        "Optimized events:",
        len(recommendations),
    )

    # -----------------------------------------------------
    # Distribution
    # -----------------------------------------------------

    print("\nRecommended action distribution:")

    print(recommendations["recommended_action"].value_counts())

    # -----------------------------------------------------
    # By severity
    # -----------------------------------------------------

    print("\nActions by severity:")

    severity_table = pd.crosstab(
        recommendations["event_severity"],
        recommendations["recommended_action"],
    )

    print(severity_table.to_string())

    # -----------------------------------------------------
    # Average impact
    # -----------------------------------------------------

    print("\nAverage recommended reduction:")

    print(f"{recommendations['estimated_reduction_kw'].mean():.2f}")

    print("Average reduction percentage:")

    print(f"{recommendations['reduction_percent'].mean():.2f}%")

    # -----------------------------------------------------
    # Sample
    # -----------------------------------------------------

    print("\nSample recommendations:")

    print(recommendations.head(10).to_string(index=False))

    # -----------------------------------------------------
    # Save
    # -----------------------------------------------------

    recommendations.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print(
        "\nSaved:",
        OUTPUT_PATH,
    )

    print("\n" + "=" * 60)

    print("ACTION OPTIMIZATION COMPLETE")

    print("=" * 60)


if __name__ == "__main__":
    main()
