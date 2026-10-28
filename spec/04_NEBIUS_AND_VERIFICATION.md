# 04 Nebius stack and verification status

## 1. Model roles (`config/models.yaml`)

Display names below are from the Token Factory catalog (CONFIRMED 2026-10-27). **API model ID strings may differ from display names: fill `api_id` from the list-models endpoint (`GET /v1/models`) before coding (VERIFY).**

~~~yaml
# config/models.yaml  (api_id values: VERIFY via GET /v1/models)
roles:
  main_chat_planner_teacher_baseline:   # planner, clarifying questions, synthetic data, error analysis, baseline, top of cascade
    display_name: Nemotron-3-Ultra-550b-a55b
    api_id: VERIFY
  ladder_K_primary:                     # prompted rung K, bulk labeling
    display_name: Nemotron-3-Nano-30B-A3B
    api_id: VERIFY
  ladder_K_alternative:                 # test against Nano; keep the cheaper/faster one
    display_name: Nemotron-3.5-Lightning
    api_id: VERIFY
  ladder_L:                             # prompted rung L
    display_name: Nemotron-3-Super-120b-a12b
    api_id: VERIFY
  trainer_error_fixer:                  # reads crash logs, proposes patches
    display_name: Nemotron-3-Nano-30B-A3B
    api_id: VERIFY
  embeddings:                           # candidates B and cloud I
    display_name: Qwen3-Embedding-8B
    api_id: VERIFY
  local_embeddings:                     # candidate C and offline I (runs in our process, not Token Factory)
    model: sentence-transformers MiniLM-class model
~~~

Access types (CONFIRMED from the catalog):

| Model | Parameters | Context | Access | Use |
|---|---|---|---|---|
| Nemotron-3-Ultra-550b-a55b | not listed | 1,024K | Public | Planner, teacher, error analysis, baseline |
| Nemotron-3-Super-120b-a12b | 120B | 256K | Public + Dedicated | Rung L |
| Nemotron-3-Nano-30B-A3B | 30B | 262K | Public | Rung K, bulk labeling, error fixer |
| Nemotron-3.5-Lightning | 30B | 1,024K | Public + Dedicated | Rung K alternative |
| Qwen3-Embedding-8B | 8B | 41K | Public | Embeddings (B, I) |
| All other Nemotron variants (Llama-3.1-Nemotron-Ultra-253B, `-serverless` variants, NVIDIA-Nemotron-3-Nano-30B-A3B, Nemotron-3-Nano-Omni) and other embedding models (bge-en-icl, bge-multilingual-gemma2, e5-mistral-7b-instruct) | | | Dedicated only | Skip (needs a paid dedicated endpoint) |

"Public" means serverless pay-per-token access. Do not use anything Dedicated-only without explicit opt-in.

## 2. Token Factory API

- OpenAI-compatible, base URL `https://api.tokenfactory.nebius.com/v1/`, auth via `NEBIUS_API_KEY` (CONFIRMED, quickstart).
- Documented features: chat completions, function calling and tools, structured output / JSON, embeddings, rerank, list models, files, cached tokens, observability (CONFIRMED, docs index). Whether each chosen Nemotron model supports tool calling and JSON mode: VERIFY with a test call per model.
- **Fine-tuning:** no Nemotron model is fine-tunable (CONFIRMED). The docs list DeepSeek, Gemma 4, gpt-oss, Qwen (Qwen3, 3.5, 3.6, 2.5) and Llama (3.1, 3.2, 3.3) base models; the catalog also shows NVIDIA-quantized NVFP4 GLM-4.7, MiniMax-M2.5/M2.7 and Qwen3.5-397B as fine-tunable. Fine-tuned models deploy only via dedicated endpoints (CONFIRMED). Do not count the NVFP4 third-party models toward the "NVIDIA open source model" rule; Nemotron covers it.

## 3. Sandboxes (training)

CONFIRMED from the Sandboxes docs (Beta):

- Secure code execution with VM-level isolation, Git-like branching (fork from any checkpoint, run alternatives in parallel, roll back instantly), OCI image support.
- Python SDK `contree-sdk` (quickstart pins 0.3.6), `from contree_sdk import Contree`, `client = Contree()`. Needs `NEBIUS_API_KEY` and `NEBIUS_PROJECT_ID` in the environment (`NEBIUS_AI_PROJECT` does not replace it). REST base `https://api.tokenfactory.nebius.com/sandboxes`, with `Authorization: Bearer` and `Project: <project id>` headers. CLI: `contree-cli`.
- Limits: **50 simultaneous operations during Beta**; checkpoint images retained 180 days; recorded stdout/stderr 1 MiB per stream by default, 10 MiB max; execution timeout is account-specific (read it from `GET /v1/whoami` limits); networking on by default and can be disabled.
- Operation output streams over SSE; completed operations expose resource fields and duration.
- Use image UUIDs, not tags, as bases. Build a reusable base image (setup commands, OCI import, or the supported Dockerfile subset).
- GPUs are not mentioned anywhere: **assume CPU only.**

VERIFY on day one: `whoami` limits (timeout, CPU/memory), base image with scikit-learn + LightGBM builds, one candidate trains and its metrics stream back, and time it. If any of this fails, switch `TRAINING_BACKEND=local` and record it.

## 4. Specialist hosting: Nebius Serverless endpoint (DECISION D3)

CONFIRMED from the Serverless docs:

- Endpoints host a container at a managed HTTPS URL; jobs run to completion with no URL.
- Custom container image with `--container-command` and `--container-port`; **CPU-only platforms supported** (omit GPUs; disk at least 20 GiB; preemptible VMs not available for CPU).
- Auth off by default; use `--auth token` and send `Authorization: Bearer <token>`.
- Limits: 120 Mbps combined traffic and 300 new connections per second per endpoint.
- **Container settings can't change after creation.** Changing them means delete and recreate (new URL). Updating the image under the same tag and restarting keeps the URL.
- Billing: per-second on compute; a stopped endpoint isn't billed for compute or storage.
- Autoscaling/replicas: not documented (VERIFY).

Design:

- **Every specialist gets its own API** (DECISION D3): its own URL path and its own API key. All of them are served by **one shared specialist server** (FastAPI) on **one** CPU Serverless endpoint, which loads every version's artifacts (model file, threshold/calibration, feature/windowing config) from storage. Why one server: endpoint settings can't change after creation, so one endpoint per specialist would mean a new URL and a new always-on bill for every specialist and version.
- Public routes (each requires that specialist's key as `Authorization: Bearer <key>`):
  - `POST /v1/specialists/{specialist_id}/predict` and `/predict_batch` (live version)
  - `POST /v1/specialists/{specialist_id}/v{n}/predict` (pinned version)
  - `GET /v1/specialists/{specialist_id}/versions`
  - `GET /health` (no key)
- A key works only for its own specialist; requests with another specialist's key get 403. Keys are stored hashed (with `API_KEY_PEPPER`), shown once, and can be regenerated or revoked.
- Admin routes (load version, set live, create/revoke keys) require `SPECIALIST_ADMIN_TOKEN` and are called only by the backend.
- Because our server enforces per-specialist keys, the Serverless endpoint's own token auth stays **off** (otherwise callers would need two tokens). VERIFY the endpoint is reachable without Nebius auth.
- New versions and rollbacks change which version is `live`; no endpoint recreation.
- **Artifact storage:** Nebius Object Storage (VERIFY S3 compatibility, credentials and that the endpoint can reach it). Fallback: the server pulls artifacts from the main backend over HTTPS with a token. Last resort: bake artifacts into the image and restart under the same tag.
- **Fallback if Serverless setup fails:** serve specialists from the main backend process with the same routes, and say so honestly in the README.
- The main app is deployed to a public URL (Nebius if possible; otherwise any host, while all model inference still runs on Nebius).

## 5. Pricing (`config/pricing.yaml`): all VERIFY

Per-token prices for Ultra, Super, Nano, Lightning and Qwen3-Embedding-8B; Serverless CPU endpoint cost per hour for the chosen preset; fine-tuning job and dedicated endpoint prices (only if G is attempted). Record the source page and date beside each value.

## 6. Verification status

| Item | Status | Source / note |
|---|---|---|
| Token Factory base URL and OpenAI SDK compatibility | CONFIRMED | https://docs.tokenfactory.nebius.com/quickstart |
| Public Nemotron models and embedding model | CONFIRMED (display names) | Token Factory catalog, 2026-10-27 |
| Exact API model IDs | VERIFY | `GET /v1/models` |
| Tool calling + JSON output per chosen model | VERIFY | Test call per model |
| Nemotron not fine-tunable; fine-tuned models deploy on dedicated only | CONFIRMED | https://docs.tokenfactory.nebius.com/post-training/models.md |
| Sandboxes exist; SDK name; env vars; Beta limits | CONFIRMED | https://docs.tokenfactory.nebius.com/sandboxes/overview |
| Sandbox timeout, CPU/memory; training actually works | VERIFY | `whoami` + one timed run |
| Serverless custom CPU container, token auth, HTTPS URL, immutability | CONFIRMED | https://docs.nebius.com/serverless/endpoints/manage |
| Serverless autoscaling | VERIFY | Not documented |
| Object Storage access from the endpoint | VERIFY | Fallbacks in section 4 |
| All prices | VERIFY | Token Factory prices page, Nebius pricing |
| USAspending fields (`award_description`, `product_or_service_code`, `product_or_service_co_desc`, `naics`) | CONFIRMED | usaspending-api FPDS transaction model |
| PSC code structure | CONFIRMED | https://api.usaspending.gov/api/v2/references/glossary/ |
| USAspending download method and data-use terms | VERIFY | Pick bulk download / archive / API; record terms |
| PSC → category mapping | VERIFY | Official PSC manual |
| Banking77: CC-BY-4.0, 10,003 train / 3,080 test, 77 intents | CONFIRMED | https://huggingface.co/datasets/PolyAI/banking77 |
| LogHub HDFS: "freely available for research or academic work", license listed as "other" | VERIFY exact LICENSE terms; cite the Loghub paper | https://github.com/logpai/loghub |
| Prompt-injection dataset (STRETCH task) | VERIFY license | Only if task 4 is attempted |
| Hackathon rules: deadline, MIT allowed, video under 3 min, demo URL, feedback | CONFIRMED | https://nebiusglobalaihackathon.devpost.com |
