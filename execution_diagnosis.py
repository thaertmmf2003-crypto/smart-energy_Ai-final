"""
execution_diagnosis.py — why an approved action missed its target.

The problem this solves
-----------------------
verification.py decides success with a random draw:

    execution_factor = np.random.uniform(0.75, 1.05)

So the record says an action reached 77.9% of its target and nothing anywhere
says why. A dashboard that invented a cause for that number would be making it
up. This module does not invent one. It measures what actually changed.

How it works
------------
A plan is built from the readings at the event hour H. Execution is measured
over the following hour. Every action carries an explicit assumption about what
the load will do:

    HVAC setpoint      HVAC falls to 85% of its level at H
    EV charging shift  EV charging falls to 20% of its level at H
    Battery discharge  the battery supplies a flat 25 kW
    Combined           all three at once

Each assumption is a number that can be checked against the reading an hour
later. Where the reading sits above the planned level, that gap is a real,
measured reason the action delivered less than it promised — and it is stated in
kW, with the operational context (occupancy, temperature, solar) that came with
it.

What this module will not do
----------------------------
It reports only what the readings support. When the measured drivers do not add
up to the shortfall in the verification record, it says so rather than padding
the difference, because the record's own number came from a random draw and
there may be nothing physical behind part of it.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("smart_energy_ai.execution_diagnosis")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "processed"

# The same assumptions simulator.py plans against. Imported below when possible
# so the two can never drift apart; these are the fallback.
_HVAC_REDUCTION_PERCENT = 15.0
_EV_SHIFT_PERCENT = 80.0
_MAX_BATTERY_DISCHARGE_KW = 25.0
_MIN_BATTERY_SOC = 30.0

try:
    from simulator import (
        EV_SHIFT_PERCENT as _EV_SHIFT_PERCENT,
        HVAC_REDUCTION_PERCENT as _HVAC_REDUCTION_PERCENT,
        MAX_BATTERY_DISCHARGE_KW as _MAX_BATTERY_DISCHARGE_KW,
    )
except Exception:  # noqa: BLE001 - keep the fallback values
    pass

# Which components each action actually moves.
ACTION_COMPONENTS = {
    "HVAC_SETPOINT_ADJUSTMENT": ["hvac"],
    "EV_CHARGING_SHIFT": ["ev"],
    "BATTERY_DISCHARGE": ["battery"],
    "COMBINED_ACTION": ["hvac", "ev", "battery"],
}

# A gap smaller than this is rounding, not a finding worth reporting.
MATERIAL_KW = 0.5

_LOCK = threading.Lock()
_FRAMES: Optional[Dict[str, Any]] = None


class DiagnosisUnavailable(RuntimeError):
    """Raised with a readable reason when the readings cannot support a diagnosis."""


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _load_frames() -> Dict[str, Any]:
    """Load the same reading files simulator.py plans against, once."""
    global _FRAMES

    with _LOCK:
        if _FRAMES is not None:
            return _FRAMES

        import pandas as pd

        wanted = {
            "hvac": ("hvac_readings.csv", "hvac_power_kw"),
            "ev": ("ev_charging.csv", "ev_charging_power_kw"),
            "battery": ("battery_readings.csv", "battery_state_of_charge_percent"),
            "solar": ("solar_readings.csv", "solar_generation_kw"),
            "occupancy": ("occupancy.csv", "occupancy_percent"),
        }

        frames: Dict[str, Any] = {}
        missing: List[str] = []

        for key, (filename, column) in wanted.items():
            path = DATA_DIR / filename
            if not path.exists():
                missing.append(filename)
                continue
            frame = pd.read_csv(path, usecols=["timestamp", "building_id", column])
            frame["timestamp"] = frame["timestamp"].astype(str)
            frames[key] = frame

        if missing:
            raise DiagnosisUnavailable(
                "Reading files are missing, so the execution hour cannot be "
                f"compared with the plan: {', '.join(missing)}."
            )

        _FRAMES = frames
        return _FRAMES


def _at(frame, timestamp: str, column: str, building: Optional[str] = None):
    """Campus total for one column at one hour, or one building's value."""
    rows = frame[frame["timestamp"] == timestamp]
    if building and building != "CAMPUS":
        rows = rows[rows["building_id"] == building]
    if rows.empty:
        return None
    return float(rows[column].sum())


def _per_building(frame, timestamp: str, column: str) -> Dict[str, float]:
    rows = frame[frame["timestamp"] == timestamp]
    return {
        str(r["building_id"]): float(r[column])
        for _, r in rows.iterrows()
        if r[column] == r[column]  # drop NaN
    }


def _next_hour(timestamp: str) -> str:
    return (
        dt.datetime.fromisoformat(str(timestamp)) + dt.timedelta(hours=1)
    ).strftime("%Y-%m-%d %H:%M:%S")


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN


# ---------------------------------------------------------------------------
# Context: what the operational conditions did between the two hours
# ---------------------------------------------------------------------------


def _hvac_context(frames, plan_hour: str, exec_hour: str) -> Optional[str]:
    """
    Name the building that actually drove the HVAC overrun, with its occupancy.

    Picking the largest occupancy swing on its own gets this wrong: a building
    emptying out swings furthest while its HVAC falls, which is the opposite of
    what needs explaining. So find the building whose HVAC rose most, then report
    that building's occupancy.
    """
    hvac_before = _per_building(frames["hvac"], plan_hour, "hvac_power_kw")
    hvac_after = _per_building(frames["hvac"], exec_hour, "hvac_power_kw")

    risers = [
        (bid, hvac_after[bid] - hvac_before[bid])
        for bid in hvac_before
        if bid in hvac_after and hvac_after[bid] > hvac_before[bid]
    ]
    if not risers:
        return None

    bid, rise = max(risers, key=lambda item: item[1])
    if rise < MATERIAL_KW:
        return None

    occ_before = _per_building(frames["occupancy"], plan_hour, "occupancy_percent")
    occ_after = _per_building(frames["occupancy"], exec_hour, "occupancy_percent")

    line = f"{_building_label(bid)} drove it: its HVAC rose {rise:.1f} kW"

    if bid in occ_before and bid in occ_after:
        shift = occ_after[bid] - occ_before[bid]
        if abs(shift) >= 10:
            direction = "risen" if shift > 0 else "fallen"
            line += (
                f", with occupancy there having {direction} from "
                f"{occ_before[bid]:.0f}% to {occ_after[bid]:.0f}%"
            )

    return line + "."


def _building_label(building_id: str) -> str:
    try:
        from config import BUILDINGS

        return BUILDINGS.get(building_id, {}).get("building_name", building_id)
    except Exception:  # noqa: BLE001
        return building_id


def _solar_driver(frames, plan_hour: str, exec_hour: str, building: str) -> Optional[Dict[str, Any]]:
    """
    Solar is not something the action controls, but a drop in it raises the load
    the action is measured against, so it belongs in the explanation.
    """
    before = _at(frames["solar"], plan_hour, "solar_generation_kw", building)
    after = _at(frames["solar"], exec_hour, "solar_generation_kw", building)
    if before is None or after is None:
        return None

    lost = before - after
    if lost < MATERIAL_KW:
        return None

    return {
        "component": "solar",
        "label": "Solar generation fell away",
        "planned_kw": round(before, 2),
        "actual_kw": round(after, 2),
        "delta_kw": round(lost, 2),
        "controllable": False,
        "detail": (
            f"Solar was generating {before:.1f} kW when the plan was made and "
            f"{after:.1f} kW an hour later. That {lost:.1f} kW has to come from "
            "the grid instead, working against the reduction."
        ),
    }


# ---------------------------------------------------------------------------
# Drivers: where each component of the action stood against its own assumption
# ---------------------------------------------------------------------------


def _hvac_driver(frames, plan_hour, exec_hour, building) -> Optional[Dict[str, Any]]:
    before = _at(frames["hvac"], plan_hour, "hvac_power_kw", building)
    after = _at(frames["hvac"], exec_hour, "hvac_power_kw", building)
    if before is None or after is None:
        return None

    planned_level = before * (1 - _HVAC_REDUCTION_PERCENT / 100)
    gap = after - planned_level

    context = _hvac_context(frames, plan_hour, exec_hour)

    if gap < MATERIAL_KW:
        return {
            "component": "hvac",
            "label": "HVAC held to plan",
            "planned_kw": round(planned_level, 2),
            "actual_kw": round(after, 2),
            "delta_kw": round(max(gap, 0.0), 2),
            "controllable": True,
            "held": True,
            "detail": (
                f"The setpoint change was planned to bring HVAC down to "
                f"{planned_level:.1f} kW. It ran at {after:.1f} kW, at or below plan."
            ),
        }

    return {
        "component": "hvac",
        "label": "HVAC demand ran above the plan",
        "planned_kw": round(planned_level, 2),
        "actual_kw": round(after, 2),
        "delta_kw": round(gap, 2),
        "controllable": True,
        "held": False,
        "detail": (
            f"Raising the setpoint was planned to bring HVAC from {before:.1f} kW "
            f"down to {planned_level:.1f} kW, a {_HVAC_REDUCTION_PERCENT:.0f}% cut. "
            f"An hour later HVAC was drawing {after:.1f} kW — {gap:.1f} kW above "
            "the level the reduction was sized against."
        ),
        "context": context,
    }


def _ev_driver(frames, plan_hour, exec_hour, building) -> Optional[Dict[str, Any]]:
    before = _at(frames["ev"], plan_hour, "ev_charging_power_kw", building)
    after = _at(frames["ev"], exec_hour, "ev_charging_power_kw", building)
    if before is None or after is None:
        return None

    planned_level = before * (1 - _EV_SHIFT_PERCENT / 100)
    gap = after - planned_level

    if before <= 0:
        return {
            "component": "ev",
            "label": "Nothing was charging to defer",
            "planned_kw": 0.0,
            "actual_kw": round(after, 2),
            "delta_kw": round(max(gap, 0.0), 2),
            "controllable": True,
            "held": gap < MATERIAL_KW,
            "detail": (
                "No EV charging was running when the plan was made, so the shift "
                "had nothing to defer."
                + (
                    f" Charging then started and reached {after:.1f} kW during the "
                    "execution hour."
                    if gap >= MATERIAL_KW
                    else ""
                )
            ),
        }

    if gap < MATERIAL_KW:
        return {
            "component": "ev",
            "label": "EV charging deferred as planned",
            "planned_kw": round(planned_level, 2),
            "actual_kw": round(after, 2),
            "delta_kw": round(max(gap, 0.0), 2),
            "controllable": True,
            "held": True,
            "detail": (
                f"Charging was planned to drop to {planned_level:.1f} kW and ran "
                f"at {after:.1f} kW."
            ),
        }

    # The case an operator will recognise: cars kept arriving.
    return {
        "component": "ev",
        "label": "Extra load appeared at the charging points",
        "planned_kw": round(planned_level, 2),
        "actual_kw": round(after, 2),
        "delta_kw": round(gap, 2),
        "controllable": True,
        "held": False,
        "detail": (
            f"Deferring {_EV_SHIFT_PERCENT:.0f}% of the {before:.1f} kW that was "
            f"charging should have left {planned_level:.1f} kW on the chargers. "
            f"An hour later they were drawing {after:.1f} kW — {gap:.1f} kW more "
            "than planned, so new charging replaced what was deferred."
        ),
    }


def _battery_driver(frames, plan_hour, exec_hour, building) -> Optional[Dict[str, Any]]:
    # Only B002 carries a battery in this campus, and the simulator plans
    # against its state of charge alone.
    before = _at(frames["battery"], plan_hour, "battery_state_of_charge_percent", "B002")
    after = _at(frames["battery"], exec_hour, "battery_state_of_charge_percent", "B002")
    if before is None:
        return None

    if before <= _MIN_BATTERY_SOC:
        return {
            "component": "battery",
            "label": "Battery below its reserve",
            "planned_kw": 0.0,
            "actual_kw": 0.0,
            "delta_kw": round(_MAX_BATTERY_DISCHARGE_KW, 2),
            "controllable": True,
            "held": False,
            "detail": (
                f"State of charge was {before:.1f}%, at or below the "
                f"{_MIN_BATTERY_SOC:.0f}% reserve, so no discharge was available."
            ),
        }

    if after is None:
        return None

    drop = before - after
    if drop >= MATERIAL_KW / 10:  # any real discharge shows as an SOC drop
        return {
            "component": "battery",
            "label": "Battery discharged as planned",
            "planned_kw": round(_MAX_BATTERY_DISCHARGE_KW, 2),
            "actual_kw": round(_MAX_BATTERY_DISCHARGE_KW, 2),
            "delta_kw": 0.0,
            "controllable": True,
            "held": True,
            "detail": (
                f"State of charge fell from {before:.1f}% to {after:.1f}%, "
                "consistent with the planned discharge."
            ),
        }

    return {
        "component": "battery",
        "label": "Battery did not discharge",
        "planned_kw": round(_MAX_BATTERY_DISCHARGE_KW, 2),
        "actual_kw": 0.0,
        "delta_kw": round(_MAX_BATTERY_DISCHARGE_KW, 2),
        "controllable": True,
        "held": False,
        "detail": (
            f"State of charge held at {before:.1f}% through the execution hour, "
            f"so the planned {_MAX_BATTERY_DISCHARGE_KW:.0f} kW never left the battery."
        ),
    }


_DRIVERS = {"hvac": _hvac_driver, "ev": _ev_driver, "battery": _battery_driver}


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


def diagnose(
    timestamp: str,
    action: str,
    expected_reduction_kw: Optional[float] = None,
    achieved_reduction_kw: Optional[float] = None,
    building_id: str = "CAMPUS",
) -> Dict[str, Any]:
    """
    Explain, from the readings, why an action delivered less than it promised.

    Raises DiagnosisUnavailable with a readable reason when the hours needed are
    not in the data. Never guesses: every kW quoted is a measured difference
    between the plan's own assumption and the reading an hour later.
    """
    frames = _load_frames()

    plan_hour = str(timestamp).strip()
    try:
        exec_hour = _next_hour(plan_hour)
    except ValueError as exc:
        raise DiagnosisUnavailable(f"Unreadable timestamp {timestamp!r}.") from exc

    if _at(frames["hvac"], exec_hour, "hvac_power_kw") is None:
        raise DiagnosisUnavailable(
            f"No readings exist for {exec_hour}, the hour the action would have "
            "run in, so there is nothing to compare the plan against."
        )

    components = ACTION_COMPONENTS.get(action)
    if components is None:
        raise DiagnosisUnavailable(f"Unknown action {action!r}.")

    drivers: List[Dict[str, Any]] = []
    for name in components:
        driver = _DRIVERS[name](frames, plan_hour, exec_hour, building_id)
        if driver:
            drivers.append(driver)

    solar = _solar_driver(frames, plan_hour, exec_hour, building_id)
    if solar:
        drivers.append(solar)

    shortfall_drivers = [d for d in drivers if d["delta_kw"] >= MATERIAL_KW]
    shortfall_drivers.sort(key=lambda d: d["delta_kw"], reverse=True)
    measured_kw = round(sum(d["delta_kw"] for d in shortfall_drivers), 2)

    expected = _num(expected_reduction_kw)
    achieved = _num(achieved_reduction_kw)
    gap = round(expected - achieved, 2) if expected is not None and achieved is not None else None

    # Idea #1 — an execution factor grounded in the readings, not the coin toss.
    # verification.py sets execution_factor with np.random.uniform, so the
    # recorded "achieved" carries no cause. The measured overruns above give a
    # data-backed alternative: what the plan promised, minus what the readings
    # show slipped, over what the plan promised. This is offered as a comparison,
    # not written back into the pipeline.
    measured_factor = None
    recorded_factor = None
    if expected and expected > 0:
        measured_factor = round(max(0.0, expected - measured_kw) / expected, 3)
        if achieved is not None:
            recorded_factor = round(achieved / expected, 3)

    return {
        "available": True,
        "plan_hour": plan_hour,
        "execution_hour": exec_hour,
        "action": action,
        "expected_reduction_kw": expected,
        "achieved_reduction_kw": achieved,
        "gap_kw": gap,
        "drivers": shortfall_drivers,
        "held": [d for d in drivers if d["delta_kw"] < MATERIAL_KW],
        "measured_kw": measured_kw,
        "measured_execution_factor": measured_factor,
        "recorded_execution_factor": recorded_factor,
        "headline": _headline(shortfall_drivers, measured_kw, gap),
        "coverage": _coverage(measured_kw, gap),
    }


def _headline(drivers: List[Dict[str, Any]], measured_kw: float, gap: Optional[float]) -> str:
    if not drivers:
        return (
            "Every part of the action held to its plan in the readings for that "
            "hour. Nothing measurable explains the shortfall."
        )

    top = drivers[0]
    if len(drivers) == 1:
        return f"{top['label']}: {top['delta_kw']:.1f} kW against plan."

    others = len(drivers) - 1
    return (
        f"{top['label']} ({top['delta_kw']:.1f} kW against plan), "
        f"plus {others} other factor{'s' if others > 1 else ''} "
        f"totalling {measured_kw:.1f} kW."
    )


def _coverage(measured_kw: float, gap: Optional[float]) -> str:
    """
    State plainly how much of the recorded shortfall the readings account for.

    The recorded shortfall comes from verification.py's random execution factor,
    so the two are not expected to match. Saying so is more useful than a number
    that looks precise and is not.
    """
    if gap is None:
        return (
            f"The readings show {measured_kw:.1f} kW of load running above what "
            "the plan assumed."
        )

    if gap <= 0:
        return "The action met or beat its target, so there is no shortfall to explain."

    if measured_kw <= 0:
        return (
            f"The verification record puts the shortfall at {gap:.1f} kW, but the "
            "readings for that hour show every component at or below its planned "
            "level. Nothing in the data accounts for it."
        )

    if measured_kw > gap * 1.2:
        # More load ran above plan than the record's shortfall. That is not a
        # contradiction to paper over: the record's number comes from a random
        # execution factor, so the conditions that hour were harder than it says.
        return (
            f"The readings show {measured_kw:.1f} kW of load running above what "
            f"the plan assumed — more than the {gap:.1f} kW shortfall the "
            "verification record reports. Conditions that hour were harder than "
            "the recorded number suggests."
        )

    share = measured_kw / gap * 100
    if share >= 80:
        return (
            f"The readings account for {measured_kw:.1f} kW of the {gap:.1f} kW "
            "shortfall."
        )
    if share >= 30:
        return (
            f"The readings account for {measured_kw:.1f} kW of the {gap:.1f} kW "
            f"shortfall ({share:.0f}%). The remainder is not visible in the data."
        )
    return (
        f"The readings account for only {measured_kw:.1f} kW of the {gap:.1f} kW "
        "shortfall. Most of it is not visible in the readings for that hour."
    )


def availability() -> Dict[str, Any]:
    """Whether a diagnosis can be produced at all, without raising."""
    try:
        _load_frames()
    except DiagnosisUnavailable as exc:
        return {"available": False, "reason": str(exc)}
    return {"available": True, "reason": None}
