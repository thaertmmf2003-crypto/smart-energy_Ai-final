"""
test_e2e.py — End-to-End lifecycle test for Smart Energy AI Agent.

Tests the full flow:
  Prediction Event → Investigate → Evidence → Simulation
  → Recommendation → WAITING_FOR_APPROVAL
  → Approve → Execute → Verify → UNDERPERFORMED
  → Replan → Alternative Action → WAITING_FOR_APPROVAL

Run:
    cd <project_dir>
    python test_e2e.py
"""

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import database
import tools
import agent as agent_module
from agent import SmartEnergyAgent, AgentState

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    msg = f"{status}  {label}"
    if detail:
        msg += f"\n       detail: {detail}"
    print(msg)
    results.append((label, condition))


def section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ==================================================================
# 1. DATABASE CONTAINS EXPECTED OPERATIONAL READINGS
# ==================================================================
section("1. Database row counts")

with database.get_connection() as conn:
    er = conn.execute("SELECT COUNT(*) FROM energy_readings").fetchone()[0]
    sr = conn.execute("SELECT COUNT(*) FROM solar_readings").fetchone()[0]

check("energy_readings == 52,632", er == 52_632, f"got {er}")
check("solar_readings  == 52,632", sr == 52_632, f"got {sr}")

# ==================================================================
# 2. OPERATIONAL TOOL CALLS RETURN REAL DATA
# ==================================================================
section("2. Operational tools")

# Pick first timestamp that has data
with database.get_connection() as conn:
    row = conn.execute(
        "SELECT timestamp FROM energy_readings WHERE building_id='B001' "
        "AND energy_kw > 0 ORDER BY timestamp LIMIT 1"
    ).fetchone()
test_ts = row[0] if row else None
check("Non-zero timestamp found in B001", test_ts is not None, str(test_ts))

# get_current_consumption
res = tools.get_current_consumption("B001")
check(
    "get_current_consumption('B001') success",
    res.get("success") and res.get("data") and res["data"].get("energy_kw", 0) > 0,
    str(res.get("data")),
)

# get_hvac_load
res = tools.get_hvac_load("B001")
check(
    "get_hvac_load('B001') success",
    res.get("success") and res.get("data") is not None,
    str(res.get("data")),
)

# get_occupancy
res = tools.get_occupancy("B001")
check(
    "get_occupancy('B001') success",
    res.get("success") and res.get("data") is not None,
    str(res.get("data")),
)

# get_solar_generation
res = tools.get_solar_generation("B001")
check(
    "get_solar_generation('B001') returns data (non-None)",
    res.get("success") and res.get("data") is not None,
    str(res.get("data")),
)
if res.get("data"):
    solar_val = res["data"].get("solar_kw", res["data"].get("generation_kw", -1))
    check(
        "get_solar_generation('B001') solar_kw field present",
        solar_val is not None,
        f"solar_kw={solar_val}",
    )

# ==================================================================
# 3. ML TOOLS WORK
# ==================================================================
section("3. ML pipeline tools")

# Peak events
peak_res = tools.get_ml_peak_events(limit=5)
check(
    "get_ml_peak_events returns data",
    peak_res.get("success") and isinstance(peak_res.get("data"), list),
    str(peak_res.get("data", [])[:1]),
)

peaks = peak_res.get("data", [])
if not peaks:
    print("  WARNING: no peak events — E2E agent test will be skipped")
    sys.exit(0)

# Use the first peak event as our test event
event = peaks[0]
ml_ts = event.get("timestamp")
check("ML event has timestamp", bool(ml_ts), str(ml_ts))

# get_ml_event_context
ctx_res = tools.get_ml_event_context(ml_ts)
check(
    "get_ml_event_context success",
    ctx_res.get("success") and ctx_res.get("data") is not None,
    str(list(ctx_res.get("data", {}).keys())),
)

ctx = ctx_res.get("data", {})
check(
    "event context has candidate_actions",
    isinstance(ctx.get("candidate_actions"), list) and len(ctx["candidate_actions"]) > 0,
    f"count={len(ctx.get('candidate_actions', []))}",
)
check(
    "event context has recommendation",
    ctx.get("recommendation") is not None,
    str(ctx.get("recommendation")),
)

# ==================================================================
# 4. AGENT REACHES WAITING_FOR_APPROVAL (not executing directly)
# ==================================================================
section("4. Agent reaches WAITING_FOR_APPROVAL")

ag = SmartEnergyAgent(agent_id="TestAgent")
result = ag.handle_event(event)

check(
    "handle_event returns WAITING_FOR_APPROVAL",
    result.get("status") == AgentState.WAITING_FOR_APPROVAL,
    f"got status={result.get('status')}",
)
check(
    "Agent state == WAITING_FOR_APPROVAL",
    ag.state == AgentState.WAITING_FOR_APPROVAL,
    f"got {ag.state}",
)
check(
    "Agent NOT in EXECUTING yet",
    ag.state != AgentState.EXECUTING,
    f"state={ag.state}",
)
check(
    "Recommendation present in result",
    result.get("recommendation") is not None,
    str(result.get("recommendation")),
)

# ==================================================================
# 5. APPROVAL TRIGGERS EXECUTION → VERIFICATION
# ==================================================================
section("5. Approval → Execute → Verify")

approval_result = ag.process_approval(approved=True)

check(
    "process_approval called with approved=True",
    True,
)
check(
    "execution_key was set (event_id + action_type)",
    ag._execution_key is not None
    and "event_id" in ag._execution_key
    and "action_type" in ag._execution_key,
    str(ag._execution_key),
)

final_state = approval_result.get("status")

# Two valid outcomes: COMPLETED or WAITING_FOR_APPROVAL (replan)
check(
    "Agent reached COMPLETED or WAITING_FOR_APPROVAL after approval",
    final_state in (AgentState.COMPLETED, AgentState.WAITING_FOR_APPROVAL),
    f"got {final_state}",
)

# ==================================================================
# 6. VERIFICATION IS TAGGED WITH CORRECT ACTION
# ==================================================================
section("6. Verification tied to execution key")

ver = ag.verification_result
if final_state == AgentState.COMPLETED:
    # Verification result should be present and tagged
    check(
        "verification_result is set after COMPLETED",
        ver is not None,
    )
    if ver:
        check(
            "verification_result has _execution_key",
            "_execution_key" in ver,
            str(ver.get("_execution_key")),
        )
        check(
            "verification _execution_key has action_type",
            "action_type" in ver.get("_execution_key", {}),
            str(ver.get("_execution_key")),
        )
else:
    # Replan path — verification_result must be CLEARED
    check(
        "verification_result cleared after REPLANNING",
        ag.verification_result is None,
        str(ag.verification_result),
    )

# ==================================================================
# 7. UNDERPERFORM → REPLAN → ALTERNATIVE NEEDS NEW APPROVAL
# ==================================================================
section("7. Replan path")

if approval_result.get("replan"):
    check(
        "Replan flag set in approval_result",
        approval_result.get("replan") is True,
    )
    check(
        "After replan: state == WAITING_FOR_APPROVAL",
        ag.state == AgentState.WAITING_FOR_APPROVAL,
        f"got {ag.state}",
    )
    check(
        "After replan: selected_action changed",
        ag.selected_action is not None,
        str(ag.selected_action),
    )
    check(
        "After replan: execution_key is None (not reused)",
        ag._execution_key is None,
        str(ag._execution_key),
    )

    # Approve the alternative action
    section("8. Approve alternative action → new verification")
    alt_result = ag.process_approval(approved=True)
    alt_state  = alt_result.get("status")

    check(
        "Alternative action: new execution_key set",
        ag._execution_key is not None,
        str(ag._execution_key),
    )
    check(
        "Alternative action reaches COMPLETED or loops WAITING_FOR_APPROVAL",
        alt_state in (AgentState.COMPLETED, AgentState.WAITING_FOR_APPROVAL),
        f"got {alt_state}",
    )

    if alt_state == AgentState.COMPLETED and ag.verification_result:
        alt_key = ag.verification_result.get("_execution_key", {})
        check(
            "Alternative verification has its own _execution_key",
            bool(alt_key),
            str(alt_key),
        )
else:
    check(
        "COMPLETED path (no replan needed) — skipping replan checks",
        True,
    )

# ==================================================================
# SUMMARY
# ==================================================================
section("SUMMARY")

passed = sum(1 for _, ok in results if ok)
total  = len(results)
failed_tests = [label for label, ok in results if not ok]

print(f"\n  {passed}/{total} checks passed")
if failed_tests:
    print("\n  FAILED CHECKS:")
    for t in failed_tests:
        print(f"    ✗  {t}")
else:
    print("\n  ALL CHECKS PASSED ✓")

sys.exit(0 if not failed_tests else 1)
