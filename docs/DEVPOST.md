# Devpost submission

Track: **Coding and Agentic Engineering**

Links: demo URL https://synapse-red-ten.vercel.app/ · repo https://github.com/havishs9/synapse · video _(YouTube, add after upload)_

## Tagline

Describe a repetitive task; an agent benchmarks rules, classic ML, embeddings and smaller LLMs against Nemotron
Ultra and ships the cheapest specialist that passes, with measured savings.

## Inspiration

Most "AI" spend in operations goes to one narrow call made millions of times: categorize this purchase line,
flag this log window, route this message. Teams send all of it to a frontier model because building and
maintaining a smaller model is a project in itself. We wanted an agent that does that project, and reports the
tradeoff honestly instead of promising a multiplier.

## What it does

1. You describe the task in chat. Nemotron Ultra asks at most seven clarifying questions in one message (which
   mistake is worse, volume, latency, cloud or not, budget). Your answers become an editable task card, and every
   answer shows how it changes the plan.
2. Four agents (Data, Planner, Trainer, Evaluator), coordinated by a plain-Python orchestrator, build candidates
   across a ladder from keyword rules to prompted Nemotron, run a successive-halving search on 10%, 40% and 100%
   of the data, repair weak spots with targeted examples, and fit a cascade where a cheap model answers what it's
   sure of and escalates the rest. You watch it live: a Pareto scatter of cost versus quality, agent lanes,
   a tournament bracket and a budget meter.
3. The winner takes one exam on a sealed test set that only the Evaluator can read, next to Nemotron Ultra
   zero-shot on the same records. It ships as its own versioned API with its own key.
4. Compare mode sends one input to both models at once and shows measured latency, cost per call and the yearly
   projection at your volume.
5. Corrections retrain the winner and runner-up; the new version deploys only if it beats the live one on the
   same sealed test set. Rollback is one click.

## Results (from our committed run files)

| Task | Specialist vs Nemotron Ultra (same sealed records) | Cost per 1M predictions | Yearly at the task's volume |
|---|---|---|---|
| Procurement categories, 19 classes (USAspending) | macro-F1 0.627 vs 0.456 | $25.87 vs $806.78 | $621 vs $19,363 (2M/month) |
| Support routing, 77 intents (Banking77) | macro-F1 0.913 vs 0.738 | $0.12 vs $1,029.14 | $0.72 vs $6,175 (500k/month) |
| Log anomalies (LogHub HDFS) | recall at 1% FPR 1.000 vs 0.000 | $0.0036 vs $1,746.33 | $0.21 vs $104,780 (5M/month) |

Each build cost $0.07 to $0.31 of Token Factory credit. Validated updates from held-back real records: procurement
v2 → v3 (0.647 → 0.655 on the same 3,368 sealed records), support v1 → v2 (0.933 → 0.935).

## How we built it

- **Backend:** FastAPI, Pydantic schemas for every handoff file, SSE for progress, scikit-learn, LightGBM,
  sentence-transformers. No agent framework: agents are functions that read and write JSON files.
- **Models (Nebius Token Factory):** Nemotron-3-Ultra (planner with JSON schema output, intake, teacher, error
  analysis, baseline), Nemotron-3-Nano and 3.5-Lightning (prompted rungs, cascade fallback), Nemotron-3-Super (rung
  L), Qwen3-Embedding-8B (embedding rungs).
- **Serving (Nebius AI Cloud):** one Serverless CPU endpoint hosts every specialist's routes with per-specialist
  hashed keys; Object Storage holds version bundles (hash-checked on load) and run folders.
- **Product:** React + Vite + TypeScript + Tailwind on Vercel; Supabase for sign-in and Postgres records.
- **Replay mode** plays recorded builds with their original timing, so the demo never depends on a live build.

## Challenges

- Keeping the evaluation honest under search: picking among dozens of candidates inflates validation, so the sealed
  set is enforced in code (only the Evaluator module can read it) and every version is graded on it exactly once.
- Our first cascades escalated too much for too little gain; the threshold rule now takes the cheapest
  expected cost within a small tolerance of the best score.
- Successive halving initially cut every cheap TF-IDF config in round 1 and shipped a cloud model as "cheapest";
  each round now also keeps the cost frontier.
- Token Factory Sandboxes weren't enabled on our account, so training runs as local parallel processes.

## What we learned

The frontier model is a great teacher and a mediocre high-volume worker: Ultra planned well and wrote good
questions, but a TF-IDF model trained on the same data beat its zero-shot score on all three tasks, at a few
cents per million predictions. The cascade gets the rest of the way by spending Nemotron only on the hard cases.

## What's next

Upload your own data with teacher labeling by Nemotron Nano, live dataset search with license checks, build
workers on Nebius AI Jobs, and per-user budgets.

## Feedback on Nebius and NVIDIA tools

See `docs/FEEDBACK.md` in the repo (paste its contents into Devpost's feedback field).
