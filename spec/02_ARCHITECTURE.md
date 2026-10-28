# 02 Architecture

## 1. Tech stack

- **Backend:** Python 3.11+, FastAPI, Pydantic v2 for every schema, server-sent events (SSE) to stream progress to the UI.
- **ML:** scikit-learn, LightGBM, numpy, pandas, sentence-transformers (local MiniLM-class embedding candidate C), joblib for model files.
- **LLM access:** OpenAI Python SDK pointed at Token Factory. One shared client module with retries, timeouts, response caching and cost tracking.
- **Sandboxes:** `contree-sdk` (CONFIRMED package name, quickstart pins 0.3.6; `from contree_sdk import Contree`). Optional CLI: `contree-cli`.
- **Search:** Tavily Python SDK; Hugging Face Hub search for datasets.
- **Frontend:** React + Vite + TypeScript + Tailwind. Recharts for charts (the live Pareto scatter is a Recharts ScatterChart fed by SSE).
- **Storage:** per-run directories on disk (`runs/<run_id>/`) holding every JSON handoff file and model artifact. SQLite only for the list of runs, specialists and versions. Deployed model versions also go to Nebius Object Storage (VERIFY, file 04).
- **No agent frameworks** (no LangChain, LangGraph, CrewAI, AutoGen). The orchestrator is plain Python.
- **Packaging:** Dockerfile for the backend, Dockerfile for the shared specialist server, `docker-compose.yml` for local dev, Makefile with `make setup`, `make dev`, `make test`, `make demo-data`, `make replay`.

## 2. Environment variables (`.env.example`)

~~~
NEBIUS_API_KEY=
NEBIUS_PROJECT_ID=                 # required by the Sandboxes SDK (CONFIRMED)
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1/
SANDBOX_BASE_URL=https://api.tokenfactory.nebius.com/sandboxes
TAVILY_API_KEY=
HF_TOKEN=                          # Hugging Face read token for dataset downloads
SPECIALIST_ENDPOINT_URL=           # managed HTTPS URL of the Nebius Serverless endpoint
SPECIALIST_ADMIN_TOKEN=            # backend to specialist server admin routes (load version, set live, create keys)
API_KEY_PEPPER=                    # secret mixed into hashed per-specialist API keys
OBJECT_STORAGE_ENDPOINT=           # VERIFY (file 04)
OBJECT_STORAGE_BUCKET=
OBJECT_STORAGE_ACCESS_KEY=
OBJECT_STORAGE_SECRET_KEY=
APP_MODE=live                      # live | replay
TRAINING_BACKEND=sandbox           # sandbox | local
CREDIT_BUDGET_USD=5                # hard stop for LLM spend per run (total credit is ~$25)
MAX_REPAIR_ROUNDS=3
DEMO_MONTHLY_VOLUME=1000000        # default volume for cost projections
DATA_DIR=./data
RUNS_DIR=./runs
~~~

## 3. Orchestrator plus four role agents

Agents never talk to each other directly. A plain-Python orchestrator runs the stages in a fixed order. Each agent has exactly one job, its own tools, and strict Pydantic-validated JSON input and output files. Every handoff is a file in `runs/<run_id>/` that can be inspected.

| Agent | Job | Model | Tools | Reads | Writes |
|---|---|---|---|---|---|
| Orchestrator (plain Python, not an LLM) | Runs stages in order, enforces budgets and the repair cap, streams SSE events | none | all agents | everything | `run_state.json`, `events.jsonl` |
| Data agent | Find datasets, check licenses, window logs, label with reasons, generate synthetic examples, generate targeted examples during repair, ingest user corrections | Nemotron Nano (or Lightning) for bulk labeling; Nemotron Ultra for synthetic generation | Tavily, HF Hub, dataset download, Token Factory | `task_card.json`, `error_patterns.json`, `corrections.json` | `dataset_manifest.json`, `dataset_stats.json`, `train.*`, `val.*` |
| Planner agent | Pick candidate families from the ladder (A to L, plus H) and their search ranges from task properties | Nemotron Ultra, structured output | Token Factory structured output | `task_card.json`, `dataset_stats.json` | `candidate_plan.json` |
| Trainer agent | Launch candidate training in parallel, run the search rounds, fix and resubmit failed runs | Mostly code; a small Nemotron only reads errors and patches configs/scripts | Training sandbox (file 03) | `candidate_plan.json`, train/val files | `runs.json`, model files, per-candidate `metrics.json` |
| Evaluator agent | Compute metrics in code, calibrate confidence, run the Nemotron baseline, find error patterns, decide pass or repair, run each version's final exam and the version gate | Code for metrics; Nemotron Ultra for error analysis | **Sealed test set (only this agent can read it)**, Token Factory | model files, validation predictions | `eval_report.json`, `error_patterns.json`, `versions.json` |

Rules:

1. The sealed test split lives in a directory only the Evaluator's code path can read. Enforce in code (the Data and Trainer modules receive paths to train/val only). A unit test proves the Trainer and Data agent cannot access it.
2. The model that trains is never the model that grades.
3. Each role uses the cheapest model tier that works.
4. Data agent and Planner may overlap: the Planner drafts a plan from the task card, then finalizes it once `dataset_stats.json` exists.
5. Trainer branches run in parallel. Everything else is sequential.
6. Every LLM call goes through the shared client, which logs model, tokens, latency and dollar cost to `runs/<run_id>/llm_calls.jsonl`.

## 4. Pipeline stages (in order)

1. **Intake:** clarifying questions → confirmed `task_card.json`.
2. **Data:** gather data in priority order (file 03), window logs if needed, label, dedupe, split → `dataset_manifest.json`, `dataset_stats.json`, train/val/test files.
3. **Plan:** `candidate_plan.json`.
4. **Train + search:** rounds by data fraction (DECISION D4, file 03) → `runs.json`.
5. **Validate:** Evaluator scores the top candidates on validation, calibrates confidence, builds the frontier, writes `error_patterns.json`.
6. **Repair loop** (capped at `MAX_REPAIR_ROUNDS`, default 3): error patterns → Data agent → targeted examples added to the training set only → Trainer retrains only the top 2 configs → Evaluator re-checks on validation. Stop when the target is met or the cap is reached. Repair never touches the sealed test set.
7. **Final exam:** Evaluator scores the chosen model on the sealed test set exactly once, plus the Nemotron zero-shot baseline on the same set. Seed reruns for the final 2.
8. **Deploy:** upload the version's artifacts; the shared specialist server serves it at the specialist's own routes; on first deploy, create the specialist's API key (file 04).
9. **Deliver:** report card, specialist panel, API URL + key + snippets.
10. **Improve (on demand):** user corrections → stages 2 (append to train only), 4 (winner + runner-up only), 7 (one final exam for the new version) → version gate → deploy or reject (file 03).

## 5. JSON schemas (Pydantic models in `backend/schemas/`)

### 5.1 `task_card.json`

- `task_id`, `task_name`, `description`
- `input_type`: `text | log_window | tabular | text_pair`
- `output_type`: `binary | multiclass | multilabel | spans | structured_json | number`
- `labels`: list of `{name, definition}`
- `positive_definition` (binary tasks)
- `error_preference`: `recall_first | precision_first | balanced`
- `per_class_error_costs` (optional map, multiclass)
- `optimization_metric`: e.g. `recall_at_fpr`, `macro_f1`, `pr_auc`
- `fpr_target` (if applicable, e.g. 0.01)
- `thresholds`: minimum acceptable values for the primary metric and any per-class floors
- `needs_reason`: bool
- `monthly_volume`: int
- `latency_budget_ms`
- `deployment`: `offline | cloud_ok`
- `build_budget_usd`, `build_budget_minutes`
- `sample_inputs`: the user's pasted format samples
- `window_spec` (logs only): `group_by` (session id / user / block id), `window_minutes`

### 5.2 `dataset_manifest.json`

- sources: name, URL, license, `license_ok`, rows used, `is_synthetic`
- label mapping used (e.g. PSC prefix → category), with its source
- format-match score between source data and the user's sample inputs, with explanation
- split sizes and class ratios for train / val / test

### 5.3 `dataset_stats.json`

Row counts, label counts, class imbalance ratio, smallest class size, average input length, vocabulary/keyword density estimate, whether the data is structured.

### 5.4 `candidate_plan.json`

- candidates: `id` (A to L or H), `rung`, hyperparameter search ranges, training-strategy variants (real labels only / real + teacher labels / + synthetic), reason for inclusion
- reasons for excluded candidate types
- planner's plain-English summary (shown in the narration feed)
- `planner_source`: `llm | deterministic_fallback`

### 5.5 `runs.json`

Per candidate config: config, seed, status (`queued | running | done | failed | timeout | eliminated`), round reached, data fraction, error log path if failed, fix attempts, `metrics.json` path, elimination reason.

### 5.6 Per-candidate `metrics.json`

Primary metric, macro precision/recall/F1, per-class precision and recall, PR-AUC, recall@FPR (when applicable), calibration error (after calibration), p50/p99 latency, throughput (items/s), model size MB, estimated $/1M predictions with formula inputs.

### 5.7 `eval_report.json`

Validation metrics per round, frontier (recommended + alternatives), calibration method, cascade band and escalation rate, final sealed-test metrics, seed mean ± std for the final 2, validation vs. sealed comparison, teacher agreement, Nemotron baseline metrics, real vs. synthetic scores, "more data" curve points, pass/repair decision with reason.

### 5.8 `error_patterns.json`

List of `{pattern, count, example_ids, suggested_data_fix}`.

### 5.9 `versions.json`

Per specialist: `specialist_id`, display name, API route, hashed API key(s) with created/revoked timestamps (never store the plain key), and a list of versions with `version`, `run_id`, sealed-test metrics, gate result (`deployed | rejected | rolled_back`), reason, artifact URI, timestamps. Exactly one version is `live`.

### 5.10 `corrections.json`

User corrections from the specialist panel: input, predicted label, corrected label, timestamp.

### 5.11 `run_state.json`

Current stage, repair round, LLM spend so far, budget remaining, timestamps, final status.

### 5.12 Event stream

Training scripts print one JSON line per step to stdout, for example:

~~~json
{"cand": "A-03", "round": 2, "data_frac": 0.4, "step": 40, "val_macro_f1": 0.88, "ms_per_item": 0.2}
~~~

Sandboxes stream stdout over SSE; the local launcher reads stdout directly. The orchestrator wraps these into `events.jsonl` entries (`{ts, agent, stage, message, data_ref, spend_usd}`) and forwards them to the UI over SSE. Replay mode plays back the same `events.jsonl`.

## 6. Reliability, budget and replay mode

- **Response cache:** every LLM call is cached on disk by (model, prompt hash, parameters). Re-running a stage reuses cached responses.
- **Budget guard:** the orchestrator stops the run with a clear message if LLM spend reaches `CREDIT_BUDGET_USD` or the task card's build budget, whichever is lower. Spend is shown live.
- **Model tiering:** Nemotron Ultra only for planning, clarifying questions, synthetic generation, error analysis and the baseline. Nano/Lightning for bulk labeling. LLM ladder rungs (K, L) are evaluated on a capped validation sample during search to save credits.
- **Replay mode** (`APP_MODE=replay`): the UI plays back a recorded run (`events.jsonl` with original timings, optionally sped up) and the specialist panel uses the saved model. Compare mode in replay still calls the live specialist and, if reachable, live Nemotron; if Nemotron is unreachable it shows cached responses labeled "cached". `make replay RUN=<run_id>` starts it.
- Retries with exponential backoff on all network calls; clear user-facing errors, never silent failures.

## 7. Repository structure

~~~
synapse/
├── LICENSE                      # MIT
├── README.md
├── CLAUDE.md
├── TEAM_INPUTS.md
├── .env.example
├── Makefile
├── docker-compose.yml
├── spec/                        # these six spec files
├── config/
│   ├── models.yaml              # verified model IDs per role
│   ├── pricing.yaml             # verified per-token / hosting prices
│   ├── datasets.yaml            # vetted dataset registry with licenses
│   └── psc_categories.yaml      # PSC prefix → spending category map (demo task 1)
├── backend/
│   ├── main.py                  # FastAPI app, SSE endpoint
│   ├── orchestrator.py
│   ├── llm_client.py            # Token Factory client, cache, cost tracking
│   ├── schemas/                 # all Pydantic models
│   ├── agents/
│   │   ├── data_agent.py
│   │   ├── planner_agent.py
│   │   ├── trainer_agent.py
│   │   └── evaluator_agent.py
│   ├── candidates/              # one module per candidate type A–L and H
│   ├── features/                # log windowing + feature engineering
│   ├── sandbox/                 # Sandboxes launcher + local fallback launcher
│   ├── serving/                 # shared specialist server, per-specialist API keys, Dockerfile
│   ├── versions/                # version registry, gate, rollback
│   └── tests/
├── frontend/
│   └── src/
│       ├── components/          # Sidebar, MainChat, TaskCard, NarrationFeed, ParetoLive, AgentLanes,
│       │                        # Bracket, BudgetMeter, SpecialistPanel, CompareMode,
│       │                        # ReportCard, VersionHistory, UseDialog, QuickSwitcher
│       ├── styles/tokens.css    # color, type, spacing variables for light and dark
│       └── ...
├── data/                        # gitignored except small fixtures
├── runs/                        # gitignored except one recorded demo run per showcase task
└── docs/
    ├── VERIFICATION.md          # result of every VERIFY item
    ├── DESIGN.md                # UI design plan (file 01, section 2.11)
    ├── ARCHITECTURE.md          # diagram + agent handoffs
    └── FEEDBACK.md              # detailed feedback on Token Factory, AI Cloud, NVIDIA models
~~~
