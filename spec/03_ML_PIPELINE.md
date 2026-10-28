# 03 ML pipeline

## 1. Data handling

### 1.1 Priority order

1. **User's labeled data** (always preferred).
2. **Public labeled datasets**, found via the vetted registry (`config/datasets.yaml`) first, then Tavily and Hugging Face Hub search. For each candidate dataset: read and record the license, reject incompatible licenses, download, inspect a sample, compute a format-match score against the user's sample inputs, and show the choice to the user in the main chat for approval before using it.
3. **Synthetic data from Nemotron**, only to fill gaps (rare classes, rare attack patterns, or when public data doesn't match the user's format). Generate it in the user's exact input format, using their sample rows as templates.

### 1.2 Rules

- For the demo, datasets are pre-downloaded into `data/` by `make demo-data`. Live Tavily search is still implemented and shown, but the demo never depends on live web results.
- **Dedupe before splitting** so near-duplicates don't leak across splits.
- **Split real labeled data into train / val / sealed test at intake**, before any processing that could leak. Default 60 / 20 / 20, stratified.
- **Rebalance only the training set.** Validation and sealed test keep the natural class ratio.
- **Log data is always windowed** (grouped by session, user or block ID over a time window per `window_spec`). Never classify single log lines.
- Cap CPU candidates at 5k to 20k training rows by default.
- When a teacher-labeling pass is used, the Data agent uses Nano/Lightning for bulk labeling and caches every call.
- Every dataset's license appears in the report card and README.
- No Corvo or customer data anywhere.

### 1.3 Demo task 1 data: USAspending procurement records

- Source: federal contract transaction data from USAspending. The FPDS transaction model includes `award_description`, `product_or_service_code`, `product_or_service_co_desc` and `naics` (CONFIRMED in the usaspending-api source). Download method (bulk download, Award Data Archive or API): VERIFY, pick the simplest that yields 20k to 50k rows.
- Input: the short description text (optionally plus vendor name and NAICS as extra features for candidate E).
- Label: the PSC rolled up to ~15 to 25 human-readable spending categories via `config/psc_categories.yaml`. PSC structure (CONFIRMED, USAspending glossary): R&D codes start with "A"; service codes start with a letter B to Z indicating the service subcategory; product codes start with two digits indicating the product subcategory. Build the mapping from the official PSC manual (VERIFY) and record it in `dataset_manifest.json`.
- Inspect descriptions for recurring boilerplate tokens and strip them if present; drop empty descriptions.
- Sample to keep every category above a minimum count; record the sampling in the manifest.
- Hold back a slice of labeled records (not in train/val/test) as the source of "user corrections" for the v1 → v2 demo.

### 1.4 Demo task 2 data: LogHub HDFS system logs

- Group log lines into sessions by block ID; each session is one input window. Labels are block-level normal/anomaly labels shipped with the dataset (VERIFY file names and license terms).
- Features for E: event-template counts per window, error/warning counts, window duration, event sequence statistics. Parse lines into templates first (a simple regex/Drain-style parser is enough).
- Metric: recall at a fixed FPR (default 1%), plus PR-AUC. Anomalies are rare, so never headline accuracy.
- Sample to 5k to 20k windows for CPU training, keeping the natural anomaly ratio in val/test.

## 2. Candidate ladder

Candidates sit on a ladder from cheapest to most expensive. The planner usually picks 2 to 3 families per task, then varies settings and training strategy within each. Every candidate is compared with the **Nemotron Ultra zero-shot baseline** (not itself a candidate).

| Rung | ID | Strategy | Inference | Notes |
|---|---|---|---|---|
| 1. Rules + classic ML | J | Rules / lookup tables (e.g. vendor → category, keyword rules) | Microseconds | Free; often handles the easy majority; good first cascade stage |
| 1. Rules + classic ML | A | TF-IDF (word + char n-grams) + logistic regression / linear SVM | Microseconds, < 5 MB | Short, keyword-heavy text |
| 1. Rules + classic ML | E | LightGBM on engineered features (window features for logs) | Microseconds | Logs, tabular, numeric data |
| 1. Rules + classic ML | F | Regex + sequence tagger (CRF / token head) | Milliseconds | Span extraction, e.g. PII |
| 2. Embeddings | I | Embeddings + cosine similarity to labeled examples or category centroids (kNN) | One embedding call, or local | No training; works with few labels; add a category by adding examples |
| 2. Embeddings | B | Qwen3-Embedding-8B (Token Factory) + LogReg / LightGBM / small MLP | One embedding API call | Paraphrase-heavy text, many labels; requires `cloud_ok` |
| 2. Embeddings | C | Local MiniLM-class embedding model + classifier | ~5 to 20 ms CPU, offline | Same as B but offline |
| 2. Embeddings | D | Fine-tuned small encoder | Same as C | Only with 5k+ examples and enough time budget |
| 3. Prompted LLMs | K | Nemotron-3-Nano-30B-A3B or Nemotron-3.5-Lightning + retrieved similar labeled examples in the prompt + constrained JSON output | Low per call | Few labels, fuzzy categories |
| 3. Prompted LLMs | L | Nemotron-3-Super-120b-a12b, same recipe | Medium per call | Harder reasoning, still far cheaper than Ultra |
| 4. Fine-tuned LLM | G (STRETCH) | LoRA on Qwen3-0.6B/1.7B or Llama-3.2-1B via the Token Factory fine-tuning API | GPU, dedicated endpoint | Only when the output itself is free text or JSON. Off by default; requires explicit opt-in because dedicated endpoints burn credits |
| Wrapper | H | Cascade: a cheap candidate answers confident cases; uncertain ones escalate (e.g. J/A → K → Ultra) | Mostly the cheap stage's cost | Always evaluate H on top of the best single candidate |

LLM rungs K and L are "trained" without fine-tuning: search varies the instruction wording and the number of retrieved examples (0, 5, 10), so they compete in the same tournament as the others. Every rung stays on Nebius.
EOFcat > spec/03_ML_PIPELINE.md << 'EOF'
# 03 ML pipeline

## 1. Data handling

### 1.1 Priority order

1. **User's labeled data** (always preferred).
2. **Public labeled datasets**, found via the vetted registry (`config/datasets.yaml`) first, then Tavily and Hugging Face Hub search. For each candidate dataset: read and record the license, reject incompatible licenses, download, inspect a sample, compute a format-match score against the user's sample inputs, and show the choice to the user in the main chat for approval before using it.
3. **Synthetic data from Nemotron**, only to fill gaps (rare classes, rare attack patterns, or when public data doesn't match the user's format). Generate it in the user's exact input format, using their sample rows as templates.

### 1.2 Rules

- For the demo, datasets are pre-downloaded into `data/` by `make demo-data`. Live Tavily search is still implemented and shown, but the demo never depends on live web results.
- **Dedupe before splitting** so near-duplicates don't leak across splits.
- **Split real labeled data into train / val / sealed test at intake**, before any processing that could leak. Default 60 / 20 / 20, stratified.
- **Rebalance only the training set.** Validation and sealed test keep the natural class ratio.
- **Log data is always windowed** (grouped by session, user or block ID over a time window per `window_spec`). Never classify single log lines.
- Cap CPU candidates at 5k to 20k training rows by default.
- When a teacher-labeling pass is used, the Data agent uses Nano/Lightning for bulk labeling and caches every call.
- Every dataset's license appears in the report card and README.
- No Corvo or customer data anywhere.

### 1.3 Demo task 1 data: USAspending procurement records

- Source: federal contract transaction data from USAspending. The FPDS transaction model includes `award_description`, `product_or_service_code`, `product_or_service_co_desc` and `naics` (CONFIRMED in the usaspending-api source). Download method (bulk download, Award Data Archive or API): VERIFY, pick the simplest that yields 20k to 50k rows.
- Input: the short description text (optionally plus vendor name and NAICS as extra features for candidate E).
- Label: the PSC rolled up to ~15 to 25 human-readable spending categories via `config/psc_categories.yaml`. PSC structure (CONFIRMED, USAspending glossary): R&D codes start with "A"; service codes start with a letter B to Z indicating the service subcategory; product codes start with two digits indicating the product subcategory. Build the mapping from the official PSC manual (VERIFY) and record it in `dataset_manifest.json`.
- Inspect descriptions for recurring boilerplate tokens and strip them if present; drop empty descriptions.
- Sample to keep every category above a minimum count; record the sampling in the manifest.
- Hold back a slice of labeled records (not in train/val/test) as the source of "user corrections" for the v1 → v2 demo.

### 1.4 Demo task 2 data: LogHub HDFS system logs

- Group log lines into sessions by block ID; each session is one input window. Labels are block-level normal/anomaly labels shipped with the dataset (VERIFY file names and license terms).
- Features for E: event-template counts per window, error/warning counts, window duration, event sequence statistics. Parse lines into templates first (a simple regex/Drain-style parser is enough).
- Metric: recall at a fixed FPR (default 1%), plus PR-AUC. Anomalies are rare, so never headline accuracy.
- Sample to 5k to 20k windows for CPU training, keeping the natural anomaly ratio in val/test.

## 2. Candidate ladder

Candidates sit on a ladder from cheapest to most expensive. The planner usually picks 2 to 3 families per task, then varies settings and training strategy within each. Every candidate is compared with the **Nemotron Ultra zero-shot baseline** (not itself a candidate).

| Rung | ID | Strategy | Inference | Notes |
|---|---|---|---|---|
| 1. Rules + classic ML | J | Rules / lookup tables (e.g. vendor → category, keyword rules) | Microseconds | Free; often handles the easy majority; good first cascade stage |
| 1. Rules + classic ML | A | TF-IDF (word + char n-grams) + logistic regression / linear SVM | Microseconds, < 5 MB | Short, keyword-heavy text |
| 1. Rules + classic ML | E | LightGBM on engineered features (window features for logs) | Microseconds | Logs, tabular, numeric data |
| 1. Rules + classic ML | F | Regex + sequence tagger (CRF / token head) | Milliseconds | Span extraction, e.g. PII |
| 2. Embeddings | I | Embeddings + cosine similarity to labeled examples or category centroids (kNN) | One embedding call, or local | No training; works with few labels; add a category by adding examples |
| 2. Embeddings | B | Qwen3-Embedding-8B (Token Factory) + LogReg / LightGBM / small MLP | One embedding API call | Paraphrase-heavy text, many labels; requires `cloud_ok` |
| 2. Embeddings | C | Local MiniLM-class embedding model + classifier | ~5 to 20 ms CPU, offline | Same as B but offline |
| 2. Embeddings | D | Fine-tuned small encoder | Same as C | Only with 5k+ examples and enough time budget |
| 3. Prompted LLMs | K | Nemotron-3-Nano-30B-A3B or Nemotron-3.5-Lightning + retrieved similar labeled examples in the prompt + constrained JSON output | Low per call | Few labels, fuzzy categories |
| 3. Prompted LLMs | L | Nemotron-3-Super-120b-a12b, same recipe | Medium per call | Harder reasoning, still far cheaper than Ultra |
| 4. Fine-tuned LLM | G (STRETCH) | LoRA on Qwen3-0.6B/1.7B or Llama-3.2-1B via the Token Factory fine-tuning API | GPU, dedicated endpoint | Only when the output itself is free text or JSON. Off by default; requires explicit opt-in because dedicated endpoints burn credits |
| Wrapper | H | Cascade: a cheap candidate answers confident cases; uncertain ones escalate (e.g. J/A → K → Ultra) | Mostly the cheap stage's cost | Always evaluate H on top of the best single candidate |

LLM rungs K and L are "trained" without fine-tuning: search varies the instruction wording and the number of retrieved examples (0, 5, 10), so they compete in the same tournament as the others. Every rung stays on Nebius.
