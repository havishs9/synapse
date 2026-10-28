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

- [x] Planner with structured output plus deterministic fallback — llm_plan (Nemotron Ultra, json_schema) validated against the ladder; adds K when cloud_ok so H can be evaluated
- [x] Search rounds (10% / 40% / 100%), Trainer error-fix loop, capped repair loop — run p2-procurement-a: 27 → 7 → 3 configs; repair loop exercised by the integration test
- [x] Calibration, cascade (H), frontier + seed reruns — session 2 fixes (issues 1-4 below); rerun `p2-procurement-c`: recommended A-04 (cheapest meeting target), calibration skipped (ECE 0.044 → 0.047 cross-fit), cascade H(A-04→K-03) shipped: escalates 43%, +0.037 on the 150-record sample; sealed macro-F1 0.635 (3,368 records); Ultra 0.456 vs specialist 0.610 on the same 298 sealed rows; spend $0.10
- [x] Feature-based reasons and teacher-explains-flags — reasons in J/A/E/I; `explain: true` calls Nemotron Ultra (labeled as a cloud call); not yet shown in the UI
- [x] Narration feed and report card (per-class metrics, validation vs. sealed, "more data" curve)
- [~] Task 2 (HDFS logs) through the same pipeline: windowing, template parsing, E features; planner picks a different winner — runs end to end (p2-logs-b: sealed recall@1%FPR 1.000), but the winner is A (TF-IDF), same family as procurement; see VERIFICATION.md 'Logs winner'; rerun `p2-logs-c` (session 2): winner A-12 again, sealed recall@1%FPR 1.000 (2,850 records), Ultra 0.000 at 1% FPR on 300 sealed rows
- [x] Shared specialist server on the Nebius Serverless endpoint: per-specialist routes and API keys, versioned routes — live at https://port8000-b3arav7mmzek3n6.tunnel.applications.eu-west2.nebius.cloud (endpoint `aiendpoint-e04txwn4spe6v76nes`, cpu-d3 2vcpu-8gb); live/pinned routes, cross-specialist 403, revocation and cascade escalation verified on the URL (VERIFICATION.md §4). Artifacts: documented fallback (downloaded from the public repo at startup), not Object Storage
- [x] Unit test proving sealed-test isolation — backend/tests/test_sealed_isolation.py (written in Phase 1)

## Phase 2b: model variety (added by the user 2026-10-28, before Phase 3)

Goal: the three tasks end up on different parts of the ladder, measured, not forced. Targets are fixed before
each run and never adjusted after seeing results.

- [ ] 3-step cascade H: cheap stage (rung 1) → embedding stage (best B/C/I, if it reached the final round) → LLM stage (best K/L). Each stage answers when its calibrated confidence ≥ its threshold; the LLM answers the rest. 2-stage variants (cheap → embeddings, cheap → LLM) stay possible.
  - Fit both thresholds on the LLM's validation sample (grid over tau1 × tau2). Among combinations within `CASCADE_TOLERANCE` of the best score, take the lowest expected cost per record (share per stage × that stage's measured `cost_per_1m_usd`), which replaces "least escalation".
  - Report the split per stage on validation and on the sealed test ("TF-IDF 55% / embeddings 30% / Nano 15%"): eval_report, report card, narration, and which stage answered on each prediction.
  - `CascadeH` generalised to N stages (bundle, shared server, snapshot rule: cascades with I/K/L stages store texts). Unit tests for the threshold fit and the N-stage predict.
- [ ] Task 3 (spec file 05, optional task): support ticket routing on Banking77 (77 intents, CC-BY-4.0, already in `config/datasets.yaml` and `data/raw/banking77/`). Demo task card `support_tickets`, `cloud_ok: true` so the planner can try B (Qwen3-Embedding-8B + MLP), target macro-F1 0.85 fixed before the first run. `make build-support`.
- [ ] Rerun procurement and logs with the 3-step cascade (same targets as before); record splits and spend.
- [ ] Snapshot all three specialists, push, restart the endpoint so it serves three; update VERIFICATION.md and the "different winner" item with the measured winners.

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
- [ ] Users with per-user separation on one shared endpoint (agreed with the team 2026-10-28; extends the spec, which has no accounts). Depends on the storage choice below.
  - Login, and a `user_id` on every run, specialist, version and API key; every route checks ownership.
  - Files under `users/<user_id>/...` in storage; specialist keys stay per specialist, scoped to their owner.
  - One shared serving endpoint for everyone: load a specialist's bundle from storage on first call, keep recently used ones in memory (LRU). No endpoint per user (each is ~$0.07/h while running, minutes to start, no scale-to-zero seen). Later: more shared endpoints with routing by user, or a dedicated endpoint as a paid option.
  - Serve only bundles our own pipeline wrote (joblib loading runs code); never accept uploaded model files.
  - Per-user budgets for training spend and for cascade escalations on public predictions.
- [ ] Durable storage instead of local disk and the repo download. Decided 2026-10-28: **Supabase** (Postgres for records: users, specialists, versions, hashed keys, runs; Supabase Auth for login) and **Nebius Object Storage** for files (bundles, run folders, uploaded datasets) under `users/<user_id>/...`. Nebius Managed PostgreSQL was considered (pgvector, but no auth, ~$0.14/h for 2 vCPU / 8 GB) and dropped for now. Fixes keys being lost on endpoint restart and the missing replay runs on the endpoint. Replaces the spec's SQLite: update file 02. Needs from a human: a Supabase project (URL, anon key, service key, JWT secret in `.env`) and a Nebius Object Storage bucket + access key.
- [ ] Data sourcing beyond the pre-downloaded demo datasets (spec file 03 §1.1; today the Data agent only loads registry datasets by key):
  - Upload in the chat (CSV, JSONL, plain-text logs) → saved as the user's own dataset → same dedupe / sealed split as the demo data. Unlabeled uploads: teacher labels from Nano (file 03 §1.2), reported as teacher-labeled.
  - Not enough labeled data → vetted registry first, then live Tavily and Hugging Face Hub search: record the license, reject incompatible ones, format-match score against the user's samples, user approves in the chat. The demo never depends on live results.
  - Synthetic data from Nemotron only to fill gaps (rare classes, format mismatch), in the user's format, always reported separately from real data. Today synthetic data is only added in repair rounds.

## Handoff notes (2026-10-28, end of session 1)

Legend: `[x]` done, `[~]` done with open issues, `[ ]` not started.

### Set up on a new machine
1. `make setup` (needs Python 3.12 and Node 22; macOS also needs `brew install libomp` for LightGBM).
2. Copy `.env` from a teammate (never commit it). Keys used: NEBIUS_API_KEY, NEBIUS_PROJECT_ID, NEBIUS_BASE_URL, API_KEY_PEPPER, SPECIALIST_ADMIN_TOKEN; TRAINING_BACKEND=local.
3. `make demo-data` (~10 min: USAspending API, PSC workbook, HDFS from Zenodo). `data/`, `runs/` and `artifacts/` are gitignored, so no runs or specialists come with the repo.
4. `make test` (32 tests, ~25 s), then `.venv/bin/python -m backend.cli build procurement` / `build hdfs_logs`, then `make dev` and open http://127.0.0.1:8000.

### Open issues found in the last runs (fix before recording)
1. **FIXED (session 2, code): last procurement run failed** (`p2-procurement-b`): `APIConnectionError` in the sealed exam (cloud I-06 embedding calls) after a ~50 s outage; the client gave up after 15 s of retries. Backoff now waits ~90 s in total (2, 4, 8, 16, 30, 30 s) for every network call. **Rerun still needed** (needs `.env`).
2. **FIXED (session 2, code): recommendation picked cloud I-06 as "cheapest that meets target".** The token cost was not missing (I-06's metrics include $0.27/1M of embedding tokens). Real cause: successive halving ranked survivors on score alone, so every cheap TF-IDF (A) config was cut in round 1-2, and "cheapest that meets the target" was chosen among only the 3 finalists (I-06, I-04, K-09). Each round now also carries forward the candidates on that round's cost/score frontier (`cost_frontier` in trainer_agent.py; test in test_evaluation.py).
3. **FIXED (session 2, code): calibration made ECE worse for kNN (I)**: temperature scaling is now skipped (T = 1, recorded as `skipped`) when cross-fit ECE doesn't improve.
4. **FIXED (session 2, code): cascade I-06 → K-03 escalated 47% for +0.014.** The escalation threshold is now the one that escalates least among thresholds within 0.005 of the best cascade score (the >0.01 gain rule to ship H is unchanged).
5. **Logs vs procurement winners are both family A** (acceptance criterion "different winner" currently fails). Don't force it; report honestly or see whether the cascade changes procurement's winner.
6. UI polish noted in Phase 1 screenshots: "Building…" button stays after the build, cost per record format ($1.1e-9), clearer "Ultra vs specialist" stat label.

### Session 2 (2026-10-28) status
- Done: setup on a second machine (Node 20 works), issues 1-4 fixed with tests (37 pass), deploy.sh fixed (one `--env` per variable; preset/disk from pricing.yaml; `DRY_RUN=1`), both showcase specialists rebuilt and snapshotted to `artifacts/demo/specialists/` (keys stripped, no raw HDFS lines: the logs bundle's `example_input` is dropped by `scripts/snapshot_demo.py`).
- Resolved blocker: `nebius ai endpoint create --dry-run` returned PermissionDenied until billing was activated. Tenant `orange-chinchilla-tenant-s5f` reports `suspension_state: SUSPENDED` (v1 API), usually meaning billing isn't activated. A human must activate billing / redeem credits in console.nebius.com, then run `DRY_RUN=1 make deploy`, then `make deploy`.
- Found for Phase 3: the deployed app has no UI (bootstrap.sh doesn't build `frontend/dist`); run files store absolute `metrics_path`s from the machine that ran them; `snapshot_demo.py` can't prune when RUNS_DIR is `./runs` and `runs/*` is gitignored; the logs specialist has no "Try an example" (raw window stripped); anyone on the public demo can regenerate (revoke) a specialist key; cascade escalations on public predictions spend Nano credits outside the daily demo guard; `main.py` `_reload_remote` imports a missing `backend.serving.sync` (silently ignored).

### Next steps
- Phase 2 is complete (2026-10-28). The endpoint is running and billed (~$0.07/h); stop it with `~/.nebius/bin/nebius ai endpoint stop aiendpoint-e04txwn4spe6v76nes` when not needed. Restarts clear API keys (regenerate via the app).
- Old note: create the Serverless endpoint. Install the CLI (`curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash`), run `nebius profile create` (browser login), then `make deploy` (deploy/serverless/deploy.sh; needs the repo pushed to GitHub because the endpoint downloads it at startup). Endpoint compute is billed to Nebius AI Cloud, not Token Factory credits. Then mark Phase 2 complete and commit "Phase 2 complete".
- Phase 3 is not started. Stubs to fill: frontend/src/components/PanelOverlays.tsx (Compare, Use dialog), PanelExtras.tsx (version history, corrections, improve), TrainingExtras.tsx (agent lanes, bracket, budget meter), lib/useIntake.ts (clarifying questions → editable task card). Backend still needs intake endpoints, `/compare`, `/corrections`, `/improve`. `scripts/snapshot_demo.py` is written for replay recordings but not yet run.
