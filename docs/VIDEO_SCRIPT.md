# Demo video script (3:00 max)

Recorded from the public demo URL in replay mode (or `make replay` locally), 1440×900, light mode, browser zoom
100%. Builds replay at 8× from their recorded events; say "sped up" on screen. Every number spoken below is in a
committed file (source in brackets). Centerpieces (DECISION D7): compare mode and the validated update.

**Before recording:** clear the browser's local storage for the site (fresh sidebar); open the procurement
specialist once so its model is loaded; check the compare call answers live (if Nemotron is down, the panel says
"cached", which is fine to show but say it). Warm up the Voice Command Parser: open it and **Run** one command a few minutes
before recording (the first call after an endpoint restart takes about 82 s while the 0.6B model loads; later
calls take 4 to 6 s, so cut the wait in editing). If it doesn't answer, show its Report instead and keep the same words.

**Typed lines.** Intake is a conversation: you click the example, then type two replies. Type them exactly as
below (or paste them): each matches the settings of the recorded build it replays, so the task card on screen is
the card that was built. They parse without a model call (`backend/tests/test_product.py::SCRIPTED`).

| When | Type |
|---|---|
| "OK to train on it?" | `Yes, use it` (or click the chip) |
| The four questions | `About 2 million records a month. All categories matter equally. Give me the category with a short reason. Cloud calls are fine, but keep each answer under 50 ms.` |

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00–0:12 | Empty chat | Nothing yet | "Teams pay a frontier model for every repetitive record. Synapse builds a small specialist for that one job, tests it honestly against Nemotron, and ships the cheapest one that clears your bar." |
| 0:12–0:30 | Data message | Click "Sort purchase records into spending categories". Click "Show the search" | "First, data. Nemotron Ultra drafted the searches; it searched Hugging Face and the web through Tavily and checked every license. Seven candidates, none usable: non-commercial or unknown licenses, files it couldn't read, labels that don't match. So it proposes a vetted dataset instead: 17,732 labeled federal purchase records, public data. It asks before using anything." [artifacts/demo/data_search/procurement.json, p2b-procurement-d dataset_manifest.json] |
| 0:30–0:48 | Questions → task card | Click "Yes, use it". Type the reply above, Ctrl+Enter. Scroll the plan changes | "Then a few questions, answered in plain words. Every answer changes the plan: cloud calls allowed lets Nemotron compete as a cascade stage; the 50-millisecond budget keeps prompted models out unless they only take escalations." |
| 0:48–1:12 | Training view | Click Build specialist. Point at the scatter, then the Rounds columns | "Sped-up replay of the real build. Every dot is a candidate on the cost-versus-quality plane, colored by rung: rules, TF-IDF, embeddings, prompted Nemotron. Thirty candidates on 10% of the data, fourteen on 40%, six on all of it. The star is Nemotron Ultra zero-shot." [p2b-procurement-d events] |
| 1:12–1:28 | Specialist panel, Report drawer | Pane turns into the specialist. Open Report, scroll to sealed vs baseline | "It shipped a cascade: TF-IDF answers most records, Nemotron Nano the uncertain rest. On a sealed test set nothing in training ever touched: macro-F1 0.647 on 3,368 records. On the same 298 records, Nemotron Ultra zero-shot scores 0.456." [report_card.json] |
| 1:28–1:48 | Compare dialog | Click Compare → Compare (pre-filled record) | "Same record to both, at the same time. Latency and cost are measured on this call. At 2 million records a month, that's about $19,000 a year with Nemotron versus about $600 with the specialist." [compare projection = report_card projection] |
| 1:48–2:08 | Improve section → improve run | Click "Check held-back records", then "Replay the improve run"; show the gate box; point at Version history and Roll back | "To update it, 95 held-back records the live version got wrong go into training only. v3 takes one exam on the same sealed set and has to beat v2: 0.655 versus 0.647, so it deploys, and v2 stays one click away." [improve_report.json] |
| 2:08–2:46 | Sidebar: the other three specialists, about 12 s each | Open **Log Anomaly Detector**, point at the report's architecture line and score. Open **Support Ticket Router**, point at the cascade split. Open **Voice Command Parser**, type `wake me up at seven tomorrow`, Run, point at the JSON | "Four specialists, four different architectures, all picked by the same agent. Server logs: one TF-IDF model, recall 1.000 at a 1% false-alarm rate on 2,850 sealed log windows. Support tickets: TF-IDF answers 75%, Qwen3 embeddings the hardest 25%; macro-F1 0.913 against Ultra's 0.738 on the same 300 tickets. And when the output is structured, a classifier isn't enough: a 0.6-billion-parameter Qwen3 fine-tuned with LoRA on Token Factory turns a voice command into intent and slots as JSON. Exactly right on 68% of 300 sealed commands, where Nemotron Ultra gets 37%." [p2b-logs-d, p2b-support-c report_card.json; voice-command-parser v1 sealed_metrics, g-massive-a eval files] |
| 2:46–3:00 | README "Built on Nebius and NVIDIA" or a title card | | "Nemotron plans, teaches and judges; Nano and Qwen3 embeddings are cascade stages; the small model is fine-tuned on Token Factory; specialists serve from one Nebius Serverless endpoint. Synapse." |

Notes:
- Don't say the search found the training data: it found nothing usable, and the dataset comes from the vetted
  list (config/datasets.yaml). The search was recorded on 2026-10-30 (`scripts/record_data_search.py`), which the
  expanded search says on screen; a live server runs it for every new task.
- Uploading your own labeled data isn't built yet. If asked, it's on the roadmap; don't show the Attach button as
  a training-data upload.
- The example log window is built from the dataset's event templates and labeled as such in the UI; don't call it
  a real record.
- Don't say "offline" or "on-device" for procurement or support: they call Token Factory for escalated items.
- Don't call teacher agreement accuracy. Nemotron was not fine-tuned: the fine-tuned model is Qwen3-0.6B.
- The voice parser scores are on a 300-command sample of MASSIVE's sealed test split (CC-BY-4.0).
- If the video runs long, cut the Rounds columns in the training view first, then the Roll back point.
