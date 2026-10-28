# 01 Product spec

## 1. What we are building

Synapse is a web app where a user chats with a large NVIDIA Nemotron model, describes a repetitive task in plain English (for example, "sort our purchase records into spending categories"), and the system automatically builds, tests and deploys a small **specialist** for that one task. The specialist is far cheaper and faster than calling the large model, and the system measures and reports the exact accuracy, latency and cost tradeoff honestly.

- **Analogy for UI copy:** a senior doctor (the big model) trains a nurse (the specialist) to run one screening test. The nurse is faster and cheaper, and nearly as good on that one test.
- **One-liner for judges:** describe a repetitive task in plain English; the agent benchmarks rules, classic ML, embeddings and smaller LLMs against Nemotron Ultra, then ships the cheapest one that passes, with measured savings. Use real measured numbers in all copy, never placeholder multipliers.
- **Product framing:** we sell a managed specialist, not a model file: the cheapest model or pipeline that meets the user's quality, latency and cost bar, served as a versioned API on Nebius and improved only through validated updates.
- **Track:** Coding and Agentic Engineering (the agent writes training code, runs it in Token Factory Sandboxes, and tests the result).

## 2. User-facing features

### 2.1 Main chat

- A chat window with the main model (largest Nemotron tier in `config/models.yaml`).
- The user types a task description and can optionally attach a file (CSV, JSONL, or plain-text logs) of labeled or unlabeled examples.
- If no labeled data is attached, the system still asks the user to **paste 10 to 20 sample rows of their real data** (labels not required) so it knows the real input format. Explain why in the UI: models learn the shape of the data they are trained on.
- The main chat also works as a normal chat for questions that are not "build a specialist" requests.

### 2.2 Clarifying questions → task card (DECISION D5)

Before building, the main model asks **one message with at most 7 questions** (hard cap):

1. What are the labels/categories, and what does each mean? (For binary tasks: what counts as the positive case?)
2. Which mistake is worse: missing a real case or raising a false alarm? (For multiclass: are some categories more costly to get wrong?) Maps to the optimization metric.
3. Category/verdict only, or with a reason?
4. Roughly how many items per month? (Drives the cost projection.)
5. Latency budget per item (e.g. under 50 ms)?
6. Must it run fully offline, or are cloud API calls allowed at inference time?
7. Build budget in dollars or minutes? (Default: `CREDIT_BUDGET_USD`.)

The answers become a **task card** (schema in file 02) shown as an editable summary card with a **"Build specialist"** button. The build starts only after the user confirms.

**Each answer visibly changes the plan.** Show a short "plan change" line per answer, for example:

| User says | Plan change shown |
|---|---|
| "Missing an attack is far worse than a false alarm" | Metric switched to recall at 1% FPR; cascade enabled |
| "Just the category, no explanations" | Explanation-heavy candidates dropped |
| "It has to run on our own servers" | Cloud-embedding candidates (B, cloud I) removed; local C added |
| "About 2 million records a month" | Latency budget tightened; cost projection updated |

### 2.3 Training view (progress + visualization)

Replaces any loading spinner. Streams real backend events over SSE. Every number traces back to a file in `runs/<run_id>/`.

| View | What it shows | Priority |
|---|---|---|
| Narration feed | One plain-English line per event, labeled by agent (Data / Planner / Trainer / Evaluator), with elapsed time and running LLM spend in dollars. Clicking an event expands the underlying JSON file. | Must |
| Live Pareto scatter (hero visual) | X: cost per 1M predictions (log scale). Y: target metric. A dot per candidate as it finishes, colored by ladder rung; eliminated dots fade; frontier line redraws; Nemotron Ultra baseline as a star; target as a horizontal line. | Must |
| Agent lanes | One lane per agent with handoff arrows when a JSON file passes between them | Should |
| Tournament bracket | Rounds as columns; each candidate a card with a live validation sparkline; eliminated cards gray out with a one-line reason ("F1 0.71 < 0.85 target") | Should |
| Budget meter | Credits and minutes spent vs. the budget from the task card | Should |
| Lineage tree | Which candidate came from which, ending at the shipped version; each node is a real Sandbox checkpoint | STRETCH |

Example narration lines:

- "Data: found your 2,000 labeled rows"
- "Data: 3 categories have under 50 examples; rebalancing the training set only"
- "Planner: trying rules (J), TF-IDF (A), embedding similarity (I) and prompted Nano (K), because descriptions are short and keyword-heavy"
- "Trainer: round 1, 28 candidates on 10% of data"
- "Trainer: round 2, 7 candidates on 40% of data"
- "Evaluator: macro-F1 0.91 on validation"
- "Repair round 1: office supplies often filed as IT equipment; adding 200 targeted examples"
- "Evaluator: final score on sealed test set"
- "Deployed v1"

### 2.4 Results

A **recommended specialist plus 1 to 2 alternatives** from the Pareto frontier (e.g. "most accurate" vs. "cheapest"), each with its report card. The recommendation follows the task card's priorities; the user can pick an alternative before deployment.

### 2.5 Specialist panel (tool UI, NOT a chat)

When a specialist is ready, a panel opens side by side with the main chat, titled e.g. "Procurement Categorizer v1". It is a tool, not a chat, because a small classifier cannot hold a conversation.

- Input box (paste one item, or one log window for log tasks) and file upload for batch scoring.
- Output: label/verdict, confidence, and reason (if the task card asked for reasons). If the cascade escalated the item, say so.
- Batch mode: results table with labels and confidences, downloadable as CSV.
- Input that doesn't match the expected format gets a clear validation error, not a meaningless prediction.
- **Small dashboard:** version, per-class precision and recall, cost per record, latency p50/p99, comparison to the Nemotron baseline, version history.

### 2.6 Compare mode

- A toggle sends the same input to the main model (Nemotron zero-shot, using the task card as the prompt) and the specialist at the same time.
- Side by side: both labels, both reasons, measured latency, and measured/calculated cost of each call.
- Projection line (DECISION D6): "At <monthly volume from task card>: Nemotron $X/year vs. specialist $Y/year", computed from measured numbers and `config/pricing.yaml`. The volume always comes from the task card's `monthly_volume`; `DEMO_MONTHLY_VOLUME` is used only if the user skipped that question, and the UI says so. Show the calculation method on hover.
- One of the two centerpieces of the demo video. Must be fast, stable and visually clear.

### 2.7 Report card

Shown in the specialist panel, downloadable as JSON and Markdown:

- Winning strategy, why the planner chose it, and the frontier alternatives.
- Metrics on the sealed test set against true labels, including **per-class precision and recall**.
- **Validation vs. sealed-test scores side by side** (expect sealed to be slightly lower; picking among many candidates inflates validation).
- **Seed error bars:** the final 2 candidates rerun with 3 random seeds.
- Agreement rate with the Nemotron teacher, reported separately and labeled as agreement.
- Nemotron zero-shot baseline on the same sealed set.
- If training used synthetic data: score on real data and on synthetic data, both reported.
- Latency p50 and p99, throughput, model size on disk, cost per 1M predictions (formula shown).
- Cascade escalation rate, if H is used.
- "Would more data help?" curve: winner's score at 10% / 40% / 100% of training data.
- Known weaknesses (top error patterns from the Evaluator).
- Data sources used, with licenses.
- Pareto chart: metric vs. latency vs. cost for surviving candidates plus the Nemotron baseline.

### 2.8 Use via API (DECISIONS D2, D3)

- Every specialist has **its own API**: its own URL (`https://<endpoint>/v1/specialists/{specialist_id}/predict`, plus a version-pinned route) and **its own API key**, created when the specialist is first deployed.
- **"Use via API"** button shows the specialist's URL, a reveal-once API key with a regenerate option, and copy-paste snippets (curl and Python).
- The live route always serves the current live version; the pinned route (`/v{n}/predict`) lets callers lock a version.
- **No model download.** Model files stay managed by the platform.

### 2.9 Improve: validated v1 → v2 update

1. The user corrects a few wrong predictions in the specialist panel.
2. The Data agent adds the corrected examples (and targeted variants) to the training set only.
3. The Trainer retrains the current winner config (and runner-up).
4. The Evaluator gives v2 its one final exam on the **fixed benchmark**: the same sealed test set v1 was scored on. The corrections never enter that set, and nothing in training or repair ever reads it (rules in file 03).
5. v2 deploys **only if it beats v1 and passes every threshold**. Otherwise v1 stays live and the UI shows why v2 lost.
6. Version history with a one-click **rollback**.

Demo: corrections come from a held-back slice of real labeled records; say so in the video.

### 2.10 Multiple specialists (STRETCH)

Each specialist appears as its own tab; a sidebar lists past specialists from SQLite.

### 2.11 UI design and navigation

The interface should feel as familiar as popular LLM chat apps (a sidebar, one conversation column, a composer at the bottom) but calmer and less cluttered. A first-time user must be able to build and use a specialist without reading instructions.

**Layout:**

- **Sidebar** (collapsible): "New chat", recent chats, and a "Specialists" list. Nothing else.
- **Main chat:** centered conversation column (max ~720px wide), composer pinned to the bottom with an attach button. The task card appears inline as an editable message with one primary button: **Build specialist**.
- **Right pane:** opens when a build starts and shows the training view (section 2.3). When the build finishes, the same pane becomes the specialist panel (section 2.5). The divider is draggable; a close button collapses it to the sidebar entry.
- **Specialist panel header** has exactly three actions: **Compare**, **Report**, **Use** (the API panel from section 2.8). Version history and corrections live inside the panel's dashboard, not as extra header buttons.
- **Report** opens as a drawer over the right pane. **Use** opens as a centered dialog. Never more than one overlay open at a time.

**Visual identity (one memorable element, everything else quiet):**

- The memorable element: **every specialist gets its own color and a two-letter monogram**, assigned at build time from a curated palette of 8 accessible hues. That color appears only in its sidebar dot, its panel header and its result markers. The main model stays neutral.
- In the training view, Pareto dots are colored by ladder rung; keep that palette separate from specialist colors.
- Neutrals: cool off-white background in light mode (e.g. `#F6F7F9`), true dark grey in dark mode (e.g. `#1C1D21`), ink `#16181D` / `#E8E9EC`. All colors are CSS variables with light and dark values.
- Typography: **IBM Plex Sans** for the interface; **IBM Plex Mono only for log lines, record text, code and API snippets**. One type scale, sentence case everywhere, no all-caps labels.
- Avoid generic defaults: no gradient washes, no identical shadowed cards for every element, no decorative eyebrow labels, no arrows appended to button text. Result cards and tables use thin borders, not shadows.

**Motion:** one deliberate moment. When a build finishes, the winning dot on the Pareto scatter pulses once and the right pane transitions into the specialist panel with its monogram. Everything else uses quick, functional transitions only. Respect `prefers-reduced-motion`.

**Chat quality bar (match popular LLM chat apps):**

- Streaming responses token by token, with a stop button.
- Markdown rendering; syntax-highlighted code blocks with copy buttons.
- Drag-and-drop file upload with a file chip showing name and row count.
- Copy and retry actions on hover in the main chat.
- Main chat empty state: one sentence on what the app does plus three example prompts as clickable chips ("Sort purchase records into spending categories", "Flag anomalies in system logs", "Route support tickets to the right team").
- Specialist panel empty state: the expected input format with a "Try an example" button that inserts a real sample.

**Navigation and accessibility:**

- `Cmd/Ctrl+K` quick switcher (chats and specialists), `Cmd/Ctrl+Enter` to send, `Esc` closes overlays, visible focus states.
- Light and dark mode following the system setting, with a manual toggle in the sidebar footer.
- Under 1024px wide, the main chat and right pane become two tabs; under 768px, the sidebar becomes a drawer.
- WCAG AA contrast for all text and controls.

**Copy rules:** plain, active language named after what users do: "Build specialist", "Compare", "Report", "Use", "Copy API key", "Deploy v2", "Roll back". Errors say what went wrong and how to fix it. Technical detail (agent names, JSON files, candidate IDs) appears only in the narration feed's expanded events and the report drawer.

**Implementation:** React + Vite + TypeScript + Tailwind, with shadcn/ui (Radix) primitives for dialogs, drawers, tabs and tooltips. Before writing frontend code, write a short design plan in `docs/DESIGN.md` (color tokens, type scale, layout, the one memorable element) and follow it. Screenshot each main screen in both themes and at mobile width, and review against this section before Phase 3 is marked done.
