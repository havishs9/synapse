# 05 Demo tasks, build order and acceptance

## 1. Demo tasks (DECISION D1)

Tasks with different winning strategies prove the agent actually chooses.

| # | Task | Data | Expected winner | What it proves |
|---|---|---|---|---|
| 1 | **Procurement categorization (main walkthrough)** | USAspending contract records: description → PSC rolled up to ~15 to 25 spending categories (file 03, section 1.3) | J + A, or I; cascade to K for ambiguous records | The business wedge; large savings at record volume |
| 2 | **System log anomaly detection (second showcase)** | LogHub HDFS_v1, sessions grouped by block ID (file 03, section 1.4; VERIFY license terms) | E: window features + LightGBM, feature-based reasons | A different task shape gets a different winner; rare-class metrics (recall at 1% FPR); security story. Frame as "system log anomaly detection", not login logs, because HDFS is Hadoop file-system logs |
| 3 | Support ticket routing (optional) | Banking77 (77 intents, CC-BY-4.0) | B, C or I | A third shape, many labels |
| 4 | Prompt-injection detection (STRETCH) | Public prompt-injection dataset (VERIFY license) + Nemotron adversarial examples | H (cascade), metric recall at 1% FPR | Cascade in action |

`make demo-data` downloads and prepares tasks 1 and 2 (and 3/4 if implemented) and records licenses in `config/datasets.yaml`. Both showcase tasks get a recorded replay run.

**Improvement demo:** task 1 uses held-back real labeled records as the user's "corrections" for the v1 → v2 update. Say so in the video.

### Demo video (3 minutes or less, DECISION D7; outline is flexible)

| Time | Beat |
|---|---|
| 0:00 to 0:15 | The problem: paying a frontier model for every repetitive record |
| 0:15 to 0:40 | Procurement: chat → clarifying questions → task card; answers visibly change the plan |
| 0:40 to 1:10 | Training view: live Pareto scatter, rounds narrowing, a repair round (replay sped up) |
| 1:10 to 1:30 | Results + report card (sealed test vs. baseline, honest numbers) |
| 1:30 to 1:55 | **Compare mode** with measured latency, cost and yearly projection at the task card's volume |
| 1:55 to 2:20 | **v1 → v2**: corrections, gate check, deploy, rollback available |
| 2:20 to 2:45 | Logs task (replay): same agent picks a different winner (E), recall at 1% FPR, its own API |
| 2:45 to 3:00 | Built on Nebius and NVIDIA: what runs where |

## 2. Build order (follow strictly)

Today is Tuesday evening, Oct 27. Suggested split: **Person A** owns pipeline, Sandboxes and agents; **Person B** owns UI, compare mode, deployment and the video.

### Phase 0: Verify (Tuesday night, first; record everything in `docs/VERIFICATION.md`)

- [ ] Exact API model IDs for Ultra, Super, Nano, Lightning, Qwen3-Embedding-8B; tool calling + JSON output work with a test call
- [ ] Sandboxes: `whoami` limits; build a base image with scikit-learn + LightGBM; train one model in a sandbox, stream its metrics, time it
- [ ] Prices for every model in `config/models.yaml` and the Serverless CPU preset
- [ ] Serverless: create one CPU endpoint with a hello-world container and token auth; confirm the URL works
- [ ] Object Storage reachable from the endpoint (else use the fallback in file 04)
- [ ] USAspending download path; first 20k to 50k rows; draft `psc_categories.yaml`
- [ ] HDFS download, label files and license terms; Banking77 download (optional task)
- [ ] Public repo with MIT license and README stub

### Phase 1: Hardcoded pipeline, no LLM agents (Tuesday night → Wednesday morning)

- [ ] USAspending → dedupe → stratified sealed split → train J, A, I, E and prompted K in parallel → validation metrics → sealed-test metrics → Nemotron Ultra zero-shot baseline
- [ ] Every agent implemented as a plain function that already reads and writes the exact JSON files in file 02 (Phase 2 becomes a swap, not a rewrite)
- [ ] Training scripts emit JSON-line events; orchestrator writes `events.jsonl`
- [ ] Minimal UI shell following `docs/DESIGN.md`: sidebar, main chat, right pane with the specialist tool panel calling the trained model, live Pareto scatter fed by SSE
- [ ] **Exit criterion:** task 1 runs end to end and produces a real report card

### Phase 2: Agents and evaluation (Wednesday)

- [ ] Planner with structured output plus deterministic fallback
- [ ] Search rounds (10% / 40% / 100%), Trainer error-fix loop, capped repair loop
- [ ] Calibration, cascade (H), frontier + seed reruns
- [ ] Feature-based reasons and teacher-explains-flags
- [ ] Narration feed and report card (per-class metrics, validation vs. sealed, "more data" curve)
- [ ] Task 2 (HDFS logs) through the same pipeline: windowing, template parsing, E features; planner picks a different winner
- [ ] Shared specialist server on the Nebius Serverless endpoint: per-specialist routes and API keys, versioned routes; artifacts in storage
- [ ] Unit test proving sealed-test isolation

### Phase 3: Product and demo (Thursday)

- [ ] Clarifying questions → editable task card, with plan-change lines
- [ ] Compare mode with measured latency, cost and yearly projection
- [ ] "Use via API": each specialist's URL, reveal-once API key with regenerate, curl and Python snippets
- [ ] v1 → v2 improvement flow: corrections, version gate, deploy or reject, rollback, version history
- [ ] Agent lanes, tournament bracket, budget meter
- [ ] UI polish pass against file 01 section 2.11 (layout, specialist colors, light/dark, mobile), with screenshots
- [ ] Replay mode with recorded runs for both showcase tasks committed to the repo
- [ ] Public demo URL
- [ ] Complete README and `docs/FEEDBACK.md`
- [ ] Record the 3-minute video

### Friday by 11:00 AM ET: submit (hard deadline 1:00 PM ET)

- [ ] Devpost: track Coding and Agentic Engineering, description, demo URL, repo, video, tool feedback

## 3. Cut order if behind (cut from the top first)

1. G (LoRA tier)
2. Task 4 (prompt injection)
3. Task 3 (Banking77)
4. Multiple specialist tabs
5. Lineage tree
6. Agent lanes, tournament bracket and budget meter
7. Rung L (Super)
8. Repair loop beyond 1 round
9. Live Tavily dataset search (use the vetted registry)
10. Logs task live in the video (keep it as a replay segment only)

**Never cut:** sealed test set, Nemotron Ultra baseline, compare mode, parallel candidate training (Sandboxes or local fallback), honest real-vs-synthetic reporting, replay mode, live Pareto scatter, per-specialist versioned API, the validated v1 → v2 update, both showcase tasks (procurement and logs) running through the pipeline, and light/dark mode.

## 4. Testing requirements

- Unit tests for: log windowing, feature engineering, PSC → category mapping, each candidate's train/predict interface, metric calculations (including per-class and recall@FPR), calibration, cascade routing, cost calculation, schema validation, planner deterministic fallback, the budget guard, the cache, and the version gate (v2 rejected when it doesn't beat v1 or breaks a per-class floor).
- A test proving the Data agent and Trainer cannot read the sealed test directory.
- A test proving rebalancing applies to train only (val/test class ratios unchanged).
- A test proving a specialist's API key works only on its own routes (another specialist's key gets 403; revoked keys fail).
- An integration test running the full pipeline on a tiny fixture dataset (a few hundred rows) in under 2 minutes with LLM calls mocked.
- Frontend smoke test: sidebar, main chat, training view, specialist panel, compare mode and version history render with replay data, in light and dark mode, at desktop and mobile widths.

## 5. Acceptance criteria (done when all are true)

- [ ] A user can describe the procurement task in chat, answer clarifying questions, confirm the task card, and watch a real run complete in the training view with the live Pareto scatter.
- [ ] The specialist panel opens side by side and returns label, confidence and reason for a pasted record.
- [ ] Compare mode shows both models' outputs with measured latency, cost and the yearly projection.
- [ ] The report card shows sealed-test metrics against true labels (overall and per class), validation vs. sealed, the Nemotron baseline, teacher agreement (separately labeled), seed error bars and a Pareto chart.
- [ ] The HDFS logs task runs through the same pipeline (windowed sessions) and the planner picks a different winning strategy than for procurement.
- [ ] A v1 → v2 update runs through the version gate; a passing v2 deploys, a failing v2 is rejected with a reason, and rollback works.
- [ ] Each specialist is reachable at its own documented, versioned API route with its own API key; another specialist's key is rejected (Nebius Serverless, or the documented fallback).
- [ ] Replay mode reproduces full recorded runs for both showcase tasks reliably.
- [ ] The public demo URL works.
- [ ] The UI matches file 01 section 2.11: familiar chat layout, three specialist actions only, one overlay at a time, per-specialist colors, light and dark mode, responsive down to mobile.
- [ ] Repo is public, MIT licensed, README complete, `docs/VERIFICATION.md` and `docs/FEEDBACK.md` filled in.
- [ ] All tests pass.

## 6. README requirements

1. Project name, one-liner, and a GIF or screenshot of compare mode at the top.
2. The problem and who it's for (teams paying frontier-model prices for repetitive classification work).
3. How it works: architecture diagram (Mermaid), the four agents, the candidate ladder, the sealed test set guarantee, the version gate.
4. **Built on Nebius and NVIDIA** table: component → Nebius/NVIDIA service → what it does. Include every Nemotron role (planner, teacher, judge, error analyst, baseline, prompted rungs, cascade fallback), Token Factory structured output/function calling, Qwen3-Embedding-8B, Sandboxes, the Serverless endpoint and storage, and Tavily.
5. Where Token Factory accelerated the workflow (concrete examples).
6. Real measured results: tables for each demo task (sealed-test metrics, Nemotron baseline, latency, cost, projected yearly cost).
7. Honest limitations (Nemotron not fine-tunable on Token Factory, synthetic data caveats, format-mismatch risk, anything that fell back from Nebius).
8. Setup from clone to running in under 10 commands; environment variables; `make demo-data`, `make dev`, `make replay`.
9. Datasets with links and licenses.
10. MIT license notice.

## 7. Things you must not do

- Do not use a chat UI for the specialist panel.
- Do not classify single log lines.
- Do not headline plain accuracy on imbalanced data.
- Do not call teacher agreement "accuracy".
- Do not let any agent except the Evaluator read the sealed test set.
- Do not rebalance validation or test sets.
- Do not deploy a new version unless it passes the version gate.
- Do not hardcode model IDs, prices or secrets.
- Do not invent numbers for the UI, README or video; every number comes from a run file.
- Do not claim Nemotron was fine-tuned.
- Do not claim "on-device" or "offline" for any path that calls a cloud API (B, cloud I, K, L, cascade to Nemotron, teacher-explains-flags).
- Do not use Dedicated-only models or endpoints without explicit opt-in.
- Do not use Corvo or any customer data.
- Do not add agent frameworks.
- Do not let agents message each other directly; all coordination goes through the orchestrator and JSON files.
