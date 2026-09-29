"""
Smart Energy AI - Incident Report Service

No Flask imports.

Builds a factual incident report from the exact snapshot returned
by app.service.snapshot().
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import re

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe(value: Any, default: str = "—") -> str:
    if value is None or value == "":
        return default
    return str(value)


def _compact_timestamp(timestamp: Any) -> str:
    text = _safe(timestamp, "unknown")
    return re.sub(r"[^0-9A-Za-z]+", "", text)


def _action_label(candidate: dict) -> str:
    return str(candidate.get("label") or candidate.get("action") or "Unknown action")


def _candidate_reduction_percent(
    candidate: dict,
    forecast_kw: Optional[float],
) -> Optional[float]:

    existing = _num(candidate.get("reduction_percent"))

    if existing is not None:
        return existing

    reduction = _num(candidate.get("estimated_reduction_kw"))

    if reduction is not None and forecast_kw is not None and forecast_kw != 0:
        return reduction / forecast_kw * 100.0

    return None


def _build_decisions(
    history: list,
    last_decision: Optional[dict],
) -> list[dict]:

    decisions = []

    for entry in history or []:
        message = str(entry.get("message", ""))

        lowered = message.lower()

        if "approved" in lowered or "rejected" in lowered:
            decisions.append(
                {
                    "time": entry.get("time"),
                    "decision": ("APPROVED" if "approved" in lowered else "REJECTED"),
                    "message": message,
                    "operator": "Operator",
                }
            )

    if last_decision:
        decisions.append(
            {
                "time": last_decision.get("time"),
                "decision": last_decision.get("decision"),
                "message": (
                    f"{last_decision.get('decision', '—')} "
                    f"{last_decision.get('action', '')}".strip()
                ),
                "operator": "Operator",
            }
        )

    # Remove exact duplicates.
    unique = []
    seen = set()

    for item in decisions:
        key = (
            item.get("time"),
            item.get("decision"),
            item.get("message"),
        )

        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


def build_report(
    snapshot: dict,
    explanation: Optional[dict] = None,
) -> dict:

    if not snapshot or not snapshot.get("event"):
        raise ValueError("No incident to report. Run an analysis first.")

    event = snapshot.get("event") or {}
    problem = snapshot.get("problem") or {}
    evidence = snapshot.get("evidence") or {}
    candidates = snapshot.get("candidate_actions") or []
    recommendation = snapshot.get("recommendation") or {}
    verification_log = snapshot.get("verification_log") or []
    history = snapshot.get("history") or []

    timestamp = event.get("timestamp")

    generated_at = datetime.now().isoformat(timespec="seconds")

    report_id = (
        f"incident_"
        f"{_compact_timestamp(timestamp)}_"
        f"{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )

    forecast_kw = _num(recommendation.get("original_predicted_load"))

    candidate_rows = []

    for candidate in candidates:
        reduction = _num(candidate.get("estimated_reduction_kw"))

        explanation_data = candidate.get("explanation") or {}

        candidate_rows.append(
            {
                "label": _action_label(candidate),
                "reduction_kw": reduction,
                "reduction_percent": (
                    _candidate_reduction_percent(
                        candidate,
                        forecast_kw,
                    )
                ),
                "score": _num(candidate.get("optimization_score")),
                "constraints": candidate.get("passes_constraints"),
                "verdict": explanation_data.get("title"),
                "points": explanation_data.get("points") or [],
            }
        )

    verification_rows = []

    for item in verification_log:
        verification_rows.append(
            {
                "time": item.get("time"),
                "intended_action": item.get("intended_label")
                or item.get("intended_action"),
                "verified_action": item.get("verified_label")
                or item.get("verified_action"),
                "expected_reduction_kw": _num(item.get("expected_reduction_kw")),
                "achieved_reduction_kw": _num(item.get("achieved_reduction_kw")),
                "performance_percent": _num(item.get("performance_ratio_percent")),
                "threshold_percent": _num(item.get("threshold_percent")),
                "status": item.get("verification_status"),
            }
        )

    timeline = []

    for entry in history:
        timeline.append(
            {
                "time": entry.get("time"),
                "state": entry.get("state"),
                "message": entry.get("message"),
            }
        )

    report = {
        "report_id": report_id,
        "generated_at": generated_at,
        "agent_id": snapshot.get("agent_id"),
        "final_state": snapshot.get("state"),
        "execution_mode": "SIMULATED",
        "event": {
            "type": event.get("event_type"),
            "building": event.get("building_id"),
            "timestamp": event.get("timestamp"),
            "severity": event.get("severity"),
            "headline": problem.get("headline"),
            "facts": problem.get("facts") or [],
            "value": problem.get("value"),
            "value_meaning": problem.get("value_meaning"),
        },
        "evidence": {
            "totals": {
                "energy_kw": evidence.get("energy_kw"),
                "hvac_kw": evidence.get("hvac_kw"),
                "solar_kw": evidence.get("solar_kw"),
                "ev_kw": evidence.get("ev_kw"),
                "occupancy_pct": evidence.get("occupancy_pct"),
                "history_count": evidence.get("history_count"),
            },
            "per_building": evidence.get("per_building") or [],
            "reading_time": evidence.get("reading_time"),
            "grid": evidence.get("grid"),
        },
        "candidates": candidate_rows,
        "recommendation": {
            "label": recommendation.get("label"),
            "reduction_kw": _num(recommendation.get("estimated_reduction_kw")),
            "reduction_percent": _num(recommendation.get("reduction_percent")),
            "source": recommendation.get("source"),
            "reason_points": (recommendation.get("reason") or {}).get("points") or [],
            "basis": (recommendation.get("reason") or {}).get("basis"),
        },
        "decisions": _build_decisions(
            history,
            snapshot.get("last_decision"),
        ),
        "verification": verification_rows,
        "timeline": timeline,
        "lime": explanation,
        "disclaimers": ["Execution was simulated; no equipment was controlled."]
        + (
            ["LIME explains model predictions, not physical causes."]
            if explanation
            else []
        ),
    }

    return report


def to_markdown(report: dict) -> str:

    lines = []

    lines.append(f"# Incident Report — {report['report_id']}")
    lines.append("")

    lines.append("## Header")
    lines.append("")
    lines.append(f"- **Report ID:** {report['report_id']}")
    lines.append(f"- **Generated at:** {report['generated_at']}")
    lines.append(f"- **Agent:** {_safe(report.get('agent_id'))}")
    lines.append(f"- **Final state:** {_safe(report.get('final_state'))}")
    lines.append(f"- **Execution mode:** {report.get('execution_mode', 'SIMULATED')}")
    lines.append("")

    event = report["event"]

    lines.append("## Event")
    lines.append("")
    lines.append(f"- **Type:** {_safe(event.get('type'))}")
    lines.append(f"- **Building:** {_safe(event.get('building'))}")
    lines.append(f"- **Timestamp:** {_safe(event.get('timestamp'))}")
    lines.append(f"- **Severity:** {_safe(event.get('severity'))}")
    lines.append(f"- **Headline:** {_safe(event.get('headline'))}")
    lines.append(f"- **Value:** {_safe(event.get('value'))}")
    lines.append(f"- **Value meaning:** {_safe(event.get('value_meaning'))}")

    if event.get("facts"):
        lines.append("")
        lines.append("### Facts")
        for fact in event["facts"]:
            lines.append(f"- {fact}")

    lines.append("")

    evidence = report["evidence"]

    lines.append("## Evidence")
    lines.append("")

    totals = evidence.get("totals") or {}

    lines.append("| Energy kW | HVAC kW | Solar kW | EV kW | Occupancy % | History |")
    lines.append("|---:|---:|---:|---:|---:|---:|")
    lines.append(
        "| "
        f"{_safe(totals.get('energy_kw'))} | "
        f"{_safe(totals.get('hvac_kw'))} | "
        f"{_safe(totals.get('solar_kw'))} | "
        f"{_safe(totals.get('ev_kw'))} | "
        f"{_safe(totals.get('occupancy_pct'))} | "
        f"{_safe(totals.get('history_count'))} |"
    )

    lines.append("")
    lines.append(f"Reading time: {_safe(evidence.get('reading_time'))}")

    grid = evidence.get("grid") or {}

    if grid:
        lines.append(f"Grid: {_safe(grid.get('description') or grid.get('status'))}")

    lines.append("")
    lines.append("### Per-building")
    lines.append("")
    lines.append("| Building | Energy kW | HVAC kW | Occupancy % | Solar kW | EV kW |")
    lines.append("|---|---:|---:|---:|---:|---:|")

    for item in evidence.get("per_building") or []:
        lines.append(
            "| "
            f"{_safe(item.get('building_id'))} | "
            f"{_safe(item.get('energy_kw'))} | "
            f"{_safe(item.get('hvac_kw'))} | "
            f"{_safe(item.get('occupancy_pct'))} | "
            f"{_safe(item.get('solar_kw'))} | "
            f"{_safe(item.get('ev_kw'))} |"
        )

    lines.append("")

    lines.append("## Candidates")
    lines.append("")
    lines.append(
        "| Action | Reduction kW | % of forecast | Score | Constraints | Verdict |"
    )
    lines.append("|---|---:|---:|---:|---|---|")

    for candidate in report["candidates"]:
        constraints = candidate.get("constraints")

        if constraints is True:
            constraint_text = "PASS"
        elif constraints is False:
            constraint_text = "FAIL"
        else:
            constraint_text = "—"

        lines.append(
            "| "
            f"{_safe(candidate.get('label'))} | "
            f"{_safe(candidate.get('reduction_kw'))} | "
            f"{_safe(candidate.get('reduction_percent'))} | "
            f"{_safe(candidate.get('score'))} | "
            f"{constraint_text} | "
            f"{_safe(candidate.get('verdict'))} |"
        )

        for point in candidate.get("points") or []:
            lines.append(f"  - {point}")

    lines.append("")

    recommendation = report["recommendation"]

    lines.append("## Recommendation")
    lines.append("")
    lines.append(f"- **Action:** {_safe(recommendation.get('label'))}")
    lines.append(f"- **Reduction:** {_safe(recommendation.get('reduction_kw'))} kW")
    lines.append(
        f"- **Reduction %:** {_safe(recommendation.get('reduction_percent'))}%"
    )
    lines.append(f"- **Source:** {_safe(recommendation.get('source'))}")
    lines.append(f"- **Basis:** {_safe(recommendation.get('basis'))}")

    for point in recommendation.get("reason_points") or []:
        lines.append(f"- {point}")

    lines.append("")

    lines.append("## Decisions")
    lines.append("")
    lines.append("| Time | Operator | Decision | Message |")
    lines.append("|---|---|---|---|")

    for decision in report["decisions"]:
        lines.append(
            "| "
            f"{_safe(decision.get('time'))} | "
            f"Operator | "
            f"{_safe(decision.get('decision'))} | "
            f"{_safe(decision.get('message'))} |"
        )

    lines.append("")

    lines.append("## Verification")
    lines.append("")
    lines.append(
        "| Time | Intended | Verified | Expected kW | Achieved kW | Performance % | Threshold % | Status |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---|")

    for item in report["verification"]:
        lines.append(
            "| "
            f"{_safe(item.get('time'))} | "
            f"{_safe(item.get('intended_action'))} | "
            f"{_safe(item.get('verified_action'))} | "
            f"{_safe(item.get('expected_reduction_kw'))} | "
            f"{_safe(item.get('achieved_reduction_kw'))} | "
            f"{_safe(item.get('performance_percent'))} | "
            f"{_safe(item.get('threshold_percent'))} | "
            f"{_safe(item.get('status'))} |"
        )

    lines.append("")

    lines.append("## Timeline")
    lines.append("")
    lines.append("| Time | State | Message |")
    lines.append("|---|---|---|")

    for item in report["timeline"]:
        lines.append(
            "| "
            f"{_safe(item.get('time'))} | "
            f"{_safe(item.get('state'))} | "
            f"{_safe(item.get('message'))} |"
        )

    lines.append("")

    lime = report.get("lime")

    if lime:
        lines.append("## LIME Explanation")
        lines.append("")
        lines.append(
            "LIME explains the forecasting model's reasoning, not the real-world cause."
        )
        lines.append("")

        explanations = (
            lime.get("buildings") if lime.get("building_id") == "CAMPUS" else [lime]
        )

        for item in explanations or []:
            lines.append(f"### {item.get('building_id')}")
            lines.append("")
            lines.append(f"- Predicted: {_safe(item.get('predicted_kw'))} kW")
            lines.append(f"- Actual: {_safe(item.get('actual_kw'))} kW")
            lines.append(f"- Local fit R²: {_safe(item.get('lime_score'))}")
            lines.append("")
            lines.append("| Feature | Condition | Weight kW | Direction | Value |")
            lines.append("|---|---|---:|---|---:|")

            for contribution in item.get("contributions") or []:
                lines.append(
                    "| "
                    f"{_safe(contribution.get('feature'))} | "
                    f"{_safe(contribution.get('condition'))} | "
                    f"{_safe(contribution.get('weight_kw'))} | "
                    f"{_safe(contribution.get('direction'))} | "
                    f"{_safe(contribution.get('value'))} |"
                )

            lines.append("")

    lines.append("## Disclaimers")
    lines.append("")

    for disclaimer in report.get("disclaimers") or []:
        lines.append(f"- {disclaimer}")

    lines.append("")

    return "\n".join(lines)


def save_report(
    report: dict,
    markdown: str,
) -> Path:

    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = REPORTS_DIR / (f"{report['report_id']}.md")

    path.write_text(
        markdown,
        encoding="utf-8",
    )

    return path
