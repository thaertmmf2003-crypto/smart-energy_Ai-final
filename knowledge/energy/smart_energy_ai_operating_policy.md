# Smart Energy AI operating policy (project-specific)

This document describes how the Smart Energy AI agent in this project actually
behaves. It is derived from the project source code.

## Campus buildings
The campus has three buildings (config.py):
- B001 Administration, working hours 08:00 to 17:00, solar and EV charging
- B002 Labs, working hours 07:00 to 20:00, solar and battery storage
- B003 Classrooms, working hours 08:00 to 18:00, solar
Maximum power values in config.py are simulated operational assumptions, not
measured ratings.

## How events are detected (prediction_engine.py)
- ENERGY_ANOMALY: actual building energy differs from the ML forecast by at least
  25 % of the predicted demand. Deviations of 50 % or more are HIGH severity,
  otherwise ELEVATED. The event value is the residual in percent.
- PEAK_DEMAND_RISK: predicted campus demand is high compared with its own
  history. ELEVATED, HIGH and CRITICAL correspond to the 90th, 95th and 99th
  percentiles of predicted campus demand. The event value is predicted demand as
  a percentage of the simulated grid import limit.

## Candidate actions simulated by the digital twin (simulator.py)
- HVAC_SETPOINT_ADJUSTMENT: reduces the HVAC load by 15 %.
- EV_CHARGING_SHIFT: shifts 80 % of the active EV charging load.
- BATTERY_DISCHARGE: discharges up to 25 kW, only when battery SOC is above 30 %.
- COMBINED_ACTION: applies all three together.
All actions are simulated. No physical equipment is controlled.

## How the optimizer chooses (optimizer.py)
Constraints a candidate must pass:
- Estimated reduction of at least 1 kW.
- Battery and combined actions require battery SOC above 30 %.
- EV and combined actions require an active EV load greater than 0 kW.
Scoring: score = estimated reduction x severity weight - disruption rank x
severity penalty. Disruption ranks are EV shift 1, battery 2, HVAC 3,
combined 4. For CRITICAL events reduction dominates (weight 1.0, penalty 2);
for HIGH the weight is 0.9 with penalty 4; for ELEVATED the weight is 0.75 with
penalty 6, which favours less disruptive actions. The highest-scoring valid
candidate becomes the recommendation.

## Human approval
The agent stops at WAITING_FOR_APPROVAL. Recommendation is not approval.
Nothing is executed until an operator approves. A rejection is logged and no
action is executed.

## Verification (verification.py)
After simulated execution the achieved reduction is compared with the expected
reduction. If it reaches at least 80 % of the expected reduction the result is
SUCCESS; otherwise it is UNDERPERFORMED and needs replanning.

## Replanning (agent.py)
When verification reports that replanning is needed, the agent excludes every
action already executed for the event and every candidate that fails the
optimizer's constraints, selects the remaining candidate with the largest
estimated reduction, and returns to WAITING_FOR_APPROVAL. The alternative also
needs human approval before execution, and it is verified against its own
record (verification_by_action.csv). If no candidate remains, the agent stops.

## Evidence (agent.py)
Evidence is read at the event hour: consumption, HVAC, occupancy and solar come
from the reading at or just before the event timestamp, and the history covers
the 24 hours up to the event.
