# Demo video script (3:00 max)

Recorded from the public demo URL in replay mode (or `make replay` locally), 1440×900, light mode, browser zoom
100%. Builds replay at 8× from their recorded events; say "sped up" on screen. Every number spoken below is in a
committed file (source in brackets). Centerpieces (DECISION D7): compare mode and the validated update.

**Before recording:** clear the browser's local storage for the site (fresh sidebar); open the procurement
specialist once so its model is loaded; check the compare call answers live (if Nemotron is down, the panel says
"cached", which is fine to show but say it). Warm up the Voice Command Parser: open it and **Run** one command a few minutes
before recording (the first call after an endpoint restart takes about 82 s while the 0.6B model loads; later
calls take 4 to 6 s, so cut the wait in editing). If it doesn't answer, show its Report instead and keep the same words.

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00–0:12 | Empty chat | Nothing yet | "Teams pay a frontier model for every repetitive record. Synapse builds a small specialist for that one job, tests it honestly against Nemotron, and ships the cheapest one that clears your bar." |
| 0:12–0:32 | Chat → task card | Click "Sort purchase records into spending categories". Answer the questions: 2 million a month, all categories equally, cloud calls allowed, under 50 ms (the recorded build's settings). Get the task card. Scroll the plan changes | "It trains on 17,732 labeled federal purchase records from USAspending.gov, public data with its license recorded. A few answers set the bar, and each one changes the plan: cloud calls let Nemotron compete as a cascade stage; the 50-millisecond budget limits prompted models to escalations." [p2b-procurement-d dataset_manifest.json, task_card.json] |
| 0:32–1:05 | Training view: Agents panel, narration feed, scatter | Click Build specialist. Point at the **Agents** panel (one lane per agent, and the chain of files handed between them). Click the **Planner** line in the narration feed to open `candidate_plan.json`, then close it. Point at the scatter, then the Rounds columns | "Sped-up replay of the real build. Four agents do the work, run by a plain-Python orchestrator, and every handoff between them is a JSON file you can open. Data seals a test set that only the Evaluator can read. The Planner, Nemotron Ultra, picks which model families to try, and says why. The Trainer races them on cost versus quality: thirty candidates on 10% of the data, fourteen on 40%, six on all of it. The Evaluator scores them against Nemotron Ultra zero-shot, the star." [p2b-procurement-d events.jsonl, candidate_plan.json; backend/orchestrator.py, backend/sealed.py] |
| 1:05–1:19 | Specialist panel, Report drawer | Pane turns into the specialist. Open Report, scroll to sealed vs baseline | "It shipped a cascade: TF-IDF answers most records, Nemotron Nano the uncertain rest. On the sealed test set: macro-F1 0.647 on 3,368 records. On the same 298 records, Nemotron Ultra zero-shot scores 0.456." [report_card.json] |
| 1:19–1:33 | Compare dialog | Click Compare → Compare (pre-filled record) | "Same record to both at once; latency and cost measured on this call. At 2 million records a month: about $19,000 a year with Nemotron, about $600 with the specialist." [compare projection = report_card projection] |
| 1:33–1:49 | Improve section → improve run | Click "Check held-back records", then "Replay the improve run"; show the gate box; point at Version history and Roll back | "To update it, 95 held-back records it got wrong go into training only. v3 sits the same sealed exam and must beat v2: 0.655 versus 0.647, so it deploys, and v2 stays one click away." [improve_report.json] |
| 1:49–2:12 | Sidebar: the other three specialists, about 7 s each | Open **Log Anomaly Detector** (point at the score). Open **Support Ticket Router** (point at the cascade split). Open **Voice Command Parser**, Run `wake me up at seven tomorrow` (warmed up), point at the JSON | "Same agents, three more architectures. Server logs: a single TF-IDF model, recall 1.000 on 2,850 sealed log windows. Support tickets: TF-IDF, with Qwen3 embeddings for the hardest 25%. Voice commands need structured JSON, so it's a 0.6-billion-parameter Qwen3 fine-tuned with LoRA: exactly right on 68% of sealed commands, Nemotron Ultra 37%." [p2b-logs-d, p2b-support-c report_card.json; voice-command-parser v1 sealed_metrics] |
| 2:12–3:00 | Sidebar **Builds** list (spend per build), then the README's "Built on Nebius and NVIDIA" table; end on a title card | Point at "Procurement Categorizer … $0.15" in Builds, then scroll the README table row by row as each service is named | "All of this runs on Nebius and NVIDIA. Every model call goes through Nebius Token Factory's OpenAI-compatible API, with prices read from its own model list. NVIDIA Nemotron Ultra is the brain: it plans each build, analyzes the errors, and is the baseline every specialist has to beat. Nemotron Nano and Lightning compete as prompted candidates, and Nano answers the uncertain procurement records in production. Qwen3 embeddings from Token Factory power the support cascade, and Token Factory fine-tuning trained the voice model's LoRA. A whole build costs cents: about 15 cents of Token Factory calls for procurement. Then every specialist serves from one Nebius Serverless CPU endpoint, its model in Nebius Object Storage, each behind its own API key. Synapse." [README "Built on Nebius and NVIDIA"; p2b-procurement-d run_state.json spend_usd 0.146; p2b-procurement-d report_card.json cascade K-11 = Nemotron Nano; p2b-support-c B-02 = Qwen3-Embedding-8B] |

Notes:
- The demo doesn't show the dataset search, so don't mention Tavily or Hugging Face for the demo tasks: their data
  comes from the vetted list (config/datasets.yaml).
- Uploading your own labeled data isn't built yet. If asked, it's on the roadmap; don't show the Attach button as
  a training-data upload.
- The example log window is built from the dataset's event templates and labeled as such in the UI; don't call it
  a real record.
- Don't say "offline" or "on-device" for procurement or support: they call Token Factory for escalated items.
- Don't call teacher agreement accuracy. Nemotron was not fine-tuned: the fine-tuned model is Qwen3-0.6B.
- The voice parser scores are on a 300-command sample of MASSIVE's sealed test split (CC-BY-4.0).
- Agents: Data, Planner, Trainer and Evaluator are modules run in a fixed order by the orchestrator (plain Python,
  not an LLM); Nemotron is the model inside some of them (the Planner's plan, the Evaluator's error analysis and
  baseline, the prompted candidates the Trainer runs). Don't call them autonomous or say they talk to each other:
  every handoff is a file in the run folder. The procurement run had no repair round, so don't mention one.
- Nebius section: Token Factory Sandboxes are **not** used (training ran as local processes), so don't say training
  runs on Nebius; say model calls, fine-tuning, serving and storage do.
- If the video runs long, cut the Rounds columns in the training view first, then the Roll back point; keep the
  Nebius/NVIDIA section whole.
