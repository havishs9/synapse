# Demo video script (3:00 max)

Recorded from the public demo URL in replay mode (or `make replay` locally), 1440×900, light mode, browser zoom
100%. Builds replay at 8× from their recorded events; say "sped up" on screen. Every number spoken below is in a
committed run file (source in brackets). Centerpieces (DECISION D7): compare mode and the validated update.

**Before recording:** clear the browser's local storage for the site (fresh sidebar); open the procurement
specialist once so its model is loaded; check the compare call answers live (if Nemotron is down, the panel says
"cached", which is fine to show but say it).

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00–0:15 | Empty chat | Nothing yet | "Teams pay a frontier model for every repetitive record: every purchase line, every log window. Synapse builds a small specialist for that one job, tests it honestly against Nemotron, and ships the cheapest one that clears your bar." |
| 0:15–0:40 | Chat → questions → task card | Click "Sort purchase records into spending categories". Pick "Some categories are costlier to miss", then set it back to "All equally" on the card; scroll the plan changes | "Nemotron Ultra asks at most seven questions in one message. Every answer changes the plan: costlier misses add a per-category recall floor to the gate; cloud calls allowed lets Nemotron compete as a cascade stage." |
| 0:40–1:10 | Training view | Click Build specialist. Point at the scatter, then the Rounds columns | "Sped-up replay of the real build. Every dot is a candidate on the cost-versus-quality plane, colored by rung: rules, TF-IDF, embeddings, prompted Nemotron. Thirty candidates on 10% of the data, fourteen on 40%, six on all of it. The star is Nemotron Ultra zero-shot." [p2b-procurement-d events] |
| 1:10–1:30 | Specialist panel, Report drawer | Pane turns into the specialist. Open Report, scroll to sealed vs baseline | "It shipped a cascade: TF-IDF answers 64% of records, Nemotron Nano the uncertain 36%. On a sealed test set nothing in training ever touched: macro-F1 0.647 on 3,368 records. On the same 298 records, Nemotron Ultra zero-shot scores 0.456." [report_card.json] |
| 1:30–1:55 | Compare dialog | Click Compare → Compare (pre-filled record) | "Same record to both, at the same time. Same label. Latency and cost are measured on this call. At the task card's 2 million records a month, that's about $19,000 a year with Nemotron versus about $600 with the specialist." [compare projection = report_card projection] |
| 1:55–2:20 | Improve section → improve run | Click "Check held-back records", then (replay server) "Replay the improve run"; show the gate box; open the specialist and point at Version history and Roll back | "To update it, we use 95 held-back real records the live version got wrong, the stand-ins for user corrections. They go into training only. v3 takes one exam on the same sealed set and has to beat v2: 0.655 versus 0.647, so it deploys, and v2 stays one click away." [improve_report.json] |
| 2:20–2:45 | Log Anomaly Detector | Open it from the sidebar; Try a template example → Run; open Use | "Same agent, different shape: HDFS logs grouped into block windows, measured by recall at a 1% false-positive rate. Here a single TF-IDF model is enough: recall 1.000 on 2,850 sealed windows, where Ultra's coarse confidences can't rank at that rate. Each specialist is its own API with its own key." [p2b-logs-d report_card.json] |
| 2:45–3:00 | README "Built on Nebius and NVIDIA" or a title card | | "Nemotron Ultra plans, teaches and judges; Nano and Qwen3 embeddings are cascade stages; everything runs on Nebius Token Factory, with specialists served from one Nebius Serverless endpoint. Synapse." |

Notes:
- The example log window is built from the dataset's event templates and labeled as such in the UI; don't call it
  a real record.
- Don't say "offline" or "on-device" for procurement or support: they call Token Factory for escalated items.
- Don't call teacher agreement accuracy. Don't say Nemotron was fine-tuned.
- If the video runs long, cut the logs Use dialog first, then the training view's bracket.
