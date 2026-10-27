# Build Prompt: Synapse (Nebius x NVIDIA Global AI Hackathon)

You are building a complete, working hackathon project from scratch. Read this entire document before writing any code. Every section is a requirement unless it is explicitly marked **STRETCH**. When something is marked **VERIFY**, do not assume it works: check the official docs or test it, and if it fails, use the stated fallback and record what happened in `docs/VERIFICATION.md`.

Work in the build order in Section 17. Do not start a later phase until the earlier phase works end to end.

---

## 1. What we are building

**Synapse** is a web app where a user chats with a large NVIDIA Nemotron model, describes a repetitive task in plain English (for example, "flag suspicious behavior in our server logs"), and the system automatically builds, tests, and deploys a small specialist model for that one task. The specialist is far cheaper and faster than calling the large model, and the system measures and reports the exact accuracy, latency, and cost tradeoff honestly.

Analogy for the UI copy: a senior doctor (the big model) trains a nurse (the specialist) to run one screening test. The nurse is faster and cheaper, and nearly as good on that one test.

**One-liner for judges:** Describe a task in plain English, get a specialist that is dramatically cheaper and faster than calling the LLM, with a measured accuracy tradeoff. (Use the real measured numbers in all copy, never placeholder multipliers.)

**Hackathon track:** Coding and Agentic Engineering (the agent writes training code, runs it, and tests the result).

---

## 2. Hard constraints (non-negotiable)

1. The project must run on **Nebius Token Factory and/or Nebius AI Cloud**.
2. It must use at least one **NVIDIA open source model** (Nemotron). Nemotron must be load-bearing, not decorative.
3. The repository must be **public** with an **MIT license** file at the repo root, visible on the repo page.
4. The repo must include a **README** with setup instructions, run instructions, and a "Built on Nebius and NVIDIA" section explaining exactly where Nemotron, Token Factory, and any other Nebius services and Tavily are used.
5. There must be a **publicly accessible working demo URL**.
6. The app must support a **demo video of 3 minutes or less**. Build a replay mode (Section 13) so recording is reliable.
7. Never commit secrets. All keys come from environment variables. Provide `.env.example`.
8. Never hardcode model IDs, prices, or endpoint URLs in code. Put them in `config/models.yaml` and `config/pricing.yaml`. **VERIFY** the real model IDs from Token Factory's model list before filling them in.
9. Token Factory exposes an OpenAI-compatible API (base URL `https://api.tokenfactory.nebius.com/v1/`, **VERIFY**). Use the OpenAI Python SDK with that base URL.
10. Nemotron **cannot** be fine-tuned on Token Factory (the fine-tunable list is DeepSeek, Gemma 4, gpt-oss, Qwen, Llama). Nemotron is used as the planner, teacher, judge, error analyst, baseline, and cascade fallback. Do not build anything that assumes Nemotron fine-tuning.

---

## 3. Tech stack

- **Backend:** Python 3.11+, FastAPI, Pydantic v2 for every schema, server-sent events (SSE) to stream progress to the UI.
- **ML:** scikit-learn, LightGBM, numpy, pandas, sentence-transformers (for the local MiniLM-class embedding candidate), joblib for model files.
- **LLM access:** OpenAI Python SDK pointed at Token Factory. One shared client module with retries, timeouts, response caching, and cost tracking.
- **Search:** Tavily Python SDK.
- **Frontend:** React + Vite + TypeScript + Tailwind. Recharts for charts.
- **Storage:** Per-run directories on disk (`runs/<run_id>/`) containing every JSON handoff file and model artifact. SQLite only for the list of runs and specialists.
- **No agent frameworks** (no LangChain, CrewAI, AutoGen). The orchestrator is plain Python.
- **Packaging:** Dockerfile for the backend, Dockerfile for the specialist serving image, `docker-compose.yml` for local dev, `Makefile` with `make setup`, `make dev`, `make test`, `make demo-data`, `make replay`.

---

## 4. Environment variables (`.env.example`)

```
NEBIUS_API_KEY=
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1/
TAVILY_API_KEY=
HF_TOKEN=
APP_MODE=live            # live | replay
CREDIT_BUDGET_USD=20     # hard stop for LLM spend per run
MAX_REPAIR_ROUNDS=3
DATA_DIR=./data
RUNS_DIR=./runs
```

---

## 5. User-facing features

### 5.1 Main chat
- A chat window with the main model (Nemotron, the largest available tier per `config/models.yaml`).
- The user can type a task description and optionally attach a file (CSV, JSONL, or plain-text logs) of labeled or unlabeled examples.
- File attachment is optional. If no labeled data is attached, the system must still ask the user to paste **10 to 20 sample lines of their real data** (labels not required) so the system knows the real input format. Explain why in the UI: models learn the shape of the data they are trained on.
- The main chat also works as a normal chat for questions that are not "build a specialist" requests.

### 5.2 Clarifying questions → task card
- Before building, the main model asks a short set of clarifying questions (maximum 5, one message):
  1. What counts as a positive/target case (e.g. what is "suspicious")?
  2. Which error is worse: missing a real case or raising a false alarm? (maps to the optimization metric)
  3. Verdict only, or verdict plus a reason?
  4. Latency budget (e.g. under 50 ms per item)?
  5. Must it run fully offline, or are cloud API calls allowed at inference time?
- The answers are converted into a **task card** (schema in Section 8.1) shown to the user as an editable summary card with a "Build specialist" button. The build starts only after the user confirms.

### 5.3 Live progress panel
- Replaces any loading spinner. Streams real events from the backend via SSE.
- Shows **one lane per agent** (Data, Planner, Trainer, Evaluator) with handoff arrows between lanes when a JSON file passes from one to another.
- Each event has a short plain-English line, for example:
  - "Data: found your 2,000 labeled rows"
  - "Data: only 3% are anomalies, rebalancing the training set"
  - "Planner: trying candidates E and A, because the data is structured logs"
  - "Trainer: 32 candidates training → 8 survive → 2 survive"
  - "Evaluator: recall 0.91 at 1% false-positive rate on validation"
  - "Repair round 1: missing slow brute-force patterns, adding 400 targeted examples"
  - "Evaluator: final score on sealed test set"
  - "Deployed"
- Every event shows elapsed time and running LLM spend in dollars.
- Clicking an event expands it to show the underlying JSON file.

### 5.4 Specialist chat
When a specialist is ready, it opens as its own chat, side by side with the main chat (or as a tab on narrow screens), titled e.g. "Log Anomaly Detector v1". It looks and feels like a normal chat thread, so the user can keep asking it to do tasks. Under the hood, a small classifier cannot converse, so every message goes through a **message router** first.

**Message router (`backend/specialist_chat/router.py`):** classifies each incoming message as one of:
1. **Input to score.** Text or log lines that match the specialist's input format (checked deterministically against the task card's `sample_inputs` and `window_spec`). → Sent straight to the specialist.
2. **File to score.** An uploaded CSV / JSONL / log file. → Batch scoring.
3. **Task or question about results.** e.g. "why did you flag this?", "score only the last hour", "show me the 10 most suspicious", "how sure are you?", "make it stricter". → Handled by the **helper** (below).
4. **Out of scope.** e.g. "write me a poem". → A short, clear reply saying what this specialist does, with a one-click link back to the main chat.

Routing order: deterministic format check first; only if ambiguous, a call to the smallest Nemotron tier with structured output to classify intent. If `deployment: offline`, the LLM router is disabled and the chat accepts only inputs, files, and slash commands.

**Helper (cloud only, smallest Nemotron tier):** handles category 3. It never makes the verdict; the specialist always decides. The helper can only:
- Explain a verdict, using the specialist's own feature-based reason, confidence, and the input. It must not invent reasons the specialist didn't produce.
- Run tools on the specialist: `score(items)`, `score_file(file_id)`, `filter_results(query)`, `top_k(n)`, `set_threshold(value)` (preview first, apply only after the user confirms), `get_report_card()`.
- Summarize batch results ("142 of 10,000 windows flagged; most share pattern X").

**Rendering:**
- Each scored item renders as a compact **result card**: verdict, confidence bar, reason, and a small "Why?" button (which sends a helper request).
- Batch results render as a results table inside the chat with sort, filter, and "Download CSV".
- Every assistant message shows a small, quiet source badge: **Specialist** (free/cheap, local) or **Helper · Nemotron** (cloud call, cost shown on hover). This keeps the cost story honest: users can see which answers came from the cheap model.
- Slash commands work in all modes: `/score`, `/file`, `/top 10`, `/threshold 0.7`, `/report`, `/compare`, `/api`, `/download`.
- If the input doesn't match the expected format and no route fits, show a clear message stating the expected format with an example from `sample_inputs`, never a meaningless prediction.
- The chat history for each specialist is saved and reloads when the user returns to it.

### 5.5 Compare mode
- A toggle in the specialist panel sends the same input to both the main model (Nemotron zero-shot, using the same task card prompt as the baseline) and the specialist at the same time.
- Shows side by side: both verdicts, both reasons, and the **measured** latency and **measured/calculated** cost of each call.
- Includes a projection line: "At 1M items/day: Nemotron $X/year vs. specialist $Y/year", computed from measured numbers and `config/pricing.yaml`. The calculation method must be shown on hover.
- This is the centerpiece of the demo video. It must be fast, stable, and visually clear.

### 5.6 Report card
Shown in the specialist panel and downloadable as JSON and Markdown:
- Winning strategy and why the planner chose it.
- Metrics on the **sealed test set** against **true labels** (Section 11).
- Agreement rate with the Nemotron teacher (reported separately from accuracy, clearly labeled).
- Nemotron zero-shot baseline metrics on the same sealed set.
- If training used synthetic data: score on real data and score on synthetic data, both reported.
- Latency p50 and p99, model size on disk, cost per 1M predictions.
- Known weaknesses (top error patterns from the Evaluator).
- Data sources used, with licenses.
- A **Pareto chart**: accuracy metric vs. latency vs. cost for all surviving candidates plus the Nemotron baseline.

### 5.7 Use it: API access and model download
Each specialist has a **Use** button in its header that opens a single panel with two tabs: **API** and **Download**.

**API tab:**
- Generate, copy, and revoke **API keys per specialist** (store only a hash server-side; show the full key once at creation).
- Endpoints for each specialist:
  - `POST /v1/specialists/{id}/predict`: one input → `{verdict, confidence, reason, model_version, latency_ms}`
  - `POST /v1/specialists/{id}/predict_batch`: up to 1,000 inputs per request
  - `GET /v1/specialists/{id}`: metadata, input format, labels, threshold, report card summary
  - `GET /health`
- Auth via `Authorization: Bearer <key>`. Simple per-key rate limit (configurable, default 100 requests/second) with a clear 429 response.
- Copy-paste snippets in **curl, Python, and JavaScript**, pre-filled with the specialist's real ID and a real example input from `sample_inputs`.
- An inline **"Try it"** box: send a request from the browser and see the raw JSON response and latency.
- Auto-generated OpenAPI docs for the specialist API (FastAPI's `/docs`), linked from the tab.
- Usage counter per key: requests today, average latency.

**Download tab:**
- One-click **zip download** containing:
  - `model.joblib` (or the native format for the candidate type)
  - `threshold.json` and `feature_config.json` (windowing + feature engineering settings)
  - `predict.py`: a standalone script that loads the model and scores a file, with no dependency on this app
  - `server.py` + `Dockerfile`: run the specialist as your own API with one command
  - `requirements.txt` with pinned versions
  - `README.md`: how to run it, the input format with examples, and the expected output
  - `report_card.md` and `report_card.json`
  - `LICENSE_NOTES.md`: licenses of every dataset used to train it
- **STRETCH:** ONNX export for candidates where conversion is reliable (linear models, LightGBM), so the model runs without Python.
- A plain-language note when the specialist depends on a cloud call at inference time (candidate B embeddings, or cascade H fallback): "This model calls Nebius Token Factory for embeddings; it won't work fully offline."
- Unit test: unzip the download into a clean virtualenv, run `predict.py` on fixture data, and check the outputs match the hosted endpoint exactly.

### 5.8 Multiple specialists
- Every specialist the user builds is listed in the sidebar and reopens with its chat history.
- Opening several at once as tabs is STRETCH.

### 5.9 UI design and navigation
The interface should feel as familiar as popular LLM chat apps (one conversation column, a sidebar, a composer at the bottom) but calmer and less cluttered. A first-time user must be able to build and use a specialist without reading any instructions.

**Layout:**
```
┌────────────┬──────────────────────────────┬──────────────────────────┐
│ Sidebar    │ Main chat (Nemotron)         │ Specialist chat          │
│            │                              │ (opens when ready)       │
│ + New chat │  conversation column,        │ ● Log Anomaly Detector v1│
│            │  max ~720px wide, centered   │ [Compare] [Report] [Use] │
│ Chats      │                              │                          │
│  …         │  build progress appears as   │  result cards,           │
│ Specialists│  one expandable message      │  tables, replies         │
│  ● Logs v1 │                              │                          │
│  ● Tickets │ ┌──────────────────────────┐ │ ┌──────────────────────┐ │
│            │ │ 📎  Message…          ⏎ │ │ │ 📎  Paste logs…    ⏎ │ │
└────────────┴─┴──────────────────────────┴─┴─┴──────────────────────┴─┘
```
- **Left sidebar** (collapsible): "New chat" at the top, then recent chats, then a "Specialists" list. Nothing else.
- **Main chat:** centered conversation column, composer pinned to the bottom with an attach button.
- **Specialist chat:** opens in a split pane on the right when the build finishes. The divider is draggable. A close button collapses it back to the sidebar entry.
- **Specialist header** has exactly three actions: **Compare**, **Report**, **Use**. Everything else lives behind these or in slash commands.
- **Build progress** is shown inside the main chat as a single message that expands into the agent lanes (Section 5.3), not as a separate dashboard. Collapsed, it shows one line: the current stage and elapsed time.
- **Report** opens as a right-side drawer over the specialist chat. **Use** opens as a centered dialog with the API and Download tabs. Never more than one overlay open at a time.
- **Task card** appears inline in the main chat as an editable message with one primary button: "Build specialist".

**Visual identity (one memorable element, everything else quiet):**
- The memorable element: **every specialist gets its own color and a two-letter monogram**, generated at build time from a curated palette of 8 accessible hues. That color appears only in its sidebar dot, its pane header, and its result cards' verdict marker. The main model stays neutral (no accent color). Users learn "the teal one is my log detector" at a glance.
- Neutrals: cool off-white background in light mode (e.g. `#F6F7F9`), true dark grey in dark mode (e.g. `#1C1D21`, not tinted near-black), text ink `#16181D` / `#E8E9EC`. Define all colors as CSS variables with light and dark values.
- Typography: **IBM Plex Sans** for the interface, **IBM Plex Mono only for log lines, code, and API snippets** (where monospace carries meaning). One type scale, sentence case everywhere, no all-caps labels.
- Avoid the generic defaults: no gradient washes, no identical shadowed cards for every element, no decorative eyebrows above headings, no arrows appended to button text.
- Shape: subtle radius on inputs and message bubbles; result cards and tables use thin borders, not shadows.

**Motion:** one deliberate moment. When a build finishes, the specialist "graduates": its monogram moves from the build message into the new split pane as it slides open. Everything else uses only quick, functional transitions (expand, open, close). Respect `prefers-reduced-motion`.

**Chat quality bar (match popular LLM chat apps):**
- Streaming responses token by token, with a stop button.
- Markdown rendering, syntax-highlighted code blocks with copy buttons.
- Drag-and-drop file upload onto either chat, with a file chip showing name and row count.
- Message actions on hover: copy, retry (main chat only).
- Empty state for the main chat: one sentence explaining what the app does, plus three example prompts as clickable chips (e.g. "Build a model that flags suspicious server logs", "Route support tickets to the right team", "Detect prompt-injection attempts").
- Empty state for a specialist chat: its expected input format with a "Try an example" button that inserts a real sample.

**Navigation and accessibility:**
- Keyboard: `Cmd/Ctrl+K` quick switcher (chats and specialists), `Cmd/Ctrl+Enter` to send, `Esc` closes overlays, visible focus states everywhere.
- Light and dark mode following the system setting, with a manual toggle in the sidebar footer.
- Responsive: on screens under 1024px, the split view becomes two tabs ("Main" / specialist name); under 768px, the sidebar becomes a drawer.
- All text and controls meet WCAG AA contrast.

**Copy rules:** plain, active language named after what users do: "Build specialist", "Compare", "Report", "Use", "Download model", "Copy API key". Errors say what went wrong and how to fix it ("This doesn't look like a log window. Expected lines like: …"). No jargon in the main UI; technical detail (agent names, JSON files, candidate IDs) appears only inside expanded build progress and the report drawer.

**Implementation:** React + Vite + TypeScript + Tailwind, with shadcn/ui (Radix) primitives for dialogs, drawers, tabs, and tooltips. Before writing frontend code, write a short design plan in `docs/DESIGN.md` (color tokens, type scale, layout, the one memorable element) and follow it. Take screenshots of each main screen in both themes and review them against this section before Phase 3 is marked done.

---

## 6. Architecture: orchestrator plus four role agents

Agents never talk to each other directly. A plain-Python **orchestrator** runs the stages in a fixed order. Each agent has exactly one job, its own tools, and strict Pydantic-validated JSON input and output files. Every handoff is a file in `runs/<run_id>/` that can be inspected.

| Agent | Job | Model | Tools | Reads | Writes |
|---|---|---|---|---|---|
| **Orchestrator** (plain Python, not an LLM) | Runs stages in order, enforces budgets and the repair cap, streams SSE events | none | all agents | everything | `run_state.json`, `events.jsonl` |
| **Data agent** | Find datasets, check licenses, window logs, label with reasons, generate synthetic examples, generate targeted examples during repair | Smaller Nemotron (Super/Nano) for bulk labeling; largest Nemotron for synthetic generation | Tavily, dataset download, Token Factory | `task_card.json`, `error_patterns.json` | `dataset_manifest.json`, `train.*`, `val.*` |
| **Planner agent** | Pick candidate types A–H and their search ranges from task properties | Largest Nemotron, structured output | Token Factory structured output | `task_card.json`, `dataset_stats.json` | `candidate_plan.json` |
| **Trainer agent** | Launch candidate training in parallel, run successive halving, fix and resubmit failed runs | Mostly code; a small LLM only reads errors and patches scripts | Training sandbox (Section 10) | `candidate_plan.json`, train/val files | `runs.json`, model files, per-candidate `metrics.json` |
| **Evaluator agent** | Compute metrics in code, run the Nemotron baseline, find error patterns, decide pass or repair | Code for metrics; largest Nemotron for error analysis | Sealed test set (**only this agent can read it**), Token Factory | model files, validation predictions | `eval_report.json`, `error_patterns.json` |

**Rules:**
1. The sealed test split is stored in a directory that only the Evaluator's code path can read. Enforce this in code (e.g. the Data and Trainer modules receive paths only to train/val). Add a unit test proving the Trainer and Data agent cannot access it.
2. The model that trains is never the model that grades.
3. Each role uses the cheapest model tier that works.
4. Data agent and Planner may overlap: the Planner drafts a plan from the task card, then finalizes it once `dataset_stats.json` exists.
5. Trainer branches run in parallel. Everything else is sequential.
6. Every LLM call goes through the shared client, which logs model, tokens, latency, and dollar cost to `runs/<run_id>/llm_calls.jsonl`.

---

## 7. Pipeline stages (in order)

1. **Intake:** clarifying questions → confirmed `task_card.json`.
2. **Data:** gather data in priority order (Section 9), window it, label it, split it → `dataset_manifest.json`, `dataset_stats.json`, train/val/test files.
3. **Plan:** `candidate_plan.json`.
4. **Train + search:** successive halving (32 → 8 → 2 candidates, adjustable by data size) → `runs.json`.
5. **Validate:** Evaluator scores the top candidates on validation, writes `error_patterns.json`.
6. **Repair loop (capped at `MAX_REPAIR_ROUNDS`, default 3):** Orchestrator sends error patterns to the Data agent → targeted examples added to the training set only → Trainer retrains only the top 2 configs → Evaluator re-checks on validation. Stop when the target is met or the cap is reached. Repair never touches the sealed test set.
7. **Final exam:** Evaluator scores the final model on the sealed test set **exactly once**, plus the Nemotron zero-shot baseline on the same set.
8. **Deploy:** package the specialist and deploy it (Section 12).
9. **Deliver:** report card, specialist panel, API snippet, download.

---

## 8. JSON schemas (define all as Pydantic models in `backend/schemas/`)

### 8.1 `task_card.json`
- `task_id`, `task_name`, `description`
- `input_type`: `text` | `log_window` | `tabular` | `text_pair`
- `output_type`: `binary` | `multiclass` | `multilabel` | `spans` | `structured_json` | `number`
- `labels`: list with plain-English definitions
- `positive_definition` (what counts as the target case)
- `error_preference`: `recall_first` | `precision_first` | `balanced`
- `optimization_metric`: e.g. `recall_at_fpr`, `macro_f1`, `pr_auc`
- `fpr_target` (if applicable, e.g. 0.01)
- `needs_reason`: bool
- `latency_budget_ms`
- `deployment`: `offline` | `cloud_ok`
- `sample_inputs`: the user's pasted format samples
- `window_spec` (for logs): `group_by` (session id / user / block id), `window_minutes`

### 8.2 `dataset_manifest.json`
- sources: name, URL, license, license_ok (bool), rows used, real vs. synthetic flag
- format match score between source data and user's sample inputs, with explanation
- split sizes and class ratios for train / val / test

### 8.3 `dataset_stats.json`
- row counts, label counts, class imbalance ratio, average input length, vocabulary/keyword density estimate, whether the data is structured

### 8.4 `candidate_plan.json`
- list of candidates: `id` (A–H), hyperparameter search ranges, reason for inclusion
- reasons for excluded candidate types
- planner's plain-English summary (shown in the progress panel)

### 8.5 `runs.json`
- per candidate: config, status, error log path if failed, fix attempts, `metrics.json` path, halving round reached

### 8.6 Per-candidate `metrics.json`
- primary metric, precision, recall, F1, PR-AUC, recall@FPR (when applicable), p50/p99 latency, model size MB, estimated $/1M predictions

### 8.7 `eval_report.json`
- validation metrics per round, final sealed-test metrics, teacher agreement, Nemotron baseline metrics, real vs. synthetic scores, pass/repair decision with reason

### 8.8 `error_patterns.json`
- list of `{pattern, count, example_ids, suggested_data_fix}`

### 8.9 `run_state.json`
- current stage, repair round, LLM spend so far, budget remaining, timestamps, final status

---

## 9. Data handling

### 9.1 Priority order
1. **User's labeled data** (always preferred).
2. **Public labeled datasets**, found with Tavily and Hugging Face Hub search. For each candidate dataset: read and record the license, reject non-compatible licenses, download, inspect a sample, compute a format-match score against the user's sample inputs, and show the choice to the user for approval in the main chat before using it.
3. **Synthetic data from Nemotron**, only to fill gaps (rare attack patterns, missing classes, or when public data doesn't match the user's format). Synthetic data must be generated in the user's exact input format, using their sample lines as templates.

### 9.2 Rules
- For the demo, datasets are **pre-downloaded** into `data/` by `make demo-data`. Live Tavily search is still implemented and shown, but the demo never depends on live web results.
- Maintain a small vetted registry (`config/datasets.yaml`) of known-good datasets with license, URL, format notes. The Data agent checks the registry first, then falls back to open search.
- **Log data is always windowed** (grouped by session, user, or block ID over a time window per `window_spec`). Never classify single log lines.
- **Rebalance only the training set.** Validation and sealed test sets keep the natural class ratio.
- Split real labeled data into train / val / sealed test at intake, before any processing that could leak. Default 60 / 20 / 20, stratified.
- Deduplicate before splitting so near-duplicates don't leak across splits.
- When reasons are needed and a teacher-labeling pass is used, the Data agent uses the smaller Nemotron tier for bulk labeling and caches every call.
- Every dataset's license appears in the report card and README.

---

## 10. Candidate specialist types

Candidates A–F train on CPU. G is a STRETCH GPU tier. H wraps any of them.

| ID | Strategy | Inference | When to use |
|---|---|---|---|
| **A** | TF-IDF (word + char n-grams) + logistic regression / linear SVM | Microseconds, < 5 MB | Short, keyword-heavy text |
| **B** | Token Factory embeddings (**VERIFY** an embedding model is available) + LogReg / LightGBM / small MLP | One embedding API call | Paraphrase-heavy text, many labels; requires `cloud_ok` |
| **C** | Local MiniLM-class embedding model + classifier | ~5–20 ms CPU, offline | Same as B but `offline` deployment |
| **D** | Fine-tuned small encoder | Same as C | Only with 5k+ examples and enough time budget |
| **E** | LightGBM on engineered window features | Microseconds | Logs, tabular, numeric data |
| **F** | Regex + sequence tagger (CRF / token head) | Milliseconds | Span extraction (e.g. PII) |
| **G** (STRETCH) | LoRA on Qwen3-0.6B/1.7B or Llama-3.2-1B via the Token Factory fine-tuning API | GPU, dedicated endpoint | Only when the output itself is free text or JSON. Off by default because dedicated endpoints burn credits |
| **H** | Cascade: specialist answers confident cases, uncertain ones go to Nemotron | Mostly specialist cost | Threshold tuned on validation to hit a target metric. This is a key differentiator: always evaluate H on top of the best single candidate |

### 10.1 Planner decision rules (encode these in the planner prompt and in a deterministic fallback function)

| Task property | Effect |
|---|---|
| Output type | Which candidate types are eligible at all |
| 2–10 labels | Linear models usually enough |
| 50+ labels | Needs embeddings (B or C) |
| < ~1k labeled rows | Linear or embeddings only |
| 5k+ rows | D becomes worth trying |
| Short, keyword-heavy input | A |
| Paraphrase-heavy input | B or C |
| Needs reason per verdict | Feature-based reasons or teacher-explains-flags first; G only if free-text reasons are essential |
| `deployment: offline` | Exclude B and H's cloud fallback |
| Latency budget | Exclude candidates whose measured p99 exceeds it |
| Error cost asymmetry | Security tasks optimize recall at fixed FPR, not accuracy |
| Structured / log data | E (window features + LightGBM) |

If the LLM planner's output fails schema validation twice, fall back to the deterministic rule function and log that it happened.

### 10.2 Successive halving
- Start with up to 32 configurations across the chosen candidate types, train on a subsample, keep the best 8, train on more data, keep the best 2, train on full training data.
- Each branch writes `metrics.json`.
- Every branch has a time budget; branches exceeding it are killed and marked `timeout`.

### 10.3 Training sandbox (VERIFY)
- First choice: **Nebius Token Factory Sandboxes** (if they exist and are usable: verify availability, CPU/memory limits, max parallel branches, checkpoint/rollback support). Train one scikit-learn model in a sandbox on day one and time it.
- Fallback: run the same training scripts in local subprocesses with a process pool. The training scripts must be identical in both modes; only the launcher differs.
- Crashed runs: the Trainer reads the error, a small LLM proposes a patch to the training config/script, the run is resubmitted (max 2 fix attempts per candidate). Use checkpoints to roll back to the last good state if supported.
- Cap datasets at 5k–20k rows for CPU candidates by default.

### 10.4 Explanations without a fine-tuned LLM
- **Feature-based reasons** (default for candidate E): template the reason from the top contributing features, e.g. "7 failed logins in 60 s from a new IP". Deterministic and free.
- **Teacher explains flags only**: the specialist decides; Nemotron writes the reason only for items flagged positive. Since positives are rare (~1–3% in anomaly tasks), this costs almost nothing. Must be disabled when `deployment: offline`.
- G is reserved for tasks whose output is itself text.

---

## 11. Evaluation and honesty rules (never cut any of these)

1. **Sealed test set** split at intake from real labeled data; never shown to the Data agent, Planner, or Trainer, never used in repair, scored exactly once at the end.
2. **True labels, not agreement.** Report accuracy-type metrics against ground truth. Report teacher agreement separately and label it clearly as agreement.
3. **Real-data score even when training is synthetic.** Report both; if the real score is low, say so plainly in the report card.
4. **Imbalance-aware metrics:** precision, recall, F1, PR-AUC, recall at fixed FPR. Never headline plain accuracy on imbalanced data.
5. **Baseline every time:** Nemotron zero-shot on the same sealed set, using the task card as the prompt.
6. **Measure latency and cost, don't assume them.** Latency measured over at least 200 calls (p50, p99). Nemotron cost from actual token counts × `config/pricing.yaml`. Specialist cost from hosting cost ÷ measured throughput, with the formula shown in the report card.
7. **Repair loop is capped** and uses validation only.
8. Every number shown in the UI must trace back to a file in `runs/<run_id>/`.

---

## 12. Deployment of the specialist

- Package each specialist as: model file, decision threshold, feature/windowing config, and a small FastAPI inference server with `/predict` (single) and `/predict_batch` endpoints, plus `/health`.
- **VERIFY** and prefer **Nebius Serverless Endpoints** (or a Nebius AI Cloud CPU instance) for hosting the specialist image. Record exactly what was used in the README.
- Fallback: serve specialists from the main backend process, and say so honestly in the README.
- Candidate G (STRETCH) would deploy via Token Factory dedicated endpoints or serverless LoRA where supported; check pricing first and require explicit opt-in in the UI.
- The main app itself is deployed to a public URL (Nebius if possible; otherwise any host, while all model inference still runs on Nebius).

---

## 13. Reliability, budget, and replay mode

- **Response cache:** every LLM call is cached by (model, prompt hash, parameters) on disk. Re-running a stage reuses cached responses.
- **Budget guard:** the orchestrator stops the run with a clear message if LLM spend reaches `CREDIT_BUDGET_USD`. Spend is shown live in the progress panel.
- **Model tiering:** largest Nemotron only for planning, clarifying questions, synthetic generation, error analysis, and the baseline; smaller Nemotron for bulk labeling.
- **Replay mode** (`APP_MODE=replay`): the UI plays back a previously recorded run (`events.jsonl` with original timings, optionally sped up) and the specialist panel uses the saved model. Compare mode in replay still calls the live specialist and, if available, the live Nemotron model; if Nemotron is unreachable, it shows cached responses labeled "cached".
- `make replay RUN=<run_id>` starts the app in replay mode.
- Retries with exponential backoff on all network calls; clear user-facing errors, never silent failures.

---

## 14. Demo tasks (pre-configured)

Two tasks with different winning strategies, proving the agent actually chooses:

1. **Log anomaly detection (main demo).** Dataset: LogHub HDFS_v1 (real labels, sessions grouped by block ID). Expected winner: E (window features + LightGBM) with feature-based reasons. Frame it as **"system log anomaly detection"**, not login logs, because HDFS is a Hadoop file-system log dataset.
   - Optional alternative for a login/security story: the LANL "Comprehensive, Multi-Source Cyber-Security Events" dataset (authentication events with red-team labels). **VERIFY** its terms and size (it is very large); if unworkable, use HDFS.
2. **Support ticket routing.** Dataset: Banking77 (77 intents). **VERIFY** license. Expected winner: B or C (embeddings + classifier).
3. **Prompt-injection detection (STRETCH).** A public prompt-injection dataset (**VERIFY** license) plus Nemotron-generated adversarial examples. Expected winner: H (cascade), metric = recall at 1% FPR.

`make demo-data` downloads and prepares tasks 1 and 2 (and 3 if implemented), and records licenses in `config/datasets.yaml`.

---

## 15. Repository structure

```
synapse/
├── LICENSE                     # MIT
├── README.md
├── .env.example
├── Makefile
├── docker-compose.yml
├── config/
│   ├── models.yaml             # verified model IDs per role
│   ├── pricing.yaml            # verified per-token / hosting prices
│   └── datasets.yaml           # vetted dataset registry with licenses
├── backend/
│   ├── main.py                 # FastAPI app, SSE endpoint
│   ├── orchestrator.py
│   ├── llm_client.py           # Token Factory client, cache, cost tracking
│   ├── schemas/                # all Pydantic models
│   ├── agents/
│   │   ├── data_agent.py
│   │   ├── planner_agent.py
│   │   ├── trainer_agent.py
│   │   └── evaluator_agent.py
│   ├── candidates/             # one module per candidate type A–H
│   ├── features/               # log windowing + feature engineering
│   ├── sandbox/                # sandbox launcher + local fallback launcher
│   ├── serving/                # specialist inference server + Dockerfile
│   ├── specialist_chat/        # router.py, helper.py (tool-calling), slash_commands.py
│   ├── api_access/             # API keys (hashed), rate limiting, /v1/specialists routes
│   ├── export/                 # builds the download zip (predict.py, server.py, Dockerfile, README, report card)
│   └── tests/
├── frontend/
│   └── src/
│       ├── components/         # Sidebar, MainChat, Composer, TaskCard, BuildProgress, SpecialistChat, ResultCard, ResultsTable, CompareView, ReportDrawer, UseDialog (API + Download tabs), ParetoChart, QuickSwitcher
│       ├── styles/tokens.css   # color, type, spacing variables for light and dark
│       └── ...
├── data/                       # gitignored except small fixtures
├── runs/                       # gitignored except one recorded demo run
└── docs/
    ├── VERIFICATION.md         # results of every VERIFY item
    ├── ARCHITECTURE.md         # diagram + agent handoffs
    └── FEEDBACK.md             # detailed feedback on Token Factory, AI Cloud, NVIDIA models
```

---

## 16. README requirements

1. Project name, one-liner, and a GIF or screenshot of compare mode at the top.
2. The problem and who it's for.
3. How it works: architecture diagram (Mermaid), the four agents, the sealed test set guarantee.
4. **Built on Nebius and NVIDIA** section with a table: component → which Nebius/NVIDIA service → what it does in the pipeline. Include Nemotron roles (planner, teacher, judge, error analyst, baseline, cascade fallback), Token Factory structured output/function calling, embeddings (if used), sandboxes (if used), serverless/AI Cloud hosting, and Tavily.
5. Where Token Factory accelerated the workflow (concrete examples).
6. Real measured results: tables for both demo tasks (sealed-test metrics, Nemotron baseline, latency, cost, projected yearly cost).
7. Honest limitations section (e.g. Nemotron not fine-tunable on Token Factory, synthetic data caveats, format-mismatch risk).
8. Setup instructions (from clone to running in under 10 commands), environment variables, `make demo-data`, `make dev`, `make replay`.
9. Datasets used, with links and licenses.
10. MIT license notice.

---

## 17. Build order (follow strictly)

### Phase 0: Verify (do first, record everything in `docs/VERIFICATION.md`)
- Real Nemotron model IDs on Token Factory for each tier; confirm tool calling and JSON/structured output work with a test call.
- Whether an embedding model is available on Token Factory (for candidate B).
- Whether Token Factory Sandboxes exist and are usable: limits, max parallel branches, checkpoint/rollback. Train one scikit-learn model in one and time it.
- Pricing: per-token cost of each Nemotron tier, fine-tuning job cost, dedicated endpoint cost.
- Where to host the specialist on Nebius (Serverless Endpoints or AI Cloud).
- Dataset availability and licenses for HDFS, Banking77 (and LANL if chosen).
- Create the public repo with MIT license and README stub.

### Phase 1: Hardcoded pipeline, no LLM agents
- Logs → windows → features → train candidates E and A in parallel → validation metrics → sealed-test metrics → Nemotron zero-shot baseline.
- Implement every agent as a plain function that already reads and writes the exact JSON files from Section 8. This makes Phase 2 a swap, not a rewrite.
- Minimal UI shell following `docs/DESIGN.md`: sidebar, main chat, and a specialist chat that scores pasted inputs with the trained model (router format check only, no helper yet).
- **Exit criterion:** HDFS task runs end to end and produces a real report card.

### Phase 2: Agents and evaluation
- Planner with structured output plus deterministic fallback.
- Successive halving, Trainer error-fix loop, capped repair loop.
- Feature-based reasons.
- Report card, Pareto chart, second task (Banking77) through the same pipeline.
- Progress panel streaming real stage events with agent lanes.
- Unit test proving sealed test isolation.

### Phase 3: Product and demo
- Clarifying questions → editable task card flow.
- Compare mode with measured latency and cost and the yearly projection.
- Specialist chat: full router, helper with tools, slash commands, file upload with results table, source badges, saved history.
- Use dialog: API keys, `/v1/specialists` endpoints, snippets, "Try it" box, and the download zip.
- Specialist deployment on Nebius.
- UI polish pass against Section 5.9, with screenshots in both themes and at mobile width.
- Replay mode with one recorded demo run committed to the repo.
- Public demo URL.
- Complete README and `docs/FEEDBACK.md`.

### Cut order if behind (cut from the top first)
1. G (LoRA tier)
2. ONNX export
3. Multiple specialist tabs open at once
4. Demo task 3
5. Helper tools beyond explain / score_file / top_k (keep slash commands)
6. Per-key usage counters and the "Try it" box
7. Repair loop beyond 1 round
8. Live Tavily dataset search (use the pre-picked registry)

**Never cut:** sealed test set, Nemotron baseline, compare mode, parallel candidate training, honest real-vs-synthetic reporting, replay mode, specialist chat with result cards, API keys + predict endpoint, download zip that runs standalone, light/dark mode.

---

## 18. Testing requirements

- Unit tests for: log windowing, feature engineering, each candidate's train/predict interface, metric calculations (including recall@FPR), cost calculation, schema validation, the budget guard, and the cache.
- A test proving the Data agent and Trainer cannot read the sealed test directory.
- A test proving rebalancing is applied to train only (val/test class ratios unchanged).
- An integration test that runs the full pipeline on a tiny fixture dataset (a few hundred rows) in under 2 minutes with LLM calls mocked.
- Message router: valid inputs go to the specialist, files go to batch scoring, questions go to the helper, out-of-scope messages get the scope reply, and malformed inputs get the format message. With `deployment: offline`, no LLM call is made.
- Helper: cannot change a verdict; `set_threshold` requires confirmation before applying.
- API: requests without a key get 401, revoked keys get 401, rate limit returns 429, `predict` and `predict_batch` outputs match the in-app specialist.
- Download: the zip runs `predict.py` in a clean virtualenv and matches the hosted endpoint's outputs on fixture data.
- Frontend: smoke tests that the sidebar, main chat, build progress, specialist chat, compare view, report drawer, and Use dialog render with replay data, in light and dark mode, at desktop and mobile widths.

---

## 19. Acceptance criteria (the project is done when all are true)

- [ ] A user can describe the log anomaly task in chat, answer clarifying questions, confirm the task card, and watch a real run complete in the progress panel.
- [ ] The specialist chat opens side by side and returns a result card (verdict, confidence, reason) for a pasted log window.
- [ ] In the specialist chat, the user can upload a file and get a results table, ask "why did you flag this?", and ask for the top 10 most suspicious items, with correct source badges on every reply.
- [ ] Compare mode shows both models' outputs with measured latency and cost.
- [ ] A user can create an API key, call the specialist from curl using the shown snippet, and revoke the key.
- [ ] The downloaded zip runs on a clean machine with `predict.py` and with its Dockerfile.
- [ ] The UI matches Section 5.9: familiar chat layout, three specialist actions only, one overlay at a time, per-specialist colors, light and dark mode, responsive down to mobile.
- [ ] The report card shows sealed-test metrics against true labels, the Nemotron baseline, teacher agreement (separately labeled), and a Pareto chart.
- [ ] The Banking77 task runs through the same pipeline and the planner picks a different winning strategy than for logs.
- [ ] The specialist is reachable through a documented API endpoint.
- [ ] Replay mode reproduces a full recorded run reliably.
- [ ] The public demo URL works.
- [ ] Repo is public, MIT licensed, README complete, `docs/VERIFICATION.md` and `docs/FEEDBACK.md` filled in.
- [ ] All tests pass.

---

## 20. Things you must not do

- Do not let the helper LLM make or override a specialist verdict; the specialist always decides.
- Do not show a specialist reply without its source badge (Specialist vs. Helper · Nemotron).
- Do not pass messages that fail the format check to the specialist as if they were valid input.
- Do not store API keys in plain text; store hashes and show the key once.
- Do not classify single log lines.
- Do not headline plain accuracy on imbalanced data.
- Do not call teacher agreement "accuracy".
- Do not let any agent except the Evaluator read the sealed test set.
- Do not rebalance validation or test sets.
- Do not hardcode model IDs, prices, or secrets.
- Do not invent numbers for the UI, README, or video; every number must come from a run file.
- Do not claim Nemotron was fine-tuned.
- Do not claim "on-device" or "offline" for any path that calls a cloud API.
- Do not add agent frameworks.
- Do not let agents message each other directly; all coordination goes through the orchestrator and JSON files.
