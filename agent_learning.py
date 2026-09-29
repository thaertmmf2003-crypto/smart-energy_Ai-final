"""
agent_learning.py — a confidence signal learned from the agent's own history.

Why this exists
---------------
The optimizer ranks actions by a fixed score: reduction x weight minus
disruption x penalty. It has no memory. If EV shifts have underperformed
every time they were tried, the optimizer would still rank the next EV shift
exactly the same way.

This module reads the recorded verification history (verification_by_action.csv)
and measures, per action type, how often it actually met its target. That
success rate becomes a confidence multiplier the dashboard can show next to
each candidate — "this action worked 39% of the time before" — so an operator
sees the track record, not just the projected kW.

Design choice: this is an ADDITIVE signal. It does NOT change which action the
agent selects; the selection logic in optimizer.py and agent.py is untouched,
so the demo's deterministic story still holds. What it adds is a re-ranking
*view*: how the candidates would order if confidence were folded in. That makes
the learning loop visible and auditable without silently overriding the agent.

Read-only. No files are written and no equipment is controlled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
VERIFICATION_PATH = BASE_DIR / "data" / "processed" / "verification_by_action.csv"

# How much the confidence signal is allowed to move a score, at most. The
# multiplier ranges over [1 - SPAN, 1] so a perfect record leaves the score
# unchanged and a poor record discounts it. Kept small so confidence tempers
# the ranking rather than dominating it.
CONFIDENCE_SPAN = 0.40

ACTION_LABELS = {
    "HVAC_SETPOINT_ADJUSTMENT": "HVAC setpoint adjustment",
    "EV_CHARGING_SHIFT": "EV charging shift",
    "BATTERY_DISCHARGE": "Battery discharge",
    "COMBINED_ACTION": "Combined action",
}


class LearningUnavailable(Exception):
    """Raised when the history file is missing or empty."""


def _confidence_from_rate(success_rate: float) -> float:
    """
    Map a success rate in [0, 1] to a score multiplier in [1 - SPAN, 1].

    A 100% record -> 1.0 (no penalty). A 0% record -> 1 - SPAN.
    """
    return (1.0 - CONFIDENCE_SPAN) + CONFIDENCE_SPAN * max(0.0, min(1.0, success_rate))


def action_stats() -> Dict[str, Dict[str, Any]]:
    """
    Per-action success rate and confidence multiplier from recorded history.
    """
    if not VERIFICATION_PATH.exists():
        raise LearningUnavailable("verification_by_action.csv not found.")

    data = pd.read_csv(VERIFICATION_PATH)
    if data.empty or "executed_action" not in data.columns:
        raise LearningUnavailable("No verification history to learn from.")

    stats: Dict[str, Dict[str, Any]] = {}
    for action, group in data.groupby("executed_action"):
        attempts = int(len(group))
        successes = int((group["verification_status"] == "SUCCESS").sum())
        rate = successes / attempts if attempts else 0.0
        stats[str(action)] = {
            "action": str(action),
            "label": ACTION_LABELS.get(str(action), str(action)),
            "attempts": attempts,
            "successes": successes,
            "success_rate_percent": round(rate * 100, 1),
            "confidence_multiplier": round(_confidence_from_rate(rate), 3),
        }
    return stats


def summary() -> Dict[str, Any]:
    """History-wide view: per-action stats, best and worst performers."""
    stats = action_stats()
    ordered = sorted(
        stats.values(), key=lambda s: s["success_rate_percent"], reverse=True
    )
    total_attempts = sum(s["attempts"] for s in ordered)
    total_success = sum(s["successes"] for s in ordered)
    best = ordered[0] if ordered else None
    worst = ordered[-1] if ordered else None

    finding = None
    if best and worst and best["action"] != worst["action"]:
        finding = (
            f"Across {total_attempts} recorded executions, "
            f"{best['label']} met its target most often "
            f"({best['success_rate_percent']}%), and {worst['label']} least "
            f"often ({worst['success_rate_percent']}%). Confidence weighting "
            "discounts the actions with the weaker track record."
        )

    return {
        "actions": ordered,
        "total_attempts": total_attempts,
        "total_successes": total_success,
        "overall_success_percent": (
            round(total_success / total_attempts * 100, 1) if total_attempts else 0.0
        ),
        "best": best,
        "worst": worst,
        "confidence_span": CONFIDENCE_SPAN,
        "finding": finding,
        "note": (
            "Learned from recorded verification history. This is an additive "
            "confidence signal shown alongside the optimizer score; it does "
            "not change which action the agent selects."
        ),
    }


def apply_to_candidates(
    candidates: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Attach a confidence multiplier and confidence-weighted score to each
    candidate, and return them ordered by that weighted score.

    The input list is not mutated; callers use this for a 'how it would
    re-rank' view. Missing history degrades gracefully to no change.
    """
    items = list(candidates or [])
    try:
        stats = action_stats()
    except LearningUnavailable:
        return items

    out: List[Dict[str, Any]] = []
    for c in items:
        action = c.get("action")
        stat = stats.get(action)
        enriched = dict(c)
        if stat:
            mult = stat["confidence_multiplier"]
            base = c.get("optimization_score")
            enriched["confidence_percent"] = stat["success_rate_percent"]
            enriched["confidence_multiplier"] = mult
            if isinstance(base, (int, float)):
                enriched["confidence_weighted_score"] = round(base * mult, 2)
        out.append(enriched)

    out.sort(
        key=lambda c: c.get("confidence_weighted_score", c.get("optimization_score", 0)),
        reverse=True,
    )
    return out


if __name__ == "__main__":
    import json

    print(json.dumps(summary(), indent=2, ensure_ascii=False))
