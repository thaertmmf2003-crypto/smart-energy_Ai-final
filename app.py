"""
Smart Energy AI - Web Application (Flask)

Responsibility:
    HTTP API + dashboard rendering. Nothing else.

    - Orchestration and the state machine stay in agent.py (SmartEnergyAgent).
    - Data access goes through tools.py (which wraps database.py / ml_service.py).
    - Constraint checks and scores shown for candidates come from optimizer.py.
    - Knowledge answers come from rag_service.py.

    This module adds only presentation helpers (problem summary, factual
    recommendation explanation, evidence roll-up) and an application-level
    AgentService that keeps ONE agent instance alive across HTTP requests so
    handle_event() and process_approval() can run in separate requests.

Run:
    python app.py            ->  http://127.0.0.1:5000
"""

from __future__ import annotations
from page_routes import pages
import datetime as dt
import logging
import math
import os
import sys
import threading
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------
# Console safety: agent.py prints characters such as "✓" and "→".
# On some Windows consoles (cp1252) that raises UnicodeEncodeError,
# which would surface as a failed HTTP request. Replace instead.
# ---------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional at runtime
    pass

from flask import Flask, jsonify, render_template, request, send_file, session, redirect, url_for, flash
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from auth import auth_bp, get_current_user

import ml_explainer
import report_service
import api_guard
import execution_diagnosis
import security
import tools

# Additive analysis layers (hackathon ideas). Imported defensively so a
# problem in any one of them degrades that feature to a 503 rather than
# stopping the whole app from booting.
try:
    import impact_translation
except Exception as _exc:  # pragma: no cover - defensive
    impact_translation = None
    _IMPACT_IMPORT_ERROR = str(_exc)
else:
    _IMPACT_IMPORT_ERROR = None

try:
    import holiday_audit
except Exception as _exc:  # pragma: no cover - defensive
    holiday_audit = None
    _HOLIDAY_IMPORT_ERROR = str(_exc)
else:
    _HOLIDAY_IMPORT_ERROR = None

try:
    import agent_learning
except Exception as _exc:  # pragma: no cover - defensive
    agent_learning = None
    _LEARNING_IMPORT_ERROR = str(_exc)
else:
    _LEARNING_IMPORT_ERROR = None
import live_simulator
import database
from agent import AgentState, SmartEnergyAgent

try:
    from config import BUILDINGS as CONFIG_BUILDINGS
except ImportError:
    CONFIG_BUILDINGS = {}

# Optimizer: reuse its constraint check and scoring for display only.
try:
    import optimizer as _optimizer

    OPTIMIZER_AVAILABLE = True
except Exception:  # noqa: BLE001
    _optimizer = None
    OPTIMIZER_AVAILABLE = False

# Verification threshold (display only). verification.py seeds numpy's global
# RNG on import; that has no effect on the web app, which never samples.
try:
    from verification import SUCCESS_THRESHOLD as _SUCCESS_THRESHOLD
except Exception:  # noqa: BLE001
    _SUCCESS_THRESHOLD = None

# RAG is optional: the dashboard must start even if it cannot load.
try:
    from rag_service import rag_service

    RAG_IMPORT_ERROR = None
except Exception as _exc:  # noqa: BLE001
    rag_service = None
    RAG_IMPORT_ERROR = str(_exc)


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("smart_energy_ai.app")

app = Flask(__name__)

# The session cookie is signed with this key. A value committed to the
# repository lets anyone who reads it forge a signed session and sign in as any
# user, including admin, so there is no safe default to fall back on. In
# development a random key is generated per start: sessions do not survive a
# restart, which is the correct trade for not shipping a known key.
_secret = os.getenv("SECRET_KEY")
if not _secret:
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("PORT"):
        raise RuntimeError(
            "SECRET_KEY is not set. Add it to the deployment's environment "
            "variables before starting; sessions cannot be signed without it."
        )
    _secret = os.urandom(32).hex()
    log.warning(
        "SECRET_KEY is not set. Using a random key for this run only — "
        "logins will not survive a restart. Set SECRET_KEY in .env."
    )

app.secret_key = _secret
app.permanent_session_lifetime = dt.timedelta(days=7)
app.json.sort_keys = False

# Reverse proxy support (Railway, Heroku, AWS, Cloudflare)
# Corrects request.scheme and request.is_secure so HTTPS is always recognized
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.register_blueprint(pages)
app.register_blueprint(auth_bp)

# Every /api/ endpoint needs a signed-in user. The pages were already gated;
# the JSON API was not, which left /api/agent/approve callable by anyone.
api_guard.apply(app, get_current_user)

# تهيئة جداول المصادقة والمستخدمين وتفعيل نمط WAL
database.init_auth_tables()


@app.context_processor
def inject_user():
    return {"current_user": get_current_user()}


@app.before_request
def enforce_https_redirect():
    """Ensure all cloud/production traffic is strictly upgraded to HTTPS."""
    host = request.host.split(":")[0]
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.endswith(".local"):
        return None

    proto = request.headers.get("X-Forwarded-Proto", request.scheme or "http").lower()
    if proto == "http":
        secure_url = request.url.replace("http://", "https://", 1)
        return redirect(secure_url, code=301)
    return None


# Response headers, CSP, HSTS, and request size cap.
is_cloud_prod = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("PORT") or not os.getenv("FLASK_DEBUG"))
security.apply(
    app,
    force_https=os.getenv("FORCE_HTTPS", "true" if is_cloud_prod else "false").lower() in {"1", "true", "yes", "on"},
    enabled=os.getenv("SECURITY_HEADERS", "on").lower() not in {"0", "off", "false", "no"},
)

# =========================================================
# CONSTANTS / LABELS
# =========================================================

BUILDING_IDS = ["B001", "B002", "B003"]

ACTION_LABELS = {
    "HVAC_SETPOINT_ADJUSTMENT": "HVAC setpoint adjustment",
    "EV_CHARGING_SHIFT": "Shift EV charging",
    "BATTERY_DISCHARGE": "Battery discharge",
    "COMBINED_ACTION": "Combined HVAC, EV and battery action",
}

EVENT_LABELS = {
    "ENERGY_ANOMALY": "Energy anomaly",
    "PEAK_DEMAND_RISK": "Peak demand risk",
}

SEVERITY_RANK = {"CRITICAL": 3, "HIGH": 2, "ELEVATED": 1, "LOW": 0, "NORMAL": 0}

LIFECYCLE = [
    "MONITORING",
    "INVESTIGATING",
    "GATHERING_EVIDENCE",
    "ANALYZING",
    "FORECASTING",
    "SIMULATING",
    "VALIDATING",
    "WAITING_FOR_APPROVAL",
    "EXECUTING",
    "VERIFYING",
    "COMPLETED",
]


def _now() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def action_label(action: Optional[str]) -> str:
    if not action:
        return "Unknown action"
    return ACTION_LABELS.get(action, action.replace("_", " ").capitalize())


def building_name(building_id: Optional[str]) -> str:
    if building_id == "CAMPUS":
        return "Campus-wide"
    meta = CONFIG_BUILDINGS.get(building_id or "", {})
    return meta.get("building_name", building_id or "Unknown")


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def event_label(event_type: Optional[str]) -> str:
    return EVENT_LABELS.get(event_type, event_type or "Event")


def humanise_state(state: Optional[str]) -> str:
    return str(state or "—").replace("_", " ").title()


def _pdf_escape(value: Any) -> str:
    """Escape text for reportlab's mini-HTML paragraph markup."""
    return (
        str("—" if value is None else value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _round(value: Any, digits: int = 1) -> Optional[str]:
    number = _num(value)
    return None if number is None else f"{number:.{digits}f}"


def _kw(value: Any) -> Optional[str]:
    number = _num(value)
    return None if number is None else f"{number:,.1f} kW"


def _pct(value: Any) -> Optional[str]:
    number = _num(value)
    return None if number is None else f"{number:.0f}%"


def _clean(obj: Any) -> Any:
    """Make tool/ML output JSON-safe (NaN -> None, numpy -> native, Enum -> value)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_clean(v) for v in obj]
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat(sep=" ")
    if hasattr(obj, "item") and callable(obj.item):  # numpy scalar
        try:
            return _clean(obj.item())
        except Exception:  # noqa: BLE001
            return str(obj)
    return obj


def ok(data: Any, status: int = 200):
    return jsonify({"success": True, "data": _clean(data)}), status


def fail(message: str, status: int = 400):
    return jsonify({"success": False, "error": message}), status


def api(fn: Callable) -> Callable:
    """Wrap an endpoint so every failure becomes a JSON error without a stack trace."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            return fail(str(exc), 400)
        except HTTPException:
            # Werkzeug raises these for a reason and already carries the right
            # status: an oversized body is 413, not a server fault. Swallowing
            # them into the generic 500 below hides what actually happened.
            raise
        except Exception:  # noqa: BLE001
            log.exception("Unhandled error in %s", fn.__name__)
            return fail("Internal server error. See the server log for details.", 500)

    return wrapper


def _tool_data(result: Dict[str, Any], label: str) -> Any:
    """Unwrap a standard tool response or raise a readable error."""
    if not result.get("success"):
        raise RuntimeError(f"{label}: {result.get('error') or 'unavailable'}")
    return result.get("data")


def _normalize_building(value: Optional[str], allow_campus: bool = True) -> str:
    b = (value or "CAMPUS").strip().upper()
    if b in {"", "ALL"}:
        b = "CAMPUS"
    if b == "CAMPUS" and allow_campus:
        return b
    if b not in BUILDING_IDS:
        raise ValueError(f"Unknown building '{value}'. Use B001, B002, B003 or CAMPUS.")
    return b


# =========================================================
# AGENT SUBCLASS: timestamps only, behaviour unchanged
# =========================================================


class DashboardAgent(SmartEnergyAgent):
    """
    SmartEnergyAgent with wall-clock timestamps on history entries and a
    record of every state it passed through (for the lifecycle timeline).

    No lifecycle logic is overridden: handle_event() and process_approval()
    are the original implementations.
    """

    def __init__(self, agent_id: str = "Agent_Alpha"):
        super().__init__(agent_id)
        self.state_trail: List[Dict[str, str]] = [
            {"state": self.state.value, "time": _now()}
        ]

    def log_step(self, message: str) -> None:
        super().log_step(message)
        self.history[-1]["time"] = _now()

    def transition_to(self, new_state: AgentState) -> None:
        super().transition_to(new_state)
        self.state_trail.append({"state": new_state.value, "time": _now()})

    def handle_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        self.state_trail = []
        return super().handle_event(event)


# =========================================================
# PRESENTATION HELPERS (derived strictly from existing data)
# =========================================================


def build_problem_summary(
    event: Optional[Dict[str, Any]],
    evidence: Optional[Dict[str, Any]] = None,
    recommendation: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Concise, factual problem statement for the dashboard.

    Uses only fields that exist in prediction_events.csv plus the forecast
    load carried by the optimizer output. Value semantics follow
    prediction_engine.py:
        ENERGY_ANOMALY   value = residual, % of predicted demand
        PEAK_DEMAND_RISK value = predicted campus demand, % of grid import limit
    """
    if not event:
        return None

    event_type = event.get("event_type")
    severity = event.get("severity")
    value = _num(event.get("value"))
    where = building_name(event.get("building_id"))
    facts: List[str] = []

    if event_type == "ENERGY_ANOMALY" and value is not None:
        direction = "above" if value >= 0 else "below"
        headline = (
            f"{where} consumption is {abs(value):.1f}% {direction} the ML forecast"
        )
    elif event_type == "PEAK_DEMAND_RISK" and value is not None:
        headline = (
            f"Forecast campus demand reaches {value:.1f}% of the grid import limit"
        )
    else:
        headline = (
            f"{EVENT_LABELS.get(event_type, event_type or 'Event')} detected at {where}"
        )

    if event.get("description"):
        facts.append(str(event["description"]))

    forecast_load = _num((recommendation or {}).get("original_predicted_load"))
    if forecast_load is not None:
        if event.get("building_id") == "CAMPUS":
            facts.append(f"Forecast load at the event hour: {forecast_load:.1f} kW.")
        else:
            facts.append(
                f"Campus forecast load at the event hour: {forecast_load:.1f} kW "
                "(the load the optimizer planned against)."
            )

    return {
        "headline": headline,
        "facts": facts,
        "event_type": event_type,
        "event_label": EVENT_LABELS.get(event_type, event_type),
        "severity": severity,
        "building_id": event.get("building_id"),
        "building_name": where,
        "timestamp": event.get("timestamp"),
        "value": value,
        "value_meaning": (
            "Residual vs. forecast (%)"
            if event_type == "ENERGY_ANOMALY"
            else (
                "Forecast demand vs. grid import limit (%)"
                if event_type == "PEAK_DEMAND_RISK"
                else "Event value"
            )
        ),
    }


def summarize_evidence(evidence: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Roll the agent's per-building evidence up into the six dashboard tiles."""
    if not evidence:
        return None
    operational = evidence.get("operational", {}) or {}
    buildings = [b for b in BUILDING_IDS if b in operational]
    if not buildings:
        return None

    per_building = []
    for bid in buildings:
        ev = operational[bid]
        cons = ev.get("consumption", {}) or {}
        hvac = ev.get("hvac", {}) or {}
        occ = ev.get("occupancy", {}) or {}
        sol = ev.get("solar", {}) or {}
        per_building.append(
            {
                "building_id": bid,
                "building_name": building_name(bid),
                "energy_kw": _num(cons.get("energy_kw", cons.get("total_kw"))),
                "hvac_kw": _num(hvac.get("hvac_kw", cons.get("hvac_kw"))),
                "hvac_pct": _num(hvac.get("hvac_pct")),
                "occupancy_pct": _num(occ.get("occupancy_pct")),
                "solar_kw": _num(sol.get("solar_kw", sol.get("generation_kw"))),
                "ev_kw": _num(cons.get("ev_kw")),
                "temperature_c": _num(cons.get("temperature_c")),
                "history_count": ev.get("history_count"),
                "reading_time": cons.get("timestamp"),
            }
        )

    def total(key):
        vals = [p[key] for p in per_building if p[key] is not None]
        return round(sum(vals), 2) if vals else None

    occ_vals = [
        p["occupancy_pct"] for p in per_building if p["occupancy_pct"] is not None
    ]
    hist_vals = [
        p["history_count"] for p in per_building if isinstance(p["history_count"], int)
    ]
    grid = operational.get("grid") or {}

    return {
        "scope": "campus" if len(per_building) > 1 else per_building[0]["building_id"],
        "reading_time": per_building[0]["reading_time"],
        "energy_kw": total("energy_kw"),
        "hvac_kw": total("hvac_kw"),
        "solar_kw": total("solar_kw"),
        "ev_kw": total("ev_kw"),
        "occupancy_pct": round(sum(occ_vals) / len(occ_vals), 2) if occ_vals else None,
        "occupancy_is_average": len(occ_vals) > 1,
        "history_count": sum(hist_vals) if hist_vals else None,
        "grid": (
            {
                "status": grid.get("event_type"),
                "severity": grid.get("severity"),
                "grid_load_pct": _num(grid.get("grid_load_pct")),
                "price_signal": _num(grid.get("price_signal")),
                "description": grid.get("description"),
                "timestamp": grid.get("timestamp"),
            }
            if grid
            else None
        ),
        "per_building": per_building,
        "ml_events_at_timestamp": len(evidence.get("ml_events_at_timestamp", []) or []),
    }


def enrich_candidates(
    candidates: List[Dict[str, Any]], selected: Optional[str]
) -> List[Dict[str, Any]]:
    """Attach the optimizer's own constraint verdict and score to each simulated candidate."""
    enriched = []
    for c in candidates or []:
        item = dict(c)
        item["label"] = action_label(c.get("action"))
        item["is_selected"] = bool(selected) and c.get("action") == selected
        item["passes_constraints"] = None
        item["optimization_score"] = None
        item["constraint_checks"] = None
        item["score_breakdown"] = None
        if OPTIMIZER_AVAILABLE:
            try:
                item["passes_constraints"] = bool(_optimizer.validate_action(c))
                if hasattr(_optimizer, "constraint_checks"):
                    item["constraint_checks"] = _optimizer.constraint_checks(c)
                if item["passes_constraints"]:
                    item["optimization_score"] = round(
                        float(_optimizer.calculate_action_score(c)), 2
                    )
                    if hasattr(_optimizer, "score_breakdown"):
                        item["score_breakdown"] = _optimizer.score_breakdown(c)
            except Exception:  # noqa: BLE001 - missing column etc.
                pass
        enriched.append(item)
    return enriched


def explain_candidates(
    candidates: List[Dict[str, Any]],
    selected: Optional[str],
    source: str,
    verification_log: List[Dict[str, Any]],
) -> None:
    """
    Attach an 'explanation' to every candidate: why it was recommended,
    rejected, or not selected. Built only from the optimizer's own checks
    and score terms, the agent's replanning rule and verification records.
    """
    winner = next((c for c in candidates if c.get("action") == selected), None)
    missed = {
        v["intended_action"]: v for v in verification_log if v.get("needs_replanning")
    }
    passed_ver = {
        v["intended_action"]: v
        for v in verification_log
        if not v.get("needs_replanning")
    }

    for c in candidates:
        action = c.get("action")
        red = _num(c.get("estimated_reduction_kw")) or 0.0
        failed_checks = [
            k
            for k in (c.get("constraint_checks") or [])
            if k.get("applies") and not k.get("passed")
        ]
        exp: Dict[str, Any] = {
            "verdict": None,
            "title": None,
            "points": [],
            "basis": None,
        }

        if action in missed:
            v = missed[action]
            exp.update(
                verdict="missed_target",
                title="Rejected after verification",
                basis="verification.py threshold and agent.py replanning rule",
            )
            exp["points"] = [
                f"You approved it and it ran as a simulated execution.",
                f"It achieved {v['achieved_reduction_kw']:.1f} kW of the expected "
                f"{v['expected_reduction_kw']:.1f} kW ({v['performance_ratio_percent']:.1f}%).",
                f"The target is {v['threshold_percent']:.0f}% or more, so verification marked it "
                "UNDERPERFORMED and the agent excluded it when replanning.",
            ]
        elif action == selected:
            exp.update(verdict="selected", title="Recommended")
            if source == "replanning":
                exp["basis"] = "agent.py replanning rule"
                exp["points"] = [
                    "After the previous action missed its target, the agent picks the untried "
                    "candidate with the largest estimated reduction that passes the optimizer's constraints.",
                    f"This candidate has the largest remaining reduction: {red:.1f} kW.",
                ]
            else:
                exp["basis"] = "optimizer.py score and constraints"
                sb = c.get("score_breakdown")
                exp["points"] = ["It passed every optimizer constraint."]
                if sb:
                    exp["points"].append(
                        f"It has the highest optimization score ({sb['score']:.2f})."
                    )
        elif failed_checks:
            exp.update(
                verdict="failed_constraints",
                title="Rejected by optimizer constraints",
                basis="optimizer.py constraint checks",
            )
            exp["points"] = [f"Failed: {k['detail']}." for k in failed_checks]
            exp["points"].append(
                "A candidate that fails any constraint is never recommended, "
                "whatever its simulated reduction."
            )
        elif action in passed_ver:
            exp.update(verdict="verified", title="Executed and verified")
            exp["points"] = [
                "This action was approved, executed in simulation and met its target."
            ]
        elif source == "replanning" and winner is not None:
            w_red = _num(winner.get("estimated_reduction_kw")) or 0.0
            exp.update(
                verdict="not_selected",
                title="Not selected during replanning",
                basis="agent.py replanning rule",
            )
            exp["points"] = [
                "Replanning picks the untried candidate with the largest estimated reduction "
                "that passes the optimizer's constraints.",
                f"This candidate: {red:.1f} kW. Selected ({action_label(selected)}): {w_red:.1f} kW.",
            ]
        elif winner is not None:
            sb, wb = c.get("score_breakdown"), winner.get("score_breakdown")
            exp.update(
                verdict="not_selected",
                title="Passed constraints, lower score",
                basis="optimizer.py score",
            )
            if sb and wb:
                exp["points"] = [
                    f"It passed every constraint, but scored {sb['score']:.2f} against "
                    f"{wb['score']:.2f} for {action_label(selected)}.",
                    f"Score = reduction x {sb['reduction_weight']:g} minus disruption rank x "
                    f"{sb['impact_penalty']:g} (weights for {sb['severity']} severity).",
                ]
                if red > (_num(winner.get("estimated_reduction_kw")) or 0):
                    exp["points"].append(
                        "It simulates a larger reduction, but its higher disruption rank "
                        "costs more than the extra reduction earns."
                    )
                exp["comparison"] = {
                    "this": sb,
                    "selected": wb,
                    "selected_label": action_label(selected),
                }
            else:
                exp["points"] = [
                    "It passed the constraints but was not the optimizer's choice."
                ]
        c["explanation"] = exp


def optimizer_constraints() -> Optional[List[str]]:
    if not OPTIMIZER_AVAILABLE:
        return None
    return [
        f"Estimated reduction of at least {_optimizer.MIN_USEFUL_REDUCTION_KW:g} kW",
        f"Battery and combined actions need battery SOC above {_optimizer.MIN_BATTERY_SOC:g}%",
        "EV and combined actions need active EV charging load",
    ]


def build_recommendation_reason(
    recommendation: Optional[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    source: str,
    failed_action: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Factual explanation assembled only from existing fields and the optimizer's
    own scoring functions. No generated reasoning is claimed.
    """
    if not recommendation:
        return None
    action = recommendation.get("recommended_action") or recommendation.get("action")
    points: List[str] = []

    if source == "replanning":
        points.append(
            f"{action_label(failed_action)} did not reach the verification target, so the "
            "agent's replanning step excluded it."
        )
        points.append(
            "Among the untried candidates that pass the optimizer's constraints, this one has the "
            "largest estimated reduction (the agent's replanning rule)."
        )
        return {"points": points, "basis": "agent.py replanning rule"}

    valid = [c for c in candidates if c.get("passes_constraints")]
    total = len(candidates)
    if recommendation.get("optimization_score") is not None and valid:
        points.append(
            f"Highest optimization score ({_num(recommendation['optimization_score']):.2f}) among "
            f"{len(valid)} of {total} simulated candidates that passed the optimizer's constraints."
        )
    red = _num(recommendation.get("estimated_reduction_kw"))
    pct = _num(recommendation.get("reduction_percent"))
    base = _num(recommendation.get("original_predicted_load"))
    if red is not None:
        tail = (
            f" ({pct:.1f}% of the {base:.1f} kW forecast)"
            if pct is not None and base is not None
            else ""
        )
        points.append(f"Simulated reduction of {red:.1f} kW{tail}.")

    my_red = _num(recommendation.get("estimated_reduction_kw")) or 0
    larger = [
        c
        for c in candidates
        if c.get("action") != action
        and (_num(c.get("estimated_reduction_kw")) or 0) > my_red
    ]
    for c in larger:
        c_red = _num(c.get("estimated_reduction_kw")) or 0
        if c.get("passes_constraints") is False:
            points.append(
                f"{action_label(c.get('action'))} simulated a larger reduction ({c_red:.1f} kW) "
                "but failed the optimizer's constraints."
            )
        else:
            points.append(
                f"{action_label(c.get('action'))} simulated a larger reduction ({c_red:.1f} kW) but scored lower: "
                f"the score also penalises operational disruption, weighted by event severity "
                f"({recommendation.get('event_severity', 'n/a')})."
            )
    best_red = max(
        candidates,
        key=lambda c: _num(c.get("estimated_reduction_kw")) or 0,
        default=None,
    )
    if False:
        pass
    elif best_red and best_red.get("action") == action and len(valid) > 1:
        points.append("It is also the candidate with the largest simulated reduction.")

    if recommendation.get("recommendation"):
        points.append(f"Optimizer note: {recommendation['recommendation']}")

    return {"points": points, "basis": "optimizer.py score and constraints"}


# =========================================================
# APPLICATION-LEVEL AGENT SERVICE
# =========================================================


class AgentService:
    """
    Holds a single long-lived agent so the approval step can arrive in a later
    HTTP request. All agent calls are serialised with a lock because Flask
    serves requests on multiple threads.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.agent = DashboardAgent()
        self._reset_run_state()
        self.processed_timestamps: set = set()
        # (timestamp, building_id) pairs whose problem the agent closed with a
        # verified SUCCESS. The 3D campus map paints these green. Survives new
        # runs; cleared only by reset().
        self.resolved: set = set()

        self._catalog_lock = threading.Lock()
        self._actionable: Optional[set] = None
        self._replan_ts: Optional[set] = None
        self._replan_quick: set = set()
        self._catalog_error: Optional[str] = None

    def _reset_run_state(self):
        self.original_recommendation: Optional[Dict[str, Any]] = None
        self.recommendation_source = "optimizer"
        self.failed_action: Optional[str] = None
        self.verification_log: List[Dict[str, Any]] = []
        self.last_verification: Optional[Dict[str, Any]] = None
        self.last_decision: Optional[Dict[str, Any]] = None
        self.last_error: Optional[str] = None
        self.selection_note: Optional[str] = None
        self.replan_count = 0

    # ---------------- event catalog (which events have ML outputs) ----------

    def load_catalog(self) -> None:
        with self._catalog_lock:
            if self._actionable is not None:
                return
            try:
                events = _tool_data(
                    tools.get_ml_prediction_events(), "ML prediction events"
                )
                actionable = set()
                for ts in sorted({e["timestamp"] for e in events}):
                    rec = tools.get_ml_recommendation(ts)
                    if rec.get("success") and rec.get("data"):
                        actionable.add(ts)
                replan = tools.get_ml_replanning_events()
                self._replan_ts = {r["timestamp"] for r in (replan.get("data") or [])}
                # Replanning events whose first alternative verifies: the clearest demo story.
                quick = set()
                for r in replan.get("data") or []:
                    sims = (tools.get_ml_simulation(r["timestamp"]).get("data")) or []
                    alts = [
                        s
                        for s in sims
                        if s.get("action") != r.get("executed_action")
                        and (tools.validate_candidate_action(s).get("data") or {}).get(
                            "valid", True
                        )
                    ]
                    if not alts:
                        continue
                    alt = max(alts, key=lambda s: s.get("estimated_reduction_kw", 0))
                    ver = tools.get_ml_verification_for_action(
                        r["timestamp"], alt["action"]
                    )
                    if (
                        ver.get("success")
                        and ver.get("data")
                        and not ver["data"].get("needs_replanning")
                    ):
                        quick.add(r["timestamp"])
                self._replan_quick = quick
                self._actionable = actionable
                self._catalog_error = None
                log.info(
                    "Event catalog ready: %d actionable timestamps", len(actionable)
                )
            except Exception as exc:  # noqa: BLE001
                self._catalog_error = str(exc)
                self._actionable, self._replan_ts = set(), set()
                log.warning("Event catalog unavailable: %s", exc)

    @property
    def actionable(self) -> set:
        self.load_catalog()
        return self._actionable or set()

    @property
    def replan_timestamps(self) -> set:
        self.load_catalog()
        return self._replan_ts or set()

    # ---------------- lifecycle ----------------------------------------------

    def reset(self) -> None:
        with self.lock:
            self.agent = DashboardAgent()
            self._reset_run_state()
            self.resolved = set()

    def select_event(self, body: Dict[str, Any]) -> Dict[str, Any]:
        events = _tool_data(tools.get_ml_prediction_events(), "ML prediction events")
        timestamp = (body.get("timestamp") or "").strip()
        building = body.get("building_id") or body.get("building")
        event_type = body.get("event_type")

        if timestamp:
            matches = [e for e in events if e.get("timestamp") == timestamp]
            if building:
                matches = [
                    e for e in matches if e.get("building_id") == building
                ] or matches
            if event_type:
                matches = [
                    e for e in matches if e.get("event_type") == event_type
                ] or matches
            if not matches:
                raise ValueError(f"No prediction event found at {timestamp}.")
            self.selection_note = None
            return matches[0]

        scenario = (body.get("scenario") or "auto").lower()
        building = _normalize_building(building)
        pool = [e for e in events if e.get("timestamp") in self.actionable]
        if scenario == "replanning":
            pool = [e for e in pool if e["timestamp"] in self.replan_timestamps]
            quick = [e for e in pool if e["timestamp"] in self._replan_quick]
            pool = quick or pool
        elif scenario == "standard":
            pool = [e for e in pool if e["timestamp"] not in self.replan_timestamps]
        if not pool:
            raise ValueError(
                "No prediction event with simulation and recommendation data is available."
            )

        note = None
        if building != "CAMPUS":
            own = [e for e in pool if e.get("building_id") == building]
            if own:
                pool = own
            else:
                pool = [e for e in pool if e.get("building_id") == "CAMPUS"] or pool
                note = (
                    f"No event for {building} {building_name(building)} has simulation data, "
                    "so the agent is analysing a campus-wide event that includes it."
                )

        fresh = [e for e in pool if e["timestamp"] not in self.processed_timestamps]
        if not fresh:
            self.processed_timestamps -= {e["timestamp"] for e in pool}
            fresh = pool
        fresh.sort(
            key=lambda e: (SEVERITY_RANK.get(e.get("severity"), 0), e.get("timestamp")),
            reverse=True,
        )
        self.selection_note = note
        return fresh[0]

    def run(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            event = self.select_event(body)
            note = self.selection_note
            self._reset_run_state()
            self.selection_note = note
            self.processed_timestamps.add(event.get("timestamp"))

            result = self.agent.handle_event(dict(event))
            if self.agent.state == AgentState.FAILED:
                self.last_error = self._failure_message(result)
            else:
                self.original_recommendation = dict(self.agent.selected_action or {})
            return self.snapshot()

    def decide(self, approved: bool) -> Dict[str, Any]:
        with self.lock:
            if self.agent.state != AgentState.WAITING_FOR_APPROVAL:
                raise PermissionError(
                    f"The agent is in state {self.agent.state.value}; "
                    "approval is only possible while it waits for approval."
                )
            intended = self.agent.selected_action or {}
            intended_action = intended.get("recommended_action") or intended.get(
                "action"
            )

            result = self.agent.process_approval(approved)
            self.last_decision = {
                "decision": "APPROVED" if approved else "REJECTED",
                "action": intended_action,
                "time": _now(),
            }
            if not approved:
                return self.snapshot()

            if self.agent.state == AgentState.FAILED:
                self.last_error = self._failure_message(result)
                return self.snapshot()

            if result.get("replan"):
                # The agent clears verification_result when it replans. Read the
                # same record it just evaluated so the operator can see why.
                ts = (self.agent.current_event or {}).get("timestamp")
                ver = (
                    tools.get_verification_for_action_tool(ts, intended_action)
                    if ts
                    else {}
                )
                if not (ver.get("success") and ver.get("data")) and ts:
                    ver = tools.get_verification_result_tool(ts)
                record = dict(ver.get("data") or {})
                self._log_verification(record, intended_action)
                self.replan_count += 1
                self.recommendation_source = "replanning"
                self.failed_action = intended_action
            else:
                self._log_verification(
                    dict(self.agent.verification_result or {}), intended_action
                )
                ev = self.agent.current_event or {}
                if (
                    self.agent.state == AgentState.COMPLETED
                    and (self.last_verification or {}).get("verification_status") == "SUCCESS"
                    and ev.get("timestamp")
                ):
                    self.resolved.add((ev["timestamp"], ev.get("building_id") or "CAMPUS"))
            return self.snapshot()

    def _failure_message(self, result: Dict[str, Any]) -> str:
        """The agent may return error=None when a tool succeeds with empty data."""
        if result.get("error"):
            return str(result["error"])
        last = (self.agent.history or [{}])[-1].get("message", "")
        last = last.removesuffix(": None").replace("FAILED at ", "")
        return (
            f"No data returned for step: {last}"
            if last
            else "The agent stopped with an unknown error."
        )

    def _log_verification(
        self, record: Dict[str, Any], intended_action: Optional[str]
    ) -> None:
        if not record:
            return
        verified_action = record.get("executed_action")
        entry = {
            "intended_action": intended_action,
            "intended_label": action_label(intended_action),
            "verified_action": verified_action,
            "verified_label": action_label(verified_action),
            "action_mismatch": bool(
                verified_action
                and intended_action
                and verified_action != intended_action
            ),
            "expected_reduction_kw": _num(record.get("expected_reduction_kw")),
            "achieved_reduction_kw": _num(record.get("achieved_reduction_kw")),
            "performance_ratio_percent": _num(record.get("performance_ratio_percent")),
            "expected_load_after_action": _num(
                record.get("expected_load_after_action")
            ),
            "observed_load_after_action": _num(
                record.get("observed_load_after_action")
            ),
            "verification_status": record.get("verification_status"),
            "needs_replanning": bool(record.get("needs_replanning")),
            "threshold_percent": (
                (_SUCCESS_THRESHOLD * 100) if _SUCCESS_THRESHOLD else None
            ),
            "time": _now(),
        }
        self.last_verification = entry
        self.verification_log.append(entry)

    # ---------------- serialisation -------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            a = self.agent
            state = a.state.value
            selected = a.selected_action or None
            selected_name = (selected or {}).get("recommended_action") or (
                selected or {}
            ).get("action")
            candidates = enrich_candidates(a.candidate_actions, selected_name)
            explain_candidates(
                candidates,
                selected_name,
                self.recommendation_source,
                self.verification_log,
            )

            recommendation = None
            if selected:
                if state == "WAITING_FOR_APPROVAL":
                    approval = (
                        "REJECTED"
                        if (self.last_decision or {}).get("decision") == "REJECTED"
                        and self.last_decision.get("action") == selected_name
                        else "PENDING"
                    )
                elif a.approval_granted:
                    approval = "APPROVED"
                else:
                    approval = "PENDING"
                recommendation = {
                    "action": selected_name,
                    "label": action_label(selected_name),
                    "estimated_reduction_kw": _num(
                        selected.get("estimated_reduction_kw")
                    ),
                    "reduction_percent": _num(selected.get("reduction_percent")),
                    "original_predicted_load": _num(
                        selected.get("original_predicted_load")
                    ),
                    "new_predicted_load": _num(selected.get("new_predicted_load")),
                    "optimization_score": _num(selected.get("optimization_score")),
                    "event_severity": selected.get("event_severity"),
                    "optimizer_note": selected.get("recommendation"),
                    "source": self.recommendation_source,
                    "approval_status": approval,
                    "reason": build_recommendation_reason(
                        selected,
                        candidates,
                        self.recommendation_source,
                        self.failed_action,
                    ),
                }

            trail_states = [t["state"] for t in getattr(a, "state_trail", [])]
            return {
                "agent_id": a.agent_id,
                "state": state,
                "approval_required": state == "WAITING_FOR_APPROVAL",
                "has_run": a.current_event is not None,
                "execution_mode": "SIMULATED",
                "lifecycle": LIFECYCLE,
                "trail": getattr(a, "state_trail", []),
                "replanned": "REPLANNING" in trail_states or self.replan_count > 0,
                "replan_count": self.replan_count,
                "event": a.current_event,
                "selection_note": self.selection_note,
                "recommendation_scope_note": (
                    "The simulated actions and recommendation for this hour come from the campus "
                    "peak-demand analysis. The ML pipeline does not produce building-specific "
                    "actions for anomalies."
                    if (a.current_event or {}).get("event_type") == "ENERGY_ANOMALY"
                    else None
                ),
                "problem": build_problem_summary(
                    a.current_event, a.evidence, self.original_recommendation
                ),
                "evidence": summarize_evidence(a.evidence),
                "candidate_actions": candidates,
                "optimizer_constraints": optimizer_constraints(),
                "recommendation": recommendation,
                "verification": self.last_verification,
                "verification_log": self.verification_log,
                "last_decision": self.last_decision,
                "error": self.last_error if state == "FAILED" else None,
                "history": a.history,
            }


service = AgentService()


# =========================================================
# DATA HELPERS FOR CHARTS / KPIs (tools only)
# =========================================================


def latest_readings() -> Dict[str, Dict[str, Any]]:
    out = {}
    for bid in BUILDING_IDS:
        res = tools.get_current_consumption(bid)
        if res.get("success") and res.get("data"):
            out[bid] = res["data"]
    return out


def energy_series(building: str, center: Optional[str], hours: int) -> Dict[str, Any]:
    hours = max(6, min(int(hours), 24 * 14))
    readings = latest_readings()
    if not readings:
        raise RuntimeError("No energy readings available from the database.")
    latest_ts = max(r["timestamp"] for r in readings.values())

    if center:
        c = dt.datetime.fromisoformat(center)
        after = min(12, hours // 4)
        start, end = c - dt.timedelta(hours=hours - after), c + dt.timedelta(
            hours=after
        )
    else:
        end = dt.datetime.fromisoformat(latest_ts)
        start = end - dt.timedelta(hours=hours)
    fmt = "%Y-%m-%d %H:%M:%S"
    start_s, end_s = start.strftime(fmt), end.strftime(fmt)

    targets = BUILDING_IDS if building == "CAMPUS" else [building]
    series: Dict[str, Dict[str, float]] = {}
    occ_counts: Dict[str, int] = {}
    for bid in targets:
        rows = _tool_data(
            tools.get_historical_consumption(bid, start_s, end_s), f"History {bid}"
        )
        for r in rows or []:
            ts = r["timestamp"]
            s = series.setdefault(
                ts,
                {
                    "energy_kw": 0.0,
                    "solar_kw": 0.0,
                    "hvac_kw": 0.0,
                    "ev_kw": 0.0,
                    "occupancy_pct": 0.0,
                },
            )
            for key in ("energy_kw", "solar_kw", "hvac_kw", "ev_kw", "occupancy_pct"):
                s[key] += _num(r.get(key)) or 0.0
            occ_counts[ts] = occ_counts.get(ts, 0) + 1

    labels = sorted(series)
    return {
        "building": building,
        "building_name": building_name(building),
        "start": start_s,
        "end": end_s,
        "center": center,
        "labels": labels,
        "energy_kw": [round(series[t]["energy_kw"], 2) for t in labels],
        "solar_kw": [round(series[t]["solar_kw"], 2) for t in labels],
        "hvac_kw": [round(series[t]["hvac_kw"], 2) for t in labels],
        "ev_kw": [round(series[t]["ev_kw"], 2) for t in labels],
        "occupancy_pct": [
            round(series[t]["occupancy_pct"] / occ_counts[t], 2) for t in labels
        ],
        "source": "energy_readings (SQLite) via tools.get_historical_consumption",
    }


# =========================================================
# ROUTES
# =========================================================


@app.route("/")
def index():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))
    return render_template("overview.html", page="overview", title="Overview")


@app.get("/api/health")
@api
def api_health():
    return ok(
        {
            "database": tools.DATABASE_AVAILABLE,
            "ml_service": tools.ML_SERVICE_AVAILABLE,
            "optimizer": OPTIMIZER_AVAILABLE,
            "rag": rag_service is not None
            and rag_service.status().get("available", False),
            "mock_data": tools.ALLOW_MOCK_DATA,
        }
    )


@app.get("/api/buildings")
@api
def api_buildings():
    readings = latest_readings()
    out = []
    for bid in BUILDING_IDS:
        meta = CONFIG_BUILDINGS.get(bid, {})
        r = readings.get(bid, {})
        out.append(
            {
                "building_id": bid,
                "name": meta.get("building_name", bid),
                "type": meta.get("building_type"),
                "floor_area_m2": meta.get("floor_area_m2"),
                "working_hours": (
                    f"{meta['working_start_hour']:02d}:00–{meta['working_end_hour']:02d}:00"
                    if "working_start_hour" in meta
                    else None
                ),
                "has_solar": meta.get("has_solar"),
                "has_ev_charging": meta.get("has_ev_charging"),
                "has_battery": meta.get("has_battery"),
                "latest": r or None,
            }
        )
    return ok(out)


@app.get("/api/dashboard")
@api
def api_dashboard():
    building = _normalize_building(request.args.get("building"))
    readings = latest_readings()
    targets = BUILDING_IDS if building == "CAMPUS" else [building]

    load = [
        (_num(readings[b].get("energy_kw")) or 0.0) for b in targets if b in readings
    ]
    solar = []
    for b in targets:
        res = tools.get_solar_generation(b)
        if res.get("success") and res.get("data"):
            solar.append(
                _num(res["data"].get("solar_kw", res["data"].get("generation_kw")))
                or 0.0
            )

    summary_res = tools.get_ml_system_summary()
    summary = summary_res.get("data") if summary_res.get("success") else None

    events_res = tools.get_ml_prediction_events()
    events = (events_res.get("data") or []) if events_res.get("success") else []
    scoped_anomalies = [
        e
        for e in events
        if e.get("event_type") == "ENERGY_ANOMALY"
        and (building == "CAMPUS" or e.get("building_id") == building)
    ]
    peak_events = [e for e in events if e.get("event_type") == "PEAK_DEMAND_RISK"]

    snap = service.snapshot()
    rec = snap.get("recommendation") or {}
    ver = snap.get("verification") or {}

    return ok(
        {
            "building": building,
            "building_name": building_name(building),
            "as_of": max((r["timestamp"] for r in readings.values()), default=None),
            "kpis": {
                "current_load_kw": round(sum(load), 2) if load else None,
                "solar_kw": round(sum(solar), 2) if solar else None,
                "anomalies": len(scoped_anomalies),
                "anomalies_high": sum(
                    1
                    for e in scoped_anomalies
                    if e.get("severity") in ("HIGH", "CRITICAL")
                ),
                "peak_risks": len(peak_events),
                "estimated_reduction_kw": rec.get("estimated_reduction_kw"),
                "estimated_reduction_action": rec.get("label"),
                "achieved_reduction_kw": ver.get("achieved_reduction_kw"),
            },
            "ml_summary": summary,
            "agent": {
                "state": snap["state"],
                "approval_required": snap["approval_required"],
            },
            "rag": (
                rag_service.status()
                if rag_service
                else {"available": False, "error": RAG_IMPORT_ERROR}
            ),
            "execution_mode": "SIMULATED",
        }
    )


@app.get("/api/energy")
@api
def api_energy():
    building = _normalize_building(request.args.get("building"))
    hours = int(request.args.get("hours", 48))
    center = request.args.get("center") or None
    if center is None and request.args.get("follow_event", "true").lower() != "false":
        center = (service.agent.current_event or {}).get("timestamp")
    return ok(energy_series(building, center, hours))


@app.get("/api/live/stream")
@api
def api_live_stream():
    building = _normalize_building(request.args.get("building"))
    state = live_simulator.get_live_operational_state(building)
    return ok(state)


@app.get("/api/history/years")
@api
def api_history_years():
    years = database.get_historical_years()
    return ok({"years": years})


@app.get("/api/history/query")
@api
def api_history_query():
    building = _normalize_building(request.args.get("building"))
    dt_str = request.args.get("timestamp") or "2017-09-23 20:00:00"
    
    # Query exact historical record
    b_target = "B001" if building == "CAMPUS" else building
    reading = database.get_energy_reading_at(b_target, dt_str)
    solar_r = database.get_solar_reading_at(b_target, dt_str)
    db_incidents = database.get_incidents(building_id=None if building == "CAMPUS" else building)

    # Get ML prediction events matching timestamp or date
    ml_events_res = tools.get_ml_prediction_events(limit=100)
    all_ml = (ml_events_res.get("data") or []) if ml_events_res.get("success") else []
    
    # Filter ML events for matching date or timestamp
    date_prefix = dt_str[:10]
    matched_events = [
        {
            "incident_type": e.get("event_type", "INCIDENT"),
            "severity": e.get("severity", "ELEVATED"),
            "created_at": e.get("timestamp"),
            "description": e.get("description", e.get("event_type")),
            "building_id": e.get("building_id")
        }
        for e in all_ml
        if e.get("timestamp", "").startswith(date_prefix)
        and (building == "CAMPUS" or e.get("building_id") in (building, "CAMPUS"))
    ]

    incidents = matched_events if matched_events else db_incidents[:10]

    # Historical 24h window chart around selected timestamp
    series = energy_series(building, center=dt_str, hours=24)
    available_years = database.get_historical_years()

    return ok({
        "timestamp": dt_str,
        "building": building,
        "building_name": building_name(building),
        "reading": reading,
        "solar_reading": solar_r,
        "incidents": incidents[:10],
        "series": series,
        "available_years": available_years,
        "is_historical_truth": True
    })




# =========================================================
# 3D CAMPUS MAP (Digital Twin)
# =========================================================

_TWIN_SEVERITY_ORDER = ["CRITICAL", "HIGH", "ELEVATED", "LOW", "NORMAL"]


def _twin_worst(events: List[Dict[str, Any]]) -> Optional[str]:
    if not events:
        return None
    return max(
        (e.get("severity") or "LOW" for e in events),
        key=lambda sev: SEVERITY_RANK.get(sev, 0),
    )


@app.get("/api/twin/map")
@api
def api_twin_map():
    """
    State of every building for one analysed hour, for the 3D campus map.

    status per building:
      problem  - at least one ML event (anomaly / peak risk) at this hour
      resolved - the agent executed and verified a fix for it (SUCCESS)
      normal   - nothing flagged at this hour
    The campus itself is an entry too: PEAK_DEMAND_RISK events are campus-wide.
    """
    events = _tool_data(tools.get_ml_prediction_events(), "ML prediction events")
    actionable = service.actionable
    by_ts: Dict[str, List[Dict[str, Any]]] = {}
    for e in events:
        ts = e.get("timestamp")
        if ts in actionable:
            by_ts.setdefault(ts, []).append(e)

    hours = sorted(by_ts, reverse=True)
    snap = service.snapshot()
    agent_event = snap.get("event") or {}

    focus = (request.args.get("timestamp") or "").strip()
    if focus not in by_ts:
        focus = agent_event.get("timestamp") if agent_event.get("timestamp") in by_ts else (hours[0] if hours else None)

    hour_events = [
        {
            **e,
            "event_label": EVENT_LABELS.get(e.get("event_type"), e.get("event_type")),
            "building_name": building_name(e.get("building_id")),
        }
        for e in by_ts.get(focus, [])
    ]
    resolved = service.resolved

    def entry_status(bid: str, evs: List[Dict[str, Any]]) -> str:
        if not evs:
            return "normal"
        return "resolved" if (focus, bid) in resolved else "problem"

    buildings = []
    for bid in BUILDING_IDS:
        meta = CONFIG_BUILDINGS.get(bid, {})
        evs = [e for e in hour_events if e.get("building_id") == bid]
        try:
            live = live_simulator.get_live_operational_state(bid)
        except Exception:  # the map must render even if the stream is down
            live = {}
        buildings.append(
            {
                "building_id": bid,
                "name": meta.get("building_name", bid),
                "type": meta.get("building_type"),
                "floor_area_m2": meta.get("floor_area_m2"),
                "maximum_power_kw": meta.get("maximum_power_kw"),
                "has_solar": meta.get("has_solar"),
                "has_ev_charging": meta.get("has_ev_charging"),
                "has_battery": meta.get("has_battery"),
                "live_load_kw": live.get("current_load_kw"),
                "live_solar_kw": live.get("solar_kw"),
                "status": entry_status(bid, evs),
                "severity": _twin_worst(evs),
                "events": evs,
            }
        )

    campus_evs = [e for e in hour_events if e.get("building_id") == "CAMPUS"]
    # The newest hours, plus every hour that flags a specific building, so a
    # building's own problems stay reachable even when they are older.
    listed = sorted(
        set(hours[:36])
        | {ts for ts in hours if any(e.get("building_id") != "CAMPUS" for e in by_ts[ts])}
        | ({focus} if focus else set()),
        reverse=True,
    )
    return ok(
        {
            "focus_timestamp": focus,
            "hours": [
                {
                    "timestamp": ts,
                    "count": len(by_ts[ts]),
                    "severity": _twin_worst(by_ts[ts]),
                    "buildings": sorted({e.get("building_id") for e in by_ts[ts]}),
                }
                for ts in listed
            ],
            "campus": {
                "building_id": "CAMPUS",
                "name": building_name("CAMPUS"),
                "status": entry_status("CAMPUS", campus_evs),
                "severity": _twin_worst(campus_evs),
                "events": campus_evs,
            },
            "buildings": buildings,
            "agent": {
                "state": snap.get("state"),
                "has_run": snap.get("has_run"),
                "event": {
                    "timestamp": agent_event.get("timestamp"),
                    "building_id": agent_event.get("building_id"),
                    "event_type": agent_event.get("event_type"),
                } if agent_event else None,
            },
            "execution_mode": "SIMULATED",
        }
    )


@app.get("/api/events")
@api
def api_events():
    building = _normalize_building(request.args.get("building"))
    event_type = request.args.get("type") or None
    limit = max(1, min(int(request.args.get("limit", 40)), 500))
    actionable_only = request.args.get("actionable", "false").lower() == "true"

    events = _tool_data(
        tools.get_ml_prediction_events(event_type=event_type), "ML prediction events"
    )
    if building != "CAMPUS":
        events = [e for e in events if e.get("building_id") in (building, "CAMPUS")]
    actionable = service.actionable
    out = []
    # Events the agent can fully process (simulation + recommendation exist)
    # are listed first, newest first within each group.
    ordered = sorted(events, key=lambda x: x.get("timestamp", ""), reverse=True)
    ordered.sort(key=lambda x: x.get("timestamp") not in actionable)
    for e in ordered:
        is_actionable = e.get("timestamp") in actionable
        if actionable_only and not is_actionable:
            continue
        out.append(
            {
                **e,
                "event_label": EVENT_LABELS.get(
                    e.get("event_type"), e.get("event_type")
                ),
                "building_name": building_name(e.get("building_id")),
                "actionable": is_actionable,
            }
        )
        if len(out) >= limit:
            break
    return ok(
        {
            "events": out,
            "total": len(events),
            "actionable_total": sum(
                1 for e in events if e.get("timestamp") in actionable
            ),
        }
    )


@app.get("/api/agent/status")
@api
def api_agent_status():
    return ok(service.snapshot())


@app.post("/api/agent/run")
@api
def api_agent_run():
    body = request.get_json(silent=True) or {}
    return ok(service.run(body))


@app.post("/api/agent/approve")
@api
def api_agent_approve():
    try:
        return ok(service.decide(True))
    except PermissionError as exc:
        return fail(str(exc), 409)


@app.post("/api/agent/reject")
@api
def api_agent_reject():
    try:
        return ok(service.decide(False))
    except PermissionError as exc:
        return fail(str(exc), 409)


@app.post("/api/agent/reset")
@api
def api_agent_reset():
    service.reset()
    return ok(service.snapshot())


@app.get("/api/agent/history")
@api
def api_agent_history():
    snap = service.snapshot()
    return ok(
        {"history": snap["history"], "trail": snap["trail"], "state": snap["state"]}
    )


@app.get("/api/verification")
@api
def api_verification():
    snap = service.snapshot()
    return ok(
        {
            "latest": snap["verification"],
            "log": snap["verification_log"],
            "state": snap["state"],
            "threshold_percent": (
                (_SUCCESS_THRESHOLD * 100) if _SUCCESS_THRESHOLD else None
            ),
        }
    )


@app.get("/api/verification/diagnosis")
@api
def api_verification_diagnosis():
    """
    Why an approved action missed its target, measured from the readings.

    verification.py decides success with a random execution factor, so the
    record itself carries no cause. This reads the hour the action ran in and
    compares each component with the level the plan assumed. Every kW it
    returns is a measured difference; where the readings explain nothing, it
    says so rather than inventing a reason.
    """
    snap = service.snapshot()
    record = snap.get("verification")

    if not record:
        return fail("No verified action yet, so there is nothing to diagnose.", 400)

    event = snap.get("event") or {}
    timestamp = request.args.get("timestamp") or event.get("timestamp")
    action = request.args.get("action") or record.get("intended_action")

    if not timestamp or not action:
        return fail("A timestamp and an action are required.", 400)

    try:
        return ok(
            execution_diagnosis.diagnose(
                timestamp=timestamp,
                action=action,
                expected_reduction_kw=record.get("expected_reduction_kw"),
                achieved_reduction_kw=record.get("achieved_reduction_kw"),
                building_id=event.get("building_id") or "CAMPUS",
            )
        )
    except execution_diagnosis.DiagnosisUnavailable as exc:
        return fail(str(exc), 503)


@app.get("/api/impact/factors")
@api
def api_impact_factors():
    """
    Money and carbon conversion factors (idea #4).

    Single source of truth for JOD-per-kWh and kg-CO2-per-kWh, so the Digital
    Twin, dashboard and report all quote the same numbers. Read-only.
    """
    if impact_translation is None:
        return fail(f"Impact translation is unavailable: {_IMPACT_IMPORT_ERROR}", 503)
    return ok(impact_translation.factors())


@app.get("/api/anomaly/holiday-audit")
@api
def api_holiday_audit():
    """
    The model auditing its own holiday blind spot (idea #3).

    Measures how many recorded anomalies fall in the Dec 23 - Jan 2 shutdown.
    Read-only: nothing is retrained and no stored value changes.
    """
    if holiday_audit is None:
        return fail(f"Holiday audit is unavailable: {_HOLIDAY_IMPORT_ERROR}", 503)
    try:
        return ok(holiday_audit.audit())
    except holiday_audit.AuditUnavailable as exc:
        return fail(str(exc), 503)


@app.get("/api/agent/learning")
@api
def api_agent_learning():
    """
    Confidence learned from the agent's own verification history (idea #2).

    Per-action success rate and a confidence multiplier. Additive: it does not
    change which action the agent selects. Read-only.
    """
    if agent_learning is None:
        return fail(f"Agent learning is unavailable: {_LEARNING_IMPORT_ERROR}", 503)
    try:
        return ok(agent_learning.summary())
    except agent_learning.LearningUnavailable as exc:
        return fail(str(exc), 503)


@app.post("/api/rag/query")
@api
def api_rag_query():
    if rag_service is None:
        return fail(f"Knowledge service is unavailable: {RAG_IMPORT_ERROR}", 503)
    body = request.get_json(silent=True) or {}
    question = body.get("question", "")

    live = None
    if body.get("include_live_context"):
        snap = service.snapshot()
        if snap.get("has_run"):
            problem = snap.get("problem") or {}
            rec = snap.get("recommendation") or {}
            ev = snap.get("evidence") or {}
            live = {
                "agent_state": snap["state"],
                "event": problem.get("headline"),
                "severity": problem.get("severity"),
                "recommended_action": rec.get("label"),
                "estimated_reduction_kw": rec.get("estimated_reduction_kw"),
                "evidence_energy_kw": ev.get("energy_kw"),
                "evidence_hvac_kw": ev.get("hvac_kw"),
                "evidence_occupancy_pct": ev.get("occupancy_pct"),
            }
            live = {k: v for k, v in live.items() if v is not None}

    try:
        return ok(rag_service.query(question, live_context=live))
    except ValueError as exc:
        return fail(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        log.warning("RAG query failed: %s", exc)
        return fail("The knowledge service could not answer right now.", 503)


@app.post("/api/rag/reload")
@api
def api_rag_reload():
    if rag_service is None:
        return fail(f"Knowledge service is unavailable: {RAG_IMPORT_ERROR}", 503)
    rag_service.load()
    return ok(rag_service.status())




# =========================================================
# ML EXPLAINABILITY (LIME)
# =========================================================


@app.get("/api/ml/explain/status")
@api
def api_ml_explain_status():
    """Whether LIME explanations can be produced in this environment."""
    available, reason = ml_explainer.is_available()
    summary_ready, summary_reason = ml_explainer.summary_available()
    return ok(
        {
            "available": available,
            "reason": reason or "LIME and the forecast model are both loaded.",
            "summary_available": summary_ready,
            "summary_reason": summary_reason,
        }
    )


@app.post("/api/ml/explain")
@api
def api_ml_explain():
    """
    Explain one forecast hour with LIME.

    Every weight returned here is fitted at request time by ml_explainer against
    the trained forecaster. There is no cached sample and no placeholder path:
    when an explanation cannot be produced this returns the reason instead.
    """
    body = request.get_json(silent=True) or {}
    timestamp = str(body.get("timestamp") or "").strip()
    building_id = str(body.get("building_id") or "").strip().upper()
    num_features = body.get("num_features", 8)

    if not timestamp or not building_id:
        return fail("Both timestamp and building_id are required.", 400)

    try:
        num_features = int(num_features)
    except (TypeError, ValueError):
        return fail("num_features must be an integer.", 400)

    available, reason = ml_explainer.is_available()
    if not available:
        return fail(reason or "LIME explanations are unavailable.", 503)

    try:
        explanation = ml_explainer.explain_prediction(
            timestamp=timestamp,
            building_id=building_id,
            num_features=num_features,
        )
    except LookupError as exc:
        return fail(str(exc), 404)
    except ValueError as exc:
        return fail(str(exc), 400)

    # The plain-language paragraph is optional. summarize_explanation() returns
    # None when no model is configured or the call fails, and the LIME table
    # below it is unaffected either way, so this never blocks the response.
    payload = dict(explanation)
    payload["summary"] = ml_explainer.summarize_explanation(explanation)

    return ok(payload)


# =========================================================
# INCIDENT REPORT (PDF)
# =========================================================


def _report_explanation(snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Attach a LIME section to the report when one can be produced.

    A missing explanation never blocks the report: sections 1 to 3 and 5 stand
    on their own, and the PDF says plainly that the LIME section was omitted.
    """
    event = snapshot.get("event") or {}
    timestamp = event.get("timestamp")
    building_id = event.get("building_id") or "CAMPUS"
    if not timestamp:
        return None

    available, _ = ml_explainer.is_available()
    if not available:
        return None

    explanation = ml_explainer.get_cached_explanation(timestamp, building_id, 8)

    if explanation is None:
        try:
            explanation = ml_explainer.explain_prediction(
                timestamp, building_id, num_features=8
            )
        except Exception as exc:  # noqa: BLE001
            log.info("Report omits the LIME section: %s", exc)
            return None

    # Carry the plain-language paragraph into the report when one is available.
    # Both calls are cached, so a report printed after the dashboard button has
    # been used costs nothing extra.
    payload = dict(explanation)
    payload["summary"] = ml_explainer.summarize_explanation(explanation)

    return payload


@app.post("/api/report/pdf")
def api_report_pdf():
    """
    Render the incident report as a PDF.

    The content comes from report_service.build_report(), which is the same
    structure the Markdown export uses, so the two cannot drift apart. The
    snapshot is read server-side rather than from the request body, so the PDF
    cannot disagree with what the agent actually decided.
    """
    try:
        from io import BytesIO

        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        return fail(
            f"PDF export needs reportlab ({exc}). Install it with: pip install reportlab",
            503,
        )

    snapshot = service.snapshot()
    body = request.get_json(silent=True) or {}
    explanation = (
        _report_explanation(snapshot) if body.get("include_explanation", True) else None
    )

    try:
        report = report_service.build_report(snapshot, explanation)
    except ValueError as exc:
        return fail(str(exc), 400)

    ink = colors.HexColor("#111827")
    muted = colors.HexColor("#6b7280")
    rule = colors.HexColor("#e5e7eb")
    accent = colors.HexColor("#0f766e")

    sheet = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "t", parent=sheet["Title"], fontSize=19, leading=24, textColor=ink,
            alignment=TA_LEFT, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "s", parent=sheet["Normal"], fontSize=9, textColor=muted, spaceAfter=15,
        ),
        "h2": ParagraphStyle(
            "h", parent=sheet["Heading2"], fontSize=12.5, leading=16, textColor=accent,
            spaceBefore=16, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "b", parent=sheet["Normal"], fontSize=9.6, leading=14.2, textColor=ink,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "sm", parent=sheet["Normal"], fontSize=8.2, leading=11.5, textColor=muted,
            spaceAfter=4,
        ),
    }

    def para(text, key="body"):
        return Paragraph(_pdf_escape(text), styles[key])

    def bullet(text):
        return Paragraph(_pdf_escape(text), styles["body"], bulletText="\u2013")

    def specs(pairs, widths=(54 * mm, 106 * mm)):
        rows = [
            [Paragraph(f"<b>{_pdf_escape(k)}</b>", styles["body"]), para(v)]
            for k, v in pairs
            if v not in (None, "")
        ]
        if not rows:
            return None
        table = Table(rows, colWidths=list(widths), hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.4, rule),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return table

    def grid(headers, rows, widths):
        data = [[Paragraph(f"<b>{_pdf_escape(h)}</b>", styles["small"]) for h in headers]]
        data += [[para(cell, "small") for cell in row] for row in rows]
        table = Table(data, colWidths=[w * mm for w in widths], hAlign="LEFT", repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.7, accent),
                    ("LINEBELOW", (0, 1), (-1, -2), 0.3, rule),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    event = report.get("event") or {}
    evidence = report.get("evidence") or {}
    totals = evidence.get("totals") or {}
    recommendation = report.get("recommendation") or {}
    lime = report.get("lime") or {}
    story: List[Any] = []

    # ---- Header -----------------------------------------------------------
    story.append(para("Smart Energy AI — Incident Report", "title"))
    story.append(
        para(
            f"{report.get('report_id')} · generated {report.get('generated_at')} · "
            f"final state {humanise_state(report.get('final_state'))} · "
            f"execution {report.get('execution_mode')}",
            "subtitle",
        )
    )

    # ---- 1 · The problem --------------------------------------------------
    story.append(para("1 · What went wrong", "h2"))
    story.append(para(event.get("headline") or "No problem summary was recorded."))
    for fact in event.get("facts") or []:
        story.append(bullet(fact))
    table = specs(
        [
            ("Event type", event_label(event.get("type"))),
            ("Building", building_name(event.get("building"))),
            ("Hour", event.get("timestamp")),
            ("Severity", event.get("severity")),
            ("Reading", event.get("value_meaning")),
        ]
    )
    if table:
        story.extend([Spacer(1, 4), table])

    # ---- 2 · Evidence -----------------------------------------------------
    story.append(para("2 · What the agent checked", "h2"))
    story.append(
        para(
            "Operational readings at the event hour, taken from the database before "
            "any action was simulated."
        )
    )
    table = specs(
        [
            ("Total load", _kw(totals.get("energy_kw"))),
            ("HVAC load", _kw(totals.get("hvac_kw"))),
            ("EV charging", _kw(totals.get("ev_kw"))),
            ("Solar generation", _kw(totals.get("solar_kw"))),
            ("Occupancy", _pct(totals.get("occupancy_pct"))),
            ("Reading time", evidence.get("reading_time")),
        ]
    )
    story.append(table or para("No readings were captured for this event.", "small"))

    per_building = evidence.get("per_building") or []
    if per_building:
        story.append(Spacer(1, 8))
        story.append(
            grid(
                ["Building", "Total", "HVAC", "EV", "Solar", "Occupancy"],
                [
                    [
                        row.get("building_name") or row.get("building_id"),
                        _kw(row.get("energy_kw")) or "—",
                        _kw(row.get("hvac_kw")) or "—",
                        _kw(row.get("ev_kw")) or "—",
                        _kw(row.get("solar_kw")) or "—",
                        _pct(row.get("occupancy_pct")) or "—",
                    ]
                    for row in per_building
                ],
                [34, 26, 26, 24, 26, 24],
            )
        )

    # ---- 3 · Method and decision -----------------------------------------
    story.append(para("3 · How the action was chosen", "h2"))
    story.append(
        para(
            "Each candidate was replayed through the digital twin to estimate its load "
            "reduction, then screened against the optimiser's operating constraints. A "
            "candidate failing a constraint was discarded regardless of its reduction."
        )
    )

    candidates = report.get("candidates") or []
    if candidates:
        story.append(Spacer(1, 4))
        story.append(
            grid(
                ["Candidate action", "Reduction", "Score", "Verdict"],
                [
                    [
                        row.get("label") or "—",
                        _kw(row.get("reduction_kw")) or "—",
                        _round(row.get("score"), 3) or "—",
                        row.get("verdict") or "—",
                    ]
                    for row in candidates
                ],
                [58, 26, 20, 56],
            )
        )

    if recommendation.get("label"):
        story.append(Spacer(1, 10))
        table = specs(
            [
                ("Selected action", recommendation.get("label")),
                ("Estimated reduction", _kw(recommendation.get("reduction_kw"))),
                ("Reduction share", _pct(recommendation.get("reduction_percent"))),
                ("Chosen by", recommendation.get("source")),
                ("Basis", recommendation.get("basis")),
            ]
        )
        if table:
            story.append(table)
        for point in recommendation.get("reason_points") or []:
            story.append(bullet(point))
    else:
        story.append(para("No action was selected for this event.", "small"))

    decisions = report.get("decisions") or []
    if decisions:
        story.append(Spacer(1, 8))
        story.append(
            grid(
                ["Time", "Human decision", "Action"],
                [
                    [
                        row.get("time") or "—",
                        row.get("decision") or "—",
                        row.get("label") or row.get("message") or "—",
                    ]
                    for row in decisions
                ],
                [32, 34, 94],
            )
        )

    # ---- 4 · Model explanation -------------------------------------------
    story.append(para("4 · Why the model forecast what it did", "h2"))

    # A campus-wide explanation nests one result per building; a single-building
    # one carries its contributions at the top level. Normalise to a list.
    parts = [p for p in (lime.get("buildings") or [lime]) if p.get("contributions")]

    if parts:
        story.append(
            para(
                "LIME fits a weighted linear surrogate to the forecaster's responses on "
                "thousands of perturbations of this single input row. The weights below "
                "are that surrogate's view of which features moved this one forecast, in "
                "kW. They describe the model's local behaviour, not the physical cause "
                "of the event."
            )
        )
        if lime.get("summary"):
            story.append(Spacer(1, 4))
            story.append(para(lime.get("summary")))

        if lime.get("method"):
            story.append(para(f"Method: {lime.get('method')}", "small"))

        for part in parts:
            if len(parts) > 1:
                story.append(Spacer(1, 8))
                story.append(para(building_name(part.get("building_id")), "h2"))

            table = specs(
                [
                    ("Model forecast", _kw(part.get("predicted_kw"))),
                    ("Actual reading", _kw(part.get("actual_kw"))),
                    ("Residual", _pct(part.get("residual_percent"))),
                    ("Surrogate baseline", _kw(part.get("lime_intercept"))),
                    ("Local fit quality (R²)", _round(part.get("lime_score"), 3)),
                ]
            )
            if table:
                story.extend([Spacer(1, 4), table, Spacer(1, 6)])

            story.append(
                grid(
                    ["Feature condition", "Contribution", "Effect on forecast"],
                    [
                        [
                            row.get("condition") or row.get("feature") or "—",
                            f"{float(row.get('weight_kw') or 0.0):+.2f} kW",
                            "raises" if (row.get("weight_kw") or 0) >= 0 else "lowers",
                        ]
                        for row in part.get("contributions") or []
                    ],
                    [92, 30, 38],
                )
            )

        note = lime.get("note") or (parts[0].get("note") if parts else None)
        if note:
            story.append(Spacer(1, 6))
            story.append(para(note, "small"))
    else:
        story.append(
            para(
                "No LIME explanation is included: either the explainer is unavailable in "
                "this environment or no model input row exists for this hour. The "
                "reasoning in section 3 stands on its own.",
                "small",
            )
        )

    # ---- 5 · Results ------------------------------------------------------
    story.append(para("5 · What happened after execution", "h2"))

    verification = report.get("verification") or []
    if verification:
        story.append(
            grid(
                ["Action", "Expected", "Achieved", "Performance", "Outcome"],
                [
                    [
                        row.get("label") or row.get("intended_action") or "—",
                        _kw(row.get("expected_reduction_kw")) or "—",
                        _kw(row.get("achieved_reduction_kw")) or "—",
                        _pct(row.get("performance_percent")) or "—",
                        row.get("status") or "—",
                    ]
                    for row in verification
                ],
                [44, 26, 26, 28, 36],
            )
        )
        threshold = (report.get("constraints") or {}).get("threshold_percent")
        if threshold:
            story.append(Spacer(1, 4))
            story.append(
                para(
                    f"An action counts as successful when the measured reduction reaches "
                    f"{_round(threshold, 0)}% of the forecast reduction.",
                    "small",
                )
            )
    else:
        story.append(
            para(
                "Nothing has been executed or verified yet, so there is no measured "
                "outcome. Sections 1 to 4 describe the analysis only.",
                "small",
            )
        )

    story.append(Spacer(1, 14))
    for line in report.get("disclaimers") or []:
        story.append(para(line, "small"))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Smart Energy AI — {report.get('report_id')}",
        author="Smart Energy AI",
    )

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(20 * mm, 11 * mm, "Smart Energy AI · simulated execution")
        canvas.drawRightString(A4[0] - 20 * mm, 11 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{report.get('report_id', 'incident-report')}.pdf",
    )


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return fail("Endpoint not found.", 404)
    return render_template("overview.html", page="overview", title="Overview"), 404


@app.errorhandler(413)
def payload_too_large(_e):
    return fail("Request body is too large.", 413)


@app.errorhandler(405)
def not_allowed(_e):
    return fail("Method not allowed for this endpoint.", 405)


@app.errorhandler(500)
def server_error(_e):
    if request.path.startswith("/api/"):
        return fail("Internal server error.", 500)
    flash("حدث خطأ غير متوقع، يرجى المحاولة مرة أخرى. / An unexpected error occurred.", "danger")
    return redirect(url_for("auth.login"))


# Warm the event catalog in the background so the first click is fast.
threading.Thread(target=service.load_catalog, name="event-catalog", daemon=True).start()


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    print(f"\nSmart Energy AI Operations Center -> http://{host}:{port}\n")
    # use_reloader=False keeps exactly one agent instance alive.
    app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)
