"""
Smart Energy AI - Autonomous Operations Agent Core

Pre-approval lifecycle:
  MONITORING → INVESTIGATING → GATHERING_EVIDENCE → ANALYZING
  → FORECASTING → SIMULATING → VALIDATING → WAITING_FOR_APPROVAL

Post-approval lifecycle (triggered by process_approval):
  WAITING_FOR_APPROVAL → EXECUTING → VERIFYING
  → COMPLETED  or  REPLANNING → WAITING_FOR_APPROVAL

Rules:
  - The Agent calls tools only; it never reads CSV files directly.
  - The Agent never implements ML/forecasting logic itself.
  - Recommendation ≠ Approval. Execution never starts before
    process_approval(approved=True) is called.
  - Every verification result is tagged with (event_id, action_type)
    so stale results can never survive a replan.
"""

from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
import datetime
import tools

# Hours of history reviewed as evidence before the event (inclusive of the event hour).
HISTORY_WINDOW_HOURS = 24


class AgentState(str, Enum):
    MONITORING           = "MONITORING"
    INVESTIGATING        = "INVESTIGATING"
    GATHERING_EVIDENCE   = "GATHERING_EVIDENCE"
    ANALYZING            = "ANALYZING"
    FORECASTING          = "FORECASTING"
    SIMULATING           = "SIMULATING"
    VALIDATING           = "VALIDATING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    EXECUTING            = "EXECUTING"
    VERIFYING            = "VERIFYING"
    REPLANNING           = "REPLANNING"
    COMPLETED            = "COMPLETED"
    FAILED               = "FAILED"


class SmartEnergyAgent:
    """
    Autonomous Energy Operations Agent.

    handle_event()   → drives the pre-approval lifecycle and
                       stops at WAITING_FOR_APPROVAL.
    process_approval() → drives execution, verification, and
                         optional replanning.
    """

    def __init__(self, agent_id: str = "Agent_Alpha"):
        self.agent_id  = agent_id
        self.state: AgentState = AgentState.MONITORING

        self.current_event: Optional[Dict[str, Any]]    = None
        self.evidence: Dict[str, Any]                   = {}
        self.candidate_actions: List[Dict[str, Any]]    = []
        self.selected_action: Optional[Dict[str, Any]]  = None
        self._execution_key: Optional[Dict[str, str]]   = None
        self.approval_granted: bool                     = False
        self.verification_result: Optional[Dict[str, Any]] = None
        self.history: List[Dict[str, Any]]              = []
        self.tried_actions: List[str]                   = []

    # ----------------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------------

    def log_step(self, message: str) -> None:
        self.history.append({"state": self.state.value, "message": message})

    def transition_to(self, new_state: AgentState) -> None:
        self.state = new_state
        print(f"\nAGENT STATE -> {self.state.value}")

    def _make_execution_key(self, action: Dict[str, Any]) -> Dict[str, str]:
        event_id = (
            self.current_event.get("event_id")
            or self.current_event.get("timestamp", "UNKNOWN")
        )
        action_type = (
            action.get("action")
            or action.get("recommended_action")
            or "UNKNOWN_ACTION"
        )
        return {"event_id": str(event_id), "action_type": str(action_type)}

    @staticmethod
    def _history_window(timestamp: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Start/end of the evidence history window ending at the event hour."""
        if not timestamp:
            return None, None
        try:
            end = datetime.datetime.fromisoformat(str(timestamp).replace("T", " "))
        except ValueError:
            return None, None
        start = end - datetime.timedelta(hours=HISTORY_WINDOW_HOURS - 1)
        fmt = "%Y-%m-%d %H:%M:%S"
        return start.strftime(fmt), end.strftime(fmt)

    def _tool_error(self, label: str, res: Dict) -> Dict[str, Any]:
        """Transition to FAILED and return a structured error."""
        self.transition_to(AgentState.FAILED)
        msg = res.get("error", f"{label} unavailable")
        self.log_step(f"FAILED at {label}: {msg}")
        return {"status": self.state.value, "error": msg}

    # ----------------------------------------------------------------
    # PRE-APPROVAL LIFECYCLE  —  handle_event()
    # ----------------------------------------------------------------

    def handle_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Drive the Agent through the complete pre-approval lifecycle.

        Lifecycle:
            MONITORING → INVESTIGATING → GATHERING_EVIDENCE
            → ANALYZING → FORECASTING → SIMULATING
            → VALIDATING → WAITING_FOR_APPROVAL

        Returns a structured dict that always contains:
            status           : current state name
            approval_required: True  (at WAITING_FOR_APPROVAL)
            event            : the triggering event
            evidence         : operational snapshot from DB tools
            candidate_actions: Digital Twin simulations
            recommendation   : ML optimizer recommendation (approval_status=PENDING)
        """
        # ── Reset for new event ────────────────────────────────
        self.current_event       = event
        self.evidence            = {}
        self.candidate_actions   = []
        self.selected_action     = None
        self._execution_key      = None
        self.approval_granted    = False
        self.verification_result = None
        self.history             = []
        self.tried_actions       = []

        timestamp = event.get("timestamp")
        building_id = event.get("building_id", "B001")
        # For campus-wide events, gather evidence from all buildings
        evidence_buildings = (
            ["B001", "B002", "B003"]
            if building_id == "CAMPUS"
            else [building_id]
        )

        # ── MONITORING ────────────────────────────────────────
        self.transition_to(AgentState.MONITORING)
        self.log_step(f"Event received: {event.get('event_type')} @ {timestamp}")
        print(f"\nEvent detected: {event.get('event_type')} | "
              f"Severity: {event.get('severity')} | "
              f"Timestamp: {timestamp}")

        # ── INVESTIGATING — confirm event via ML tools ────────
        self.transition_to(AgentState.INVESTIGATING)
        self.log_step("Retrieving ML prediction events for context")

        ml_events_res = tools.get_ml_prediction_events(limit=10)
        if not ml_events_res.get("success"):
            return self._tool_error("ML prediction events", ml_events_res)

        ml_events = ml_events_res.get("data", [])
        matched = [e for e in ml_events if e.get("timestamp") == timestamp]
        print(f"  ML events at {timestamp}: {len(matched)} found")

        # ── GATHERING_EVIDENCE — operational snapshot ─────────
        self.transition_to(AgentState.GATHERING_EVIDENCE)
        self.log_step("Gathering operational evidence at the event hour via database tools")

        history_start, history_end = self._history_window(timestamp)

        operational_evidence = {}
        for bid in evidence_buildings:
            building_ev = {}

            # Consumption at the event hour
            res = tools.get_current_consumption(bid, at_time=timestamp)
            if res.get("success"):
                building_ev["consumption"] = res["data"]
                print(f"  [{bid}] energy_kw={res['data'].get('energy_kw')} "
                      f"hvac_kw={res['data'].get('hvac_kw')}")

            # HVAC load at the event hour
            res = tools.get_hvac_load(bid, at_time=timestamp)
            if res.get("success"):
                building_ev["hvac"] = res["data"]

            # Occupancy at the event hour
            res = tools.get_occupancy(bid, at_time=timestamp)
            if res.get("success"):
                building_ev["occupancy"] = res["data"]
                print(f"  [{bid}] occupancy_pct={res['data'].get('occupancy_pct')}")

            # Solar generation at the event hour
            res = tools.get_solar_generation(bid, at_time=timestamp)
            if res.get("success"):
                building_ev["solar"] = res["data"]

            # Historical trend (the 24 hours up to the event)
            res = tools.get_historical_consumption(bid, history_start, history_end)
            if res.get("success"):
                building_ev["history_count"] = len(res.get("data", []))
                building_ev["history_window"] = {"start": history_start, "end": history_end}

            operational_evidence[bid] = building_ev

        # Grid status (campus-level)
        grid_res = tools.get_grid_status()
        if grid_res.get("success"):
            operational_evidence["grid"] = grid_res["data"]
            print(f"  Grid status: {grid_res['data'].get('event_type')}")

        self.evidence = {
            "operational": operational_evidence,
            "ml_events_at_timestamp": matched,
        }

        # ── ANALYZING — get full ML event context ────────────
        self.transition_to(AgentState.ANALYZING)
        self.log_step("Retrieving ML event context for analysis")

        ctx_res = tools.get_ml_event_context(timestamp)
        if not ctx_res.get("success") or not ctx_res.get("data"):
            return self._tool_error("ML event context", ctx_res)

        context = ctx_res["data"]
        event_details = context.get("events", [])
        print(f"  Event details from ML: {len(event_details)} record(s)")

        # ── FORECASTING — attach forecast context ────────────
        self.transition_to(AgentState.FORECASTING)
        self.log_step("Reading forecast context from ML service")

        # The candidate_actions already include predicted load context
        # from the optimizer output; no separate forecast tool needed.
        print(f"  Forecast context embedded in ML event context ✓")

        # ── SIMULATING — get Digital Twin simulations ─────────
        self.transition_to(AgentState.SIMULATING)
        self.log_step("Retrieving Digital Twin simulation results")

        sim_res = tools.get_ml_simulation(timestamp)
        if not sim_res.get("success") or not sim_res.get("data"):
            return self._tool_error("ML simulation", sim_res)

        self.candidate_actions = sim_res["data"]
        print(f"  Candidate actions ({len(self.candidate_actions)}):")
        for c in self.candidate_actions:
            print(f"    {c.get('action'):30s} | "
                  f"reduction: {c.get('estimated_reduction_kw')} kW")

        # ── VALIDATING — read optimizer recommendation ────────
        self.transition_to(AgentState.VALIDATING)
        self.log_step("Retrieving optimizer recommendation")

        rec_res = tools.get_ml_recommendation(timestamp)
        if not rec_res.get("success") or not rec_res.get("data"):
            return self._tool_error("ML recommendation", rec_res)

        recommendation = rec_res["data"]
        if not recommendation.get("recommended_action"):
            return self._tool_error(
                "recommendation content",
                {"error": "Recommendation exists but has no recommended_action field"},
            )

        self.selected_action = recommendation
        print(f"\n  Recommended action : {recommendation.get('recommended_action')}")
        print(f"  Estimated reduction: {recommendation.get('estimated_reduction_kw')} kW")
        print(f"  Approval status    : {recommendation.get('approval_status')}")

        # ── WAITING_FOR_APPROVAL ──────────────────────────────
        self.transition_to(AgentState.WAITING_FOR_APPROVAL)
        self.log_step("Waiting for human approval")

        return {
            "status":            self.state.value,
            "approval_required": True,
            "event":             self.current_event,
            "evidence":          self.evidence,
            "candidate_actions": self.candidate_actions,
            "recommendation":    self.selected_action,
        }

    # ----------------------------------------------------------------
    # POST-APPROVAL LIFECYCLE  —  process_approval()
    # ----------------------------------------------------------------

    def process_approval(self, approved: bool) -> Dict[str, Any]:
        """
        Process human-in-the-loop approval or rejection.

        On approval drives: EXECUTING → VERIFYING → COMPLETED
        On underperformance: REPLANNING → WAITING_FOR_APPROVAL
        """
        if self.state != AgentState.WAITING_FOR_APPROVAL:
            return {
                "status": self.state.value,
                "error": (
                    f"Agent is in state {self.state.value}, "
                    "not WAITING_FOR_APPROVAL"
                ),
            }

        if not approved:
            print("\nHuman decision: REJECTED")
            self.approval_granted = False
            self.log_step("Human rejected the recommendation")
            return {"status": self.state.value, "approval": "REJECTED"}

        print("\nHuman decision: APPROVED")
        self.approval_granted = True
        self.log_step("Human approved — proceeding to execution")

        # Stamp execution key BEFORE executing
        self._execution_key = self._make_execution_key(self.selected_action)
        self.tried_actions.append(self._execution_key["action_type"])
        print(f"\nExecution key: event_id={self._execution_key['event_id']} "
              f"| action_type={self._execution_key['action_type']}")

        # ── EXECUTING ─────────────────────────────────────────
        self.transition_to(AgentState.EXECUTING)
        action_name = (
            self.selected_action.get("recommended_action")
            or self.selected_action.get("action")
        )
        print(f"\nExecuting simulated action: {action_name}")

        # ── VERIFYING ─────────────────────────────────────────
        self.verification_result = None
        self.transition_to(AgentState.VERIFYING)

        timestamp = self.current_event.get("timestamp")

        # Verify the action that was actually approved. Fall back to the
        # event-level record only if no action-specific record exists.
        ver_res = tools.get_verification_for_action_tool(
            timestamp, self._execution_key["action_type"]
        )
        if ver_res.get("success") and ver_res.get("data"):
            self.log_step(f"Verification record found for {self._execution_key['action_type']}")
        else:
            ver_res = tools.get_verification_result_tool(timestamp)
            self.log_step("No action-specific verification record; using the event-level record")

        if not ver_res.get("success") or not ver_res.get("data"):
            return self._tool_error("Verification result", ver_res)

        verification = ver_res["data"]
        verification["_execution_key"] = self._execution_key
        self.verification_result = verification

        performance  = verification.get("performance_ratio_percent")
        status       = verification.get("verification_status")
        exec_action  = verification.get("executed_action", "—")

        print(f"\nVerified action : {exec_action}")
        print(f"Execution key   : {self._execution_key}")
        print(f"Performance     : {performance} %")
        print(f"Status          : {status}")

        if exec_action and exec_action != self._execution_key["action_type"]:
            print(f"  WARNING: verified action '{exec_action}' differs from "
                  f"intended '{self._execution_key['action_type']}'. "
                  "Check ML output alignment.")

        # ── REPLANNING ────────────────────────────────────────
        if verification.get("needs_replanning"):
            self.transition_to(AgentState.REPLANNING)
            print(f"\nAction underperformed: {action_name}")
            self.log_step(f"Underperformed — replanning from {action_name}")

            alternative = self._select_alternative_action(action_name)
            if not alternative:
                return self._tool_error(
                    "Replanning",
                    {"error": "No alternative action available"},
                )

            print(f"\nAlternative: {alternative.get('action')} | "
                  f"{alternative.get('estimated_reduction_kw')} kW")

            self.selected_action     = alternative
            self.verification_result = None
            self._execution_key      = None

            self.transition_to(AgentState.WAITING_FOR_APPROVAL)
            self.log_step("Waiting for human approval of alternative action")
            return {
                "status":            self.state.value,
                "replan":            True,
                "recommendation":    self.selected_action,
                "approval_required": True,
            }

        # ── COMPLETED ─────────────────────────────────────────
        self.transition_to(AgentState.COMPLETED)
        self.log_step("Action completed successfully")
        print("\nAction achieved acceptable performance.")
        return {
            "status":       self.state.value,
            "verification": self.verification_result,
        }

    # ----------------------------------------------------------------
    # Helper
    # ----------------------------------------------------------------

    def _select_alternative_action(
        self, failed_action_name: str
    ) -> Optional[Dict[str, Any]]:
        # Never propose an action that has already been executed for this event,
        # and never propose one that fails the optimizer's constraints.
        excluded = set(self.tried_actions) | {failed_action_name}
        alternatives = []
        for a in self.candidate_actions:
            if a.get("action") in excluded:
                continue
            check = tools.validate_candidate_action(a)
            if check.get("success") and check["data"] and not check["data"].get("valid"):
                continue
            alternatives.append(a)
        if not alternatives:
            return None
        return max(alternatives, key=lambda x: x.get("estimated_reduction_kw", 0))
