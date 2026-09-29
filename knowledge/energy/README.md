# Smart Energy AI knowledge base

This folder is the document store for the AI Knowledge assistant (`rag_service.py`).
Every `.md` and `.txt` file here is split into sections, indexed, and searched when
someone asks a question in the dashboard. Answers always list the files and
sections they were drawn from.

## What belongs here

- Operating guidelines (HVAC, solar, batteries, EV charging)
- Energy efficiency and demand response background
- Project-specific operating policy for the Smart Energy AI agent

## What does not belong here

Live operational data. Readings, events, simulations, recommendations and
verification results come from the database and the ML pipeline through the
agent's tools. The assistant keeps those separate from what it retrieves here.

## Adding a document

1. Save a Markdown (`.md`) or plain text (`.txt`) file in this folder.
2. Use `#` / `##` headings. Each heading becomes a separately retrievable section,
   so keep one topic per section.
3. Restart the app, or call `POST /api/rag/reload`.

## About the included documents

`smart_energy_ai_operating_policy.md` is derived directly from the project code
(`simulator.py`, `optimizer.py`, `verification.py`, `prediction_engine.py`,
`agent.py`, `config.py`). If those files change, update it.

The other documents are general reference notes written for this demo. They
describe widely used engineering practice, not site-specific rules. Replace or
supplement them with your organisation's vetted procedures before relying on
them operationally.
