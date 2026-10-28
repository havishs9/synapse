# Build progress

Checklist for Phases 1 to 3 (spec/05 section 2). A new session resumes from the first unchecked item.
Mark `[x]` with a one-line note when done. Phase 0 results: `docs/VERIFICATION.md`.

Decisions taken at the start of Phase 1 (2026-10-27, by the user): HDFS license approved; recipient (vendor)
name excluded as a feature; missing spec/03 sections built from files 00/01/02/05 (assumptions in
VERIFICATION.md); Serverless endpoint deployed in Phase 2 after the user logs in to the nebius CLI.

## Phase 1: hardcoded pipeline, no LLM agents

- [x] USAspending → dedupe → stratified sealed split → train J, A, I, E and prompted K in parallel → validation metrics → sealed-test metrics → Nemotron Ultra zero-shot baseline — run `phase1-procurement-b`: A-01 sealed macro-F1 0.631; Ultra 0.456 vs specialist 0.601 on the same 298 sealed rows
- [x] Every agent is a plain function that already reads/writes the exact JSON files in file 02 — Pydantic schemas in backend/schemas, agents in backend/agents
- [x] Training scripts emit JSON-line events; orchestrator writes `events.jsonl` — backend/sandbox/worker.py + launcher.py (local; Sandboxes lack permission)
- [x] `docs/DESIGN.md` written before frontend code
- [x] Minimal UI shell: sidebar, main chat, right pane with specialist tool panel calling the trained model, live Pareto scatter fed by SSE — verified with scripts/screenshots.py (docs/screenshots/)
- [x] Exit criterion: task 1 runs end to end and produces a real report card — runs/phase1-procurement-b/report_card.md; also via the UI (live build over SSE → specialist panel)

## Phase 2: agents and evaluation

- [ ] Planner with structured output plus deterministic fallback
- [ ] Search rounds (10% / 40% / 100%), Trainer error-fix loop, capped repair loop
- [ ] Calibration, cascade (H), frontier + seed reruns
- [ ] Feature-based reasons and teacher-explains-flags
- [ ] Narration feed and report card (per-class metrics, validation vs. sealed, "more data" curve)
- [ ] Task 2 (HDFS logs) through the same pipeline: windowing, template parsing, E features; planner picks a different winner
- [ ] Shared specialist server on the Nebius Serverless endpoint: per-specialist routes and API keys, versioned routes; artifacts in storage
- [x] Unit test proving sealed-test isolation — backend/tests/test_sealed_isolation.py (written in Phase 1)

## Phase 3: product and demo

- [ ] Clarifying questions → editable task card, with plan-change lines
- [ ] Compare mode with measured latency, cost and yearly projection
- [ ] "Use via API": URL, reveal-once API key with regenerate, curl and Python snippets
- [ ] v1 → v2 improvement flow: corrections, version gate, deploy or reject, rollback, version history
- [ ] Agent lanes, tournament bracket, budget meter
- [ ] UI polish pass against file 01 section 2.11, with screenshots
- [ ] Replay mode with recorded runs for both showcase tasks committed to the repo
- [ ] Public demo URL
- [ ] Complete README and `docs/FEEDBACK.md`
- [ ] `docs/DEVPOST.md` and `docs/VIDEO_SCRIPT.md`
- [ ] Record the 3-minute video (human)
- [ ] Acceptance criteria check (file 05 section 5)
