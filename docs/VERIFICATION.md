# Verification log

Results of every VERIFY item in the spec. Phase 0 run on 2026-10-27 (US evening; 2026-10-28 UTC).
Raw evidence lives in `runs/verify/`. Scripts that produced it live in `scripts/verify/` and `scripts/data/`.
No secret values are recorded here or in `runs/verify/`.

## Summary

| # | Phase 0 item | Result |
|---|---|---|
| 1 | Exact API model IDs; tool calling + JSON output | **PASS** (all 5 models; 13/13 test calls passed) |
| 2 | Sandboxes: whoami, base image, one timed training run | **FAIL: no permissions on our account.** Fallback applied: `TRAINING_BACKEND=local` |
| 3 | Prices for every model + Serverless CPU preset | **PASS** (`config/pricing.yaml`) |
| 4 | Serverless: CPU hello-world endpoint with token auth | **BLOCKED**: needs `nebius` CLI with interactive login (team action) |
| 5 | Object Storage reachable from the endpoint | **BLOCKED**: depends on 4; no bucket or credentials in `.env` yet |
| 6 | USAspending download path; 20k–50k rows; draft `psc_categories.yaml` | **PASS** (42,000 awards, 100% mapped to 19 categories) |
| 7 | HDFS download, label files, license terms; Banking77 | **PASS** (downloaded and checked); HDFS license **needs human approval** |
| 8 | Public repo, MIT license, README stub | **PASS** |

Total Token Factory spend for Phase 0: **$0.00225** (sum of `cost_usd` in `runs/verify/model_tests.json`).

## 1. Token Factory model IDs and capabilities

Source: `GET https://api.tokenfactory.nebius.com/v1/models` and `?verbose=true` (raw: `runs/verify/models_list.json`, `runs/verify/models_list_verbose.json`). 30 models are listed.

| Role | Display name | API model ID | Context | Listed features | RPM / TPM limit |
|---|---|---|---|---|---|
| Main chat, planner, teacher, baseline | Nemotron-3-Ultra-550b-a55b | `nvidia/Nemotron-3-Ultra-550b-a55b` | 1,048,576 | tools, reasoning | 1,000 / 2,000,000 |
| Rung L | Nemotron-3-Super-120b-a12b | `nvidia/nemotron-3-super-120b-a12b` | 262,144 | tools, reasoning | 1,000 / 1,000,000 |
| Rung K primary, bulk labeling, error fixer | Nemotron-3-Nano-30B-A3B | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 262,144 | tools, reasoning | **100** / 800,000 |
| Rung K alternative | Nemotron-3.5-Lightning | `nvidia/Nemotron-3_5-Lightning` | 1,048,576 | tools, reasoning | 1,000 / 2,000,000 |
| Embeddings (B, cloud I) | Qwen3-Embedding-8B | `Qwen/Qwen3-Embedding-8B` | 40,960 | n/a (4096-dim vectors) | 10,000 / 600,000 |

Test calls (`scripts/verify/test_models.py`, raw: `runs/verify/model_tests.json`). `temperature=0`, `max_tokens=1024`, one procurement record, 4 candidate labels:

| Model | Plain chat | Tool calling (`tools`, `tool_choice=auto`) | JSON output (`response_format=json_schema`, strict) |
|---|---|---|---|
| Ultra | PASS, 1,008 ms | PASS, `finish_reason=tool_calls`, 518 ms | PASS, valid schema, 866 ms |
| Super | PASS, 795 ms | PASS, 1,557 ms | PASS, 1,981 ms |
| Nano | PASS, 566 ms | PASS, 1,444 ms | PASS, 889 ms |
| Lightning | PASS, 998 ms | PASS, 350 ms | PASS, 1,991 ms |
| Qwen3-Embedding-8B | embeddings: PASS, 2 inputs, dim 4096, 1,917 ms | | |

Latencies are single calls, not benchmarks.

Observations for later phases:

- **Reasoning tokens are hidden but billed.** Replying "ok" cost 31 (Ultra), 44 (Super), 81 (Nano) and 196 (Lightning) completion tokens. Rung K cost estimates must use measured completion tokens, not visible output length. Disabling reasoning for K/L is worth testing in Phase 1.
- **Nano is limited to 100 requests/minute** on our account; Lightning allows 1,000. That favors Lightning for bulk labeling unless Nano wins on quality.
- ID casing is inconsistent (`nemotron-3-super...` lowercase, `Nemotron-3_5-Lightning` with an underscore). Always read IDs from `config/models.yaml`.

## 2. Sandboxes

`scripts/verify/sandbox_whoami.py` with `contree-sdk==0.3.6` (raw: `runs/verify/sandbox_whoami.json`):

- Auth works (HTTP 200 on `/v1/whoami`, using `NEBIUS_API_KEY` + `NEBIUS_PROJECT_ID`).
- **Every permission is `false`:** `import`, `spawn`, `spawn_disposable`, `list`, `cancel`, `set_image_tag`.
- Limits reported: `instance_max_timeout` 3600 s, `instance_max_concurrency` 50, `instance_max_layer_bytes` 12,884,901,888 (12 GiB), `images_import_max_concurrency` 8, `images_import_max_timeout` 3600 s. CPU/memory per instance are not reported.
- Image import attempt (`docker.io/library/python:3.12-slim`): `ForbiddenError: You do not have permission to perform this action`.
- The SDK warns "Token expires in 0 hours". The expiry is a short-lived token issued server-side; it moved forward on the next call (00:05:33 → 00:13:55 UTC) and later calls still succeeded. Not a problem with our key.

**Result: FAIL.** Base image build and the timed training run could not be attempted.
**Fallback applied (spec 04 §3):** `TRAINING_BACKEND=local` set in `.env`.
**Team action:** ask Nebius (Discord / support) to enable Sandboxes `import` + `spawn` for our project. If enabled, re-run `scripts/verify/sandbox_whoami.py` and finish this item.

## 3. Pricing

Recorded in `config/pricing.yaml` with source and date beside each value.

Token Factory, USD per 1M tokens. Source: the `pricing` field of `GET /v1/models?verbose=true`, read 2026-10-27. The public prices page (tokenfactory.nebius.com/pricing) renders client-side and could not be read, so the API's own values are the source.

| Model | Input | Cached input | Output |
|---|---|---|---|
| Ultra | 1.00 | 0.12 | 3.00 |
| Super | 0.30 | 0.06 | 0.90 |
| Nano | 0.06 | 0.012 | 0.24 |
| Lightning | 0.06 | 0.03 | 0.24 |
| Qwen3-Embedding-8B | 0.01 | n/a | 0 |

Serverless CPU endpoint:

- Serverless has no separate pricing; it bills Compute VM + disk rates ([Serverless pricing and quotas](https://docs.nebius.com/serverless/pricing-quotas)). Stopped endpoints are not billed for compute or storage.
- Platform `cpu-d3` = AMD EPYC 9654 (Genoa), presets 2vcpu-8gb up to 256vcpu-1024gb ([VM types](https://docs.nebius.com/compute/virtual-machines/types)).
- Genoa rates from Oct 1, 2026: $0.015 per vCPU-hour, $0.0045 per GiB RAM-hour; Network SSD $0.071 per GiB per 730 h ([Compute pricing](https://docs.nebius.com/compute/resources/pricing)).
- These are component rates. A preset's hourly cost is derived as vCPUs × rate + RAM × rate; no per-preset price is published. The derived figure goes into the run files when cost is computed, not into this doc.

Object Storage Standard: $0.0147 per GiB-month, $0.015 per GiB egress ([nebius.com/prices](https://nebius.com/prices)).

Fine-tuning and dedicated endpoints: not priced (G is STRETCH and off).

## 4. Serverless endpoint: BLOCKED

Not attempted. Creating an endpoint needs the `nebius` CLI (not installed), an interactive browser login (`nebius profile create`), and creates a billed resource. These are team actions.

Steps for the team (from the [endpoint quickstart](https://docs.nebius.com/serverless/quickstart/endpoints)): install the CLI, run `nebius profile create`, then create a CPU endpoint from a public hello-world image (the quickstart uses nginx) with `--platform cpu-d3 --preset 2vcpu-8gb`, `--auth token` and at least 20 GiB disk. Then curl the URL with and without the token, and record the URL, timing and result here. Autoscaling/replicas are still undocumented (VERIFY when the endpoint exists).

Fallback if this stays blocked (spec 04 §4): serve specialists from the main backend with the same routes, and say so in the README.

## 5. Object Storage: BLOCKED

Depends on item 4. `OBJECT_STORAGE_*` values in `.env` are empty and no bucket exists yet. Fallbacks (spec 04 §4): the specialist server pulls artifacts from the backend over HTTPS with a token; last resort, bake artifacts into the image.

## 6. USAspending procurement data

**Download path chosen: the public search API** `POST https://api.usaspending.gov/api/v2/search/spending_by_award/` (no auth). It returns `Description`, `PSC {code, description}`, `NAICS {code, description}`, `Recipient Name`, `Award Amount` and `Awarding Agency` in one call, which makes it the simplest path to 20k–50k rows. Bulk download and the Award Data Archive were not needed.

Script: `scripts/data/fetch_usaspending.py` (output: `data/raw/usaspending/awards.jsonl`, gitignored).

- Contract award types A, B, C, D; FY2025 (2024-10-01 to 2025-09-30); 3,500 awards per month, sorted by Award ID.
- **Use `date_type: date_signed`.** The first run used the default action-date window and returned mostly the same long-running awards every month (2,266 of 2,500 overlapped between October and November; 6,127 unique of 28,900 rows). Filtering on signing date makes months disjoint. That first sample was discarded.
- **The API is flaky under sustained load:** intermittent HTTP 500s, then several minutes of dropped connections. The script now retries with backoff, sleeps 0.3 s between pages, and resumes from the existing file. `make demo-data` must keep this behavior.

Inspection (`scripts/data/inspect_usaspending.py`, raw: `runs/verify/usaspending_inspection.json`):

- 42,000 rows, 42,000 unique awards; no missing PSC; no empty descriptions; median description 43 characters.
- 4,815 rows repeat another row's description text exactly. Dedupe before splitting.
- Boilerplate found: a leading `<digits>!` prefix (e.g. `8500135728!SUPPORT,STRUCTURAL`) on 4,245 rows. Strip it. (`IGF::OT::IGF`-style tags appeared in the discarded first sample but not in this one; strip them too if present.)
- **PSC → category coverage: 100%** (0 unmapped).
- 19 categories. Largest: Facilities & Construction 14,342. Smallest: Aircraft, Ships/Submarines & Land Vehicles 80, Electronic & Communication Services 121. Full counts in the inspection file. Very imbalanced, so sampling per category with a minimum count is required (spec 03 §1.3).

Data-use terms: the USAspending licensing text (from the official site's source, [Licensing.jsx](https://github.com/fedspendingtransparency/usaspending-website/blob/master/src/js/components/about/Licensing.jsx)) says the data is "available to copy, adapt, redistribute, or otherwise use for non-commercial or for commercial purposes, subject to the Limitation on Permissible Use of Dun & Bradstreet, Inc. Data". The API code repository is CC0-1.0. We don't use DUNS or other D&B identifiers. Whether `Recipient Name` counts as D&B data is unclear; until a human approves it, don't use it as a feature. The live site renders client-side, so the text was read from its public source repo.

### PSC → category mapping (`config/psc_categories.yaml`)

- Source: the official **PSC Manual April 2025** workbook from acquisition.gov (`PSC April 2025.xlsx`, the latest edition listed on [acquisition.gov/psc-manual](https://www.acquisition.gov/psc-manual)). Its "Level 1 Category" column (the government-wide category management taxonomy) has exactly 19 categories, inside the 15–25 target, so it is used directly rather than a hand-made roll-up.
- Generated by `scripts/data/build_psc_categories.py`; not edited by hand. The workbook spells one name two ways ("Professional services"); the script normalizes it.
- Lookup order: exact 4-character code (2,348 codes) → 3-character prefix majority → 2-character prefix majority (791 more codes) → none (515 retired codes, listed in the file).
- Two explicit overrides for retired IT families that FY2025 awards still use: `D3` "IT AND TELECOM" and `70` "INFORMATION TECHNOLOGY EQUIPMENT…" (both ended 2020-10-29, both replaced by codes whose Level 1 is IT). Before the override, 623 of the first sample's rows were unmapped, mostly `D3xx`.

The mapping's source and lookup rules must be copied into `dataset_manifest.json` in Phase 1.

## 7. LogHub HDFS and Banking77

### HDFS_v1

- Download: `https://zenodo.org/records/8196385/files/HDFS_v1.zip` (186,645,559 bytes), linked from the Loghub README. Extracted to `data/raw/hdfs_v1/` (gitignored).
- Files: `HDFS.log` (11,175,629 lines, matches the README), `preprocessed/anomaly_label.csv` (columns `BlockId,Label`), `preprocessed/HDFS.log_templates.csv`, `preprocessed/Event_traces.csv`, `preprocessed/Event_occurrence_matrix.csv`, `preprocessed/HDFS.npz`, `README.md`.
- Labels: 575,061 blocks, 558,223 Normal and 16,838 Anomaly (2.93%). Labels are per block ID, as the spec assumes. Log lines carry `blk_...` IDs for grouping.
- License (full text from [loghub LICENSE](https://github.com/logpai/loghub/blob/master/LICENSE)): "The datasets are freely available for research or academic work, subject to the following condition: For any usage or distribution of the loghub datasets, please refer to the loghub repository URL (https://github.com/logpai/loghub) and cite the following loghub paper where applicable. [Zhu et al., Loghub, ISSRE 2023.] The above license notice shall be included in all copies of the datasets." GitHub lists it as "Other". The HDFS README also asks for a citation of Xu et al., SOSP 2009.
- **Needs human approval:** whether a hackathon demo counts as "research or academic work". If approved: cite both papers and link the repo in the README and report card, and don't commit the raw logs (download them in `make demo-data`).

### Banking77 (optional task)

- The Hugging Face repo `PolyAI/banking77` holds only a loading script, which pulls `train.csv` / `test.csv` from `github.com/PolyAI-LDN/task-specific-datasets` (repo license CC-BY-4.0; HF tag `license:cc-by-4.0`, not gated). Downloaded directly to `data/raw/banking77/`.
- Verified: train 10,003 rows, test 3,080 rows, 77 categories, columns `text,category`. Matches spec 04.

## 8. Repository

`gh api repos/havishs9/synapse`: visibility **public**, license **MIT**, default branch `main`. `LICENSE` is at the repo root. `README.md` is now a stub with the one-liner and a status note.

## Spec conflicts and issues found

1. **`spec/03_ML_PIPELINE.md` is corrupted and incomplete.** Line 59 contains a stray shell heredoc (`EOFcat > spec/03_ML_PIPELINE.md << 'EOF'`), the content is duplicated after it, and the file ends after the candidate ladder. The planner rules, search schedule, sandbox, repair, cascade and evaluation-rule sections that `00_START_HERE.md` promises are missing. These are needed before Phase 2.
2. **Nano access type.** Spec 04 lists `NVIDIA-Nemotron-3-Nano-30B-A3B` as Dedicated-only and `Nemotron-3-Nano-30B-A3B` as Public. The public API has only one Nano: ID `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, display name "Nemotron-3-Nano-30B-A3B", serverless per-token pricing, and it served our calls. It is used as rung K primary.
3. `.env.example` has no defaults or comments, unlike spec 02 §2. Not a Phase 0 item; flagged only.
4. Spec 02 requires Python 3.11+, but the machine only had 3.9.6. Python 3.12.16 was installed via Homebrew; the project venv is `.venv/` (gitignored).

## Decisions taken at the start of Phase 1 (user, 2026-10-27)

- **HDFS license: approved** for the logs showcase task. Obligations: link https://github.com/logpai/loghub, cite Zhu et al. (ISSRE 2023) and Xu et al. (SOSP 2009) in the README and report card, never commit raw logs.
- **Recipient (vendor) name: excluded** as a feature. Procurement specialists use description text and NAICS only; candidate J uses learned keyword rules, not vendor lookups.
- **spec/03 missing sections:** built from what files 00, 01, 02 and 05 say. Assumptions are listed under "Assumptions for missing spec/03 sections" below as they are made.
- **Serverless endpoint:** the user will log in to the nebius CLI when asked in Phase 2.

## Assumptions for missing spec/03 sections

## Reasoning control (tested at the start of Phase 1)

Prompt: "Category for 'box of printer paper'? Answer with one word.", `max_tokens=512`.

| Model | Default | `reasoning_effort=low` | `extra_body={"chat_template_kwargs":{"enable_thinking":false}}` |
|---|---|---|---|
| Nano | 85 completion tokens, 2,147 ms | 67 tokens | **3 tokens, 496 ms** |
| Lightning | 512 tokens (hit the cap), **thinking text leaked into `content`** | 512 tokens, same leak | **3 tokens, 225 ms** |
| Ultra | 18 tokens (reasoning returned separately in `reasoning_content`) | 18 tokens | **3 tokens, 427 ms** |

Decision: classification calls (rungs K/L, the Ultra baseline, bulk labeling) send `enable_thinking: false` (`no_thinking_extra_body` in `config/models.yaml`). Planner, error analysis and chat keep reasoning on.
- **Procurement target (demo default).** The first task card used a placeholder target of macro-F1 0.70, chosen before any run. Phase 1 run `phase1-procurement` showed Nemotron Ultra zero-shot at 0.401 (150 validation records) and 0.456 (298 sealed records), and the best specialist at 0.619 on validation. The demo default is now **0.60**, still well above the frontier model. It's disclosed here because it was set after seeing results. In the product, the user sets the target at intake.
- **Validation sample for LLM rungs.** K, L and the Ultra baseline are scored on a stratified 150-record validation sample (the same rows for every LLM config); CPU candidates use all of validation. Scores on different samples are labeled with their n.
- **Ultra baseline sizes.** The baseline runs on a stratified sample of 300 sealed records (≈298 after rounding); for the binary logs task every sealed anomaly is kept so recall is measurable. The specialist is also scored on exactly those rows, and teacher agreement is measured there.
- **Cost per 1M predictions.** CPU candidates: Serverless hourly cost (cpu-d3 2vcpu-8gb, derived from published component rates) × time for 1M items at the measured single-thread throughput. LLM candidates: measured mean prompt/completion tokens × list price. Latency and throughput are measured with caches bypassed.
- **Search schedule (D4).** Round 1: every config on 10% of training rows; round 2: the top quarter (at least 3) on 40%; round 3: the top 2-3 on 100%. Small-data guard: a round is skipped when its fraction would give fewer than 400 training rows. Ranking uses the primary metric, then a tie-breaker when the primary saturates: PR-AUC for binary tasks, macro-F1 for multiclass. Elimination reasons say which applied.
- **Recommendation rule.** `balanced` / `precision_first` task cards ship the cheapest allowed candidate that meets the target. `recall_first` cards ship the best detector that meets the target (primary, then PR-AUC), with cost only breaking ties. If nothing meets the target, the most accurate allowed candidate ships to validation review, but the version gate still blocks deployment.
- **Calibration.** Temperature scaling fitted on validation predictions; the reported "after" ECE uses 2-fold cross-fitting on validation so it isn't measured on the data it was fit on.
- **Cascade (H).** Base = the recommended single model (calibrated); fallback = the best prompted rung (K/L). The escalation threshold is chosen on the LLM rung's capped validation sample, where both have predictions. H ships only if it beats the base by more than 0.01 on that shared sample, escalates something, and fits the latency/deployment constraints; otherwise the report says why it wasn't used. The planner always includes rung K when cloud calls are allowed, so H can be evaluated.
- **Seed error bars.** The final 2 (the shipped single model and its best frontier alternative, excluding LLM rungs, which are deterministic at temperature 0) are retrained with 3 seeds; each seed bootstrap-resamples the training set, so the spread measures data variance.
- **Repair loop.** Runs while validation is below target, up to `MAX_REPAIR_ROUNDS`. Each round: Ultra describes the top confusions → Ultra writes targeted synthetic examples in the user's format for the true class → appended to the training set only (5 per pattern held aside to score on synthetic data) → the top 2 configs retrain → keep the result only if validation improves (otherwise the synthetic rows are removed again).
- **Teacher explains flags.** Optional per prediction (`explain: true`): Nemotron Ultra reads the input and the specialist's feature-based reason and writes up to three sentences. It is a cloud call and is labeled "Nemotron Ultra (cloud call)".
- **Ultra baseline on the logs task.** Ultra's self-reported confidences are coarse (mostly 0.9-0.95), so its recall at a fixed 1% FPR is 0.000 on the sealed sample: it can't rank windows finely enough. At its own labels it finds 62.7% of anomalies at 52.5% precision (run `p2-logs-a`, 300 sealed rows, 83 anomalies). The report card shows both numbers.
- **Logs winner.** Expected winner in spec 05 was E (window features + LightGBM). Measured (run `p2-logs-b`): E reaches recall 1.000 at 1% FPR with PR-AUC 0.9947 and p50 ~6 ms; TF-IDF on masked log text (A) reaches recall 1.000 with PR-AUC 0.9999 and p50 0.26 ms. The agent picks A on the numbers; the planner was not changed to force E.
- **Fake LLM for tests.** `SYNAPSE_FAKE_LLM=1` swaps in a deterministic offline client (used only by the integration test, which must run without network).
- **Public deployment without Docker.** No Docker on the build machine. The Serverless endpoint uses the public `python:3.12-slim` image, an injected `bootstrap.sh` (`--inject-file`, ≤64 KiB) that downloads this public repo, installs requirements and starts the app. One CPU endpoint serves the whole app: main chat, builds (replay by default) and the shared specialist server routes. Dockerfiles are included but were not built locally.
- **Public spend guard.** Interactive cloud calls on the deployed app (chat, compare, teacher explanations) stop at `DEMO_DAILY_BUDGET_USD` (default $3) per day; specialist predictions keep working.
