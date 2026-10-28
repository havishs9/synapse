# Report card: Log Anomaly Detector

Run `p2b-logs-d`

## Winning strategy

**A-12** (family A): misses cost more than false alarms (task card), so among candidates meeting the recall_at_fpr target of 0.90 this is the best detector: 1.000, PR-AUC 0.9999 on validation.

Planner (llm): Trying rules (J), TF‑IDF linear models (A), LightGBM on engineered features (E), and embedding kNN/centroids (I) because they provide fast interpretable baselines, classic text classification, the recommended engineered‑feature approach for long log windows, and semantic similarity methods that fit the cloud deployment and latency budget.; prompted Nemotron (K) added so the cascade can be evaluated

Frontier alternatives:

- recommended: A-12 — recall_at_fpr 1.000 on validation, $0.0036 per 1M predictions, p50 0.41 ms

## Sealed test set (true labels)

- recall_at_fpr: **1.000** on 2850 records
- macro precision 0.911, macro recall 0.997, macro F1 0.949
- PR-AUC 1.000; recall at 1% FPR 1.000
- with the threshold chosen on validation: recall 1.000 at FPR 0.651%
- validation 1.000 vs sealed 1.000 (sealed is not lower here; with one config per family there was little selection to inflate validation)

| Class | Precision | Recall | Support |
|---|---|---|---|
| anomaly | 0.822 | 1.000 | 83 |
| normal | 1.000 | 0.993 | 2767 |

## Nemotron Ultra zero-shot baseline

On the same 300 sealed records: Nemotron Ultra recall_at_fpr 0.000 vs specialist 1.000.
Baseline p50 latency 1495 ms, $1746.33 per 1M predictions.

At their own labels (anomaly class): Nemotron Ultra recall 0.627, precision 0.525; specialist recall 0.988, precision 1.000. Ultra's self-reported confidence is too coarse to rank windows, which is why its recall at a fixed 1% FPR is so low.

Agreement with Nemotron Ultra (agreement, not accuracy): 73.7% on 300 records.

## Seed error bars (3 seeds, validation)

- A-12: 1.000 ± 0.000

## Speed and cost

- latency p50 0.413 ms, p99 0.856 ms
- throughput 5430 items/s; model size 0.01 MB
- $0.0036 per 1M predictions; formula: endpoint_hourly_usd × (1e6 / throughput_per_s) / 3600
- at 5,000,000 records/month (task card): Nemotron Ultra $104,780/year vs specialist $0.21/year (cost per 1M predictions × monthly_volume × 12 / 1e6 (marginal cost; the Serverless endpoint is shared by all specialists))
- cascade A-12 → K-01: answered by A-12 100.0% / K-01 0.0% on validation (not used: no cascade gained over 0.01 on the shared validation sample)

## Would more data help?

- 10% of training data: 1.000
- 40% of training data: 1.000
- 100% of training data: 1.000

## Known weaknesses

- normal confused with anomaly (1 validation errors): The classifier misinterprets routine block allocation and DataNode receipt logs containing temporary task paths and block IDs as anomalous due to insufficient normal examples of this common NameNode-DataNode coordination pattern.

## Data sources

- loghub_hdfs_v1 (https://zenodo.org/records/8196385/files/HDFS_v1.zip): Loghub license: freely available for research or academic work; must reference the loghub repo URL and cite the Loghub paper; license notice must be included in all copies; 15,000 rows. Cite: Jieming Zhu, Shilin He, Pinjia He, Jinyang Liu, Michael R. Lyu. Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics. ISSRE 2023.; Wei Xu, Ling Huang, Armando Fox, David Patterson, Michael Jordan. Detecting Large-Scale System Problems by Mining Console Logs. SOSP 2009.
