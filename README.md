# Smart Energy AI

An autonomous operations agent for campus energy. It detects an event in the
data, gathers evidence, forecasts load, simulates candidate actions through a
digital twin, stops at a human approval gate, executes the approved action in
simulation, and verifies whether the action met its target.

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000/>.

`models/energy_forecast_model.pkl` was pickled with **scikit-learn 1.9.0**.
Loading it under an older version raises `InconsistentVersionWarning` and the
predictions are not guaranteed to match — install 1.9 or newer, or retrain with
`run_pipeline.py`.

## The walkthrough

1. **Activity** — pick an event and press *Analyze*. You land on Operations.
2. **AI Operations** — the lifecycle replays, candidates and their constraint
   checks appear, and the agent stops at the approval gate.
3. **Explain forecast** — LIME fits a local surrogate around the forecast for
   that hour and shows which features moved it, in kW.
4. **Approve** — the action executes in simulation and is verified against its
   target.
5. **Download PDF report** — the full incident record, five sections.

Both buttons on Operations stay disabled until there is something to act on.

## Layout

```
app.py                  HTTP API and the AgentService that keeps one agent alive
page_routes.py          page routes (note: /digital-twin, with a hyphen)
agent.py                the state machine
tools.py                data access, wrapping database.py and ml_service.py
optimizer.py            constraint checks and scoring
verification.py         did the action meet its target
ml_service.py           the trained forecaster
ml_explainer.py         LIME explanations
report_service.py       report structure, shared by the PDF and Markdown exports
rag_service.py          knowledge answers
simulator.py            the digital twin
templates/ static/      the dashboard
data/ models/ energy.db the dataset, the forecaster, the operational database
```

## Endpoints worth knowing

| Endpoint | Purpose |
|---|---|
| `POST /api/agent/run` | run an analysis |
| `POST /api/agent/approve` · `reject` · `reset` | the human gate |
| `POST /api/ml/explain` | LIME explanation for one hour |
| `GET /api/ml/explain/status` | whether the explainer is usable |
| `POST /api/report/pdf` | the incident report |

`/api/ml/explain` accepts `B001`, `B002`, `B003` or `CAMPUS`. A campus request
returns one explanation per building under `buildings`.

## On reading the LIME output

The panel shows the local fit quality (R²) next to every explanation, and it
varies a lot between buildings on the same hour — 0.79 for one, 0.01 for
another. A low R² means the surrogate fits that neighbourhood poorly and its
weights deserve less weight. The number is shown rather than hidden so a weak
explanation does not look authoritative.

LIME explains why the **model** predicted what it did. It is not a claim about
the physical cause of the event.

## Historical files

`INSTALL.md` and `app.py.diff` describe the migration to the multi-page UI.
Those steps are already applied — the files are kept for reference only, not as
instructions to follow.

`CHANGES.md` records the recent bug fixes and what was verified.

## Packaging note

`data/raw/building_data_genome/` is not in this archive. It holds the original
BDG2 source file, used only by `prepare_bdg2_data.py` and `explore_bdg2.py` to
regenerate `data/processed/`, which is already here. Nothing at runtime reads
it. Drop your copy back in if you want to re-run the data preparation.
