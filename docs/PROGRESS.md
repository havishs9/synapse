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
- [~] Task 2 (HDFS logs) through the same pipeline: windowing, template parsing, E features; planner picks a different winner — runs end to end (p2-logs-b: sealed recall@1%FPR 1.000), but the winner is A (TF-IDF), same family as procurement. Phase 2b (2026-10-28): the single-model winner is still family A on all three tasks (cheapest meeting each target), but what ships differs: logs = TF-IDF alone, procurement = TF-IDF → Nano cascade (36% to the LLM), support tickets = TF-IDF → Qwen3 embeddings + MLP cascade (24% to embeddings); see VERIFICATION.md 'Logs winner'; rerun `p2-logs-c` (session 2): winner A-12 again, sealed recall@1%FPR 1.000 (2,850 records), Ultra 0.000 at 1% FPR on 300 sealed rows
- [x] Shared specialist server on the Nebius Serverless endpoint: per-specialist routes and API keys, versioned routes — live at https://port8000-b3arav7mmzek3n6.tunnel.applications.eu-west2.nebius.cloud (endpoint `aiendpoint-e04txwn4spe6v76nes`, cpu-d3 2vcpu-8gb); live/pinned routes, cross-specialist 403, revocation and cascade escalation verified on the URL (VERIFICATION.md §4). Artifacts: documented fallback (downloaded from the public repo at startup), not Object Storage
- [x] Unit test proving sealed-test isolation — backend/tests/test_sealed_isolation.py (written in Phase 1)

## Phase 2b: model variety (added by the user 2026-10-28, before Phase 3)

Goal: the three tasks end up on different parts of the ladder, measured, not forced. Targets are fixed before
each run and never adjusted after seeing results.

- [x] 3-step cascade H: cheap stage (rung 1) → embedding stage (best B/C/I, if it reached the final round) → LLM stage (best K/L). Each stage answers when its calibrated confidence ≥ its threshold; the LLM answers the rest. 2-stage variants (cheap → embeddings, cheap → LLM) stay possible.
  - Fit both thresholds on the LLM's validation sample (grid over tau1 × tau2). Among combinations within `CASCADE_TOLERANCE` of the best score, take the lowest expected cost per record (share per stage × that stage's measured `cost_per_1m_usd`), which replaces "least escalation".
  - Report the split per stage on validation and on the sealed test ("TF-IDF 55% / embeddings 30% / Nano 15%"): eval_report, report card, narration, and which stage answered on each prediction.
  - `CascadeH` generalised to N stages (bundle, shared server, snapshot rule: cascades with I/K/L stages store texts). Unit tests for the threshold fit and the N-stage predict.
  - Done 2026-10-28: `fit_cascade_chain` (evaluator), `Orchestrator._cascade` tries every chain that starts with the winner (H wraps the recommended model, spec file 03) and keeps the cheapest within tolerance of the best if it gains > 0.01; predictions return `answered_by`; old 2-stage bundles still load. Also added: B/C get an MLP head (`head: mlp`), the chosen LLM stage is scored on 400 validation rows before fitting thresholds (150 was ~2 rows per class for 77 intents), and cloud finalists' latency is re-measured alone after the search (during the search ~40 jobs share the API and rate-limit retries counted as latency: single embedding calls took 0.8 to 20 s). Fixed: the cascade's Pareto point was never saved in eval_report.json (report card showed n/a; `scripts/backfill_cascade_point.py` repaired the runs below).
- [x] Task 3 (spec file 05, optional task): support ticket routing on Banking77 (77 intents, CC-BY-4.0, already in `config/datasets.yaml` and `data/raw/banking77/`). Demo task card `support_tickets`, `cloud_ok: true` so the planner can try B (Qwen3-Embedding-8B + MLP), target macro-F1 0.85 fixed before the first run. `make build-support`.
  - Run `p2b-support-c`: winner A-11 (TF-IDF, validation 0.877, cheapest meeting 0.85), shipped as cascade H(A-11→B-02) where B-02 is Qwen3-Embedding-8B + MLP: TF-IDF answers 75.6%, embeddings 24.4% on the sealed test; sealed macro-F1 0.933 on 2,474 records; Ultra 0.738 vs specialist 0.913 on the same 300 sealed rows; $0.12 per 1M predictions (B-02 alone: validation 0.936, $0.47 per 1M); spend $0.31. Runs a/b were stopped before the sealed test: (a) latency measured under API contention, (b) a cascade that didn't start with the winner (B-02→K-12, 0% to the LLM) was picked; both fixed above.
- [x] Rerun procurement and logs with the 3-step cascade (same targets as before); record splits and spend.
  - `p2b-procurement-d`: the Nemotron planner chose J, A, I, C, K this time (local embeddings only, no B); no embedding candidate reached the final round, so only TF-IDF → LLM chains were possible. Winner A-07 (validation 0.617), shipped H(A-07→K-11): TF-IDF answers 64.1%, Nano 35.9% on the sealed test; sealed macro-F1 0.647 on 3,368 records; deployed as v2 (beats v1's 0.635); Ultra 0.456 vs specialist 0.627 on the same 298 sealed rows; $25.88 per 1M predictions; spend $0.15.
  - `p2b-logs-d`: winner A-12 again (sealed recall@1%FPR 1.000 on 2,850 records, PR-AUC 0.9997); H(A-12→K-01) gains nothing at 1.000, so no cascade; v2 not deployed (doesn't beat the live v1's 1.000); v1 stays live; spend $0.07.
- [x] Snapshot all three specialists, push, restart the endpoint so it serves three; update VERIFICATION.md and the "different winner" item with the measured winners. — commit 11c70ba pushed; endpoint restarted 2026-10-28 (healthy with 3 specialists after ~10 min); live checks in VERIFICATION.md Phase 2b.

## Phase 3: product and demo

Split between Raj (backend platform) and Havish (product, frontend, hosting, demo): see `docs/TEAM_PLAN.md` for the contracts, file ownership and setup.

- [x] [Raj] Builds list stub `GET /api/builds` (contract TEAM_PLAN §1), `?after=n` on the event stream, `CORS_ORIGINS` (2026-10-28)
- [x] [Raj] Build queue and workers (done 2026-10-29; first AI Job build verified, see VERIFICATION.md; the endpoint's dispatcher switches over with the redeploy): `builds` table in Supabase, dispatcher with caps, one Nebius AI Job per build, heartbeats, cancel/retry, events in Postgres (TEAM_PLAN §2.3)
- [ ] [Raj] Pre-built image in Nebius Container Registry; fix `_reload_remote`; per-user budgets (TEAM_PLAN §2.4-2.5)
- [x] [Havish] Builds sidebar and cascade split display (TEAM_PLAN §3.2-3.3) — sidebar on `GET /api/builds` (polls every 4 s while one runs), status/stage/round/spend, reopens the training view, Cancel/Retry (show the 501 message until the queue lands); split in the panel header, dashboard and history ("TF-IDF 64% / Prompted Nemotron 36%"), `answered_by` on each prediction and in batch CSV (2026-10-29)

- [x] [Havish] Clarifying questions → editable task card, with plan-change lines — `POST /api/intake/start` (Nemotron Ultra, JSON schema: task match + question wording; canned wording and keyword match as fallback) and `/api/intake/card` (answers → card, one plan-change line per answer, free text parsed by Ultra with number parsing as fallback); card fields editable, lines recomputed on each edit
- [x] [Havish] Compare mode with measured latency, cost and yearly projection — `POST /api/specialists/{id}/compare`: both calls in parallel; Ultra latency and token cost measured on the call (cached answer labeled "cached" if unreachable); specialist cost = measured cost per 1M of the stage that answered; projection from the build's measured costs × task card volume, method on hover
- [x] [Havish] "Use via API": URL, reveal-once API key with regenerate, curl and Python snippets — live and pinned routes, Create/Regenerate (revokes only the caller's earlier key), copy buttons
- [x] [Havish] v1 → v2 improvement flow: corrections, version gate, deploy or reject, rollback, version history — `backend/improve.py` + routes; recorded: procurement v2 → v3 (95 held-back corrections, 0.655 vs 0.647 on 3,368 sealed records, $0.08) and support v1 → v2 (18 + 54 variants, 0.935 vs 0.933); chained improves keep the original build's sealed set; tests in `test_product.py` (deploy, reject, chain, rollback, sealed file unchanged, Object Storage)
- [x] [Havish] Agent lanes, tournament bracket, budget meter — `TrainingExtras.tsx`
- [x] [Havish] UI polish pass against file 01 section 2.11, with screenshots — `docs/screenshots/` (light, dark, 390 px mobile); `make screenshots` is the frontend smoke test (spec 05 §4); Phase 1 notes fixed (build button state, cost format, "Same sealed records: specialist vs Nemotron Ultra" label); logs "Try a template example" built from event templates and labeled
- [x] Replay mode with recorded runs for both showcase tasks committed to the repo — all three tasks in `artifacts/demo/runs/` (2026-10-28), served by `make replay`; saved paths made relative
- [~] [Havish] Public demo URL (frontend on Vercel, API on the Nebius endpoint) — `vercel.json` and `VITE_API_BASE_URL` support done; still needs Havish's Vercel login/project link and `CORS_ORIGINS` with the Vercel URL on the endpoint (Raj redeploys)
- [x] [Havish] Complete README and `docs/FEEDBACK.md` — README has placeholders for the demo URL and video link
- [x] [Havish] `docs/DEVPOST.md` and `docs/VIDEO_SCRIPT.md`
- [ ] [Havish] Record the 3-minute video (human)
- [~] [Both] Acceptance criteria check (file 05 section 5) — Havish's pass, 2026-10-29:
  - [x] Describe procurement → questions → task card → build with live Pareto: in replay (smoke test); live builds use the unchanged `POST /api/builds` (not re-run through the new UI this session)
  - [x] Specialist panel returns label, confidence, reason (and which stage answered)
  - [x] Compare: both outputs, measured latency and cost, yearly projection
  - [x] Report card: sealed per-class metrics, validation vs sealed, baseline, teacher agreement (labeled), seed error bars, Pareto chart (existing report)
  - [~] HDFS through the same pipeline with a different winner: the single-model winner is TF-IDF on all three tasks; what ships differs (TF-IDF alone for logs, TF-IDF → Nano for procurement, TF-IDF → Qwen3 for support). Reported honestly in the README
  - [x] v1 → v2 through the gate: deploy (two recorded runs), reject and rollback (tests)
  - [x] Per-specialist versioned routes and keys, cross-specialist 403 (Phase 2, VERIFICATION §4)
  - [x] Replay reproduces the three builds and two improve runs
  - [ ] Public demo URL (Vercel link + `CORS_ORIGINS`)
  - [x] UI per spec 01 §2.11 (screenshots); builds list added to the sidebar per TEAM_PLAN §3.3
  - [~] README, VERIFICATION, FEEDBACK done; demo URL and video link still placeholders
  - [~] Tests: 64 pass; `test_builds_api.py::test_cancel_retry_not_yet_and_unknown` fails when `frontend/dist` exists (VERIFICATION, issue 0)
- [~] [Raj backend, Havish login UI] Users with per-user separation on one shared endpoint. **Backend done 2026-10-28** (`backend/auth.py`: Supabase token verification, `AUTH_REQUIRED` switch, ownership on every specialist, key, run and build route, per-user keys on demo specialists); login screens done 2026-10-29 (Google sign-in via Supabase behind `VITE_AUTH_ENABLED`, sign-out in the sidebar; needs `VITE_SUPABASE_URL` and the anon key in `frontend/.env.local` / Vercel); the switch to `AUTH_REQUIRED=true` on the public deployment still to do (agreed with the team 2026-10-28; extends the spec, which has no accounts). Depends on the storage choice below.
  - Login, and a `user_id` on every run, specialist, version and API key; every route checks ownership.
  - Files under `users/<user_id>/...` in storage; specialist keys stay per specialist, scoped to their owner.
  - One shared serving endpoint for everyone: load a specialist's bundle from storage on first call, keep recently used ones in memory (LRU). No endpoint per user (each is ~$0.07/h while running, minutes to start, no scale-to-zero seen). Later: more shared endpoints with routing by user, or a dedicated endpoint as a paid option.
  - Serve only bundles our own pipeline wrote (joblib loading runs code); never accept uploaded model files.
  - Per-user budgets for training spend and for cascade escalations on public predictions.
- [x] [Raj] Durable storage instead of local disk and the repo download. **Records done 2026-10-28** (Supabase: schema in `supabase/migrations/`, registry on Postgres with local files as the fallback, keys survive restarts); files done 2026-10-28 too (Object Storage: version bundles and run folders under `users/<owner>/...`, fetched on first use and loaded only when their SHA-256 matches the hash recorded in Postgres; LRU of loaded models). The live endpoint switches over when it is recreated with the pre-built image (TEAM_PLAN §2.4). Decided 2026-10-28: **Supabase** (Postgres for records: users, specialists, versions, hashed keys, runs; Supabase Auth for login) and **Nebius Object Storage** for files (bundles, run folders, uploaded datasets) under `users/<user_id>/...`. Nebius Managed PostgreSQL was considered (pgvector, but no auth, ~$0.14/h for 2 vCPU / 8 GB) and dropped for now. Fixes keys being lost on endpoint restart and the missing replay runs on the endpoint. Replaces the spec's SQLite: update file 02. Needs from a human: a Supabase project (URL, anon key, service key, JWT secret in `.env`) and a Nebius Object Storage bucket + access key.
- [~] [Havish, moved from Raj 2026-10-29] Data sourcing beyond the pre-downloaded demo datasets (spec file 03 §1.1). **Search and synthetic done 2026-10-29** (`backend/data_sourcing.py`, settings in the `sourcing` section of `config/datasets.yaml`): a request that matches no demo task → Nemotron Ultra drafts a text-classification task card → Hugging Face Hub keyword search + Tavily (huggingface.co only, daily cap) → license tag checked against an allowlist (unknown, other, NC, ND, GPL rejected) → columns and sample rows read through the dataset viewer → Ultra ranks the fits (≥ 0.5) and maps their labels onto the task's → the user picks a dataset or synthetic data in the chat (synthetic is the only option when nothing fits). At build time the license is checked again, rows are read sampled across the split, labels the dataset lacks get synthetic rows in the training set only (5 per label kept aside to score on synthetic data), and an all-synthetic build says in the narration and report card that validation and the sealed test are synthetic too. Still to do: upload of the user's own labeled data.
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
