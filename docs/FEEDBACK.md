# Feedback on Nebius and NVIDIA tools

From building Synapse, 2026-10-27 to 2026-10-30. Every point below happened to us; details, dates and trace IDs
are in `docs/VERIFICATION.md`.

## Token Factory

**What worked well**

- **OpenAI compatibility is real.** The OpenAI Python SDK with a base URL change covered chat, streaming,
  structured output, tool calling and embeddings for all five models we used. No adapter code.
- **`GET /v1/models?verbose=true` is excellent.** One call returns IDs, context lengths, rate limits and per-token
  prices. We generated `config/models.yaml` and `config/pricing.yaml` from it, so every cost in the app traces to
  the API's own numbers. Please keep this.
- **Structured output (`json_schema`, strict) passed on Ultra, Super, Nano and Lightning** in our first tests
  (13/13 calls). It's what lets a planner, an intake step and prompted classifiers return validated JSON.
- **Per-call usage, including cached tokens,** made exact cost accounting possible.
- **Turning reasoning off with `chat_template_kwargs.enable_thinking=false`** cut a one-word classification on
  Nano from 85 to 3 completion tokens (2.1 s to 0.5 s). That made prompted Nemotron affordable as a cascade stage.

**What slowed us down**

- **Hidden reasoning tokens are billed but not obvious.** Replying "ok" cost 31 (Ultra) to 196 (Lightning)
  completion tokens. The docs should say clearly that reasoning is on by default, that it's billed as output, and
  how to turn it off per model.
- **Lightning writes its thinking into `content`** with reasoning on (it hit our 512-token cap on a one-word
  answer); Ultra returns it separately in `reasoning_content`. The same flag fixed both, but the inconsistency
  cost us a debugging session.
- **Model ID casing is inconsistent:** `nvidia/nemotron-3-super-120b-a12b` (lowercase), `nvidia/Nemotron-3_5-Lightning`
  (underscore), `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (vendor prefix twice). Easy to mistype from the catalog's
  display names.
- **Nano's rate limit is 100 requests/minute** on our account, against 1,000 for Ultra and Lightning. Our
  procurement improve run's final exam took 12 minutes mostly waiting on it (1,082 calls). A higher default, or a
  documented way to request one, would help agent workloads that fan out.
- **The pricing page renders client-side** and couldn't be read by our tooling; we used the API's prices instead.
- **The catalog lists two Nano entries** (one marked Dedicated-only) while the API serves one ID under the public
  display name. We weren't sure which we were billed for until we checked the verbose models list.

## Token Factory Sandboxes

- **Our account had no permissions:** `/v1/whoami` returned every permission `false` (import, spawn, list,
  cancel), and an image import failed with `ForbiddenError`. The SDK and auth worked, so it's an account flag,
  but nothing in the console or docs says how to request it. We fell back to local parallel training.
- `whoami` reports limits (timeout 3600 s, concurrency 50, 12 GiB layers) but not CPU or memory per instance,
  which is what we needed to size candidate training.
- The SDK warns "Token expires in 0 hours" on every call while the token keeps working. Harmless, but alarming.

## Nebius AI Cloud

**What worked well**

- **Serverless endpoints run a custom CPU container at a managed HTTPS URL with auth off,** which let our own server
  enforce per-specialist API keys behind one URL. `/health` answered 62 s after create.
- **Stop and start keep the URL,** so we could stop billing between work sessions.
- **The CLI covers everything** (endpoints, buckets, registry, service accounts, AI Jobs), and `--dry-run` on
  `ai endpoint create` caught our mistakes before we paid for them.
- **Object Storage is plain S3,** so boto3 worked with an endpoint URL and a region.

**What slowed us down**

- **Billing activation surfaced as `PermissionDenied`.** Before billing was active, `ai endpoint create --dry-run`
  failed with "you do not have permission to access the requested object"; the real cause (tenant
  `suspension_state: SUSPENDED`) was only visible through `iam tenant list`. A message that says "activate
  billing" would have saved us an evening.
- **No `ai endpoint update`.** Changing an environment variable means delete and recreate, which changes the URL.
  For a demo with a public URL that's a real constraint; we had to plan every setting before the one recreate.
- **No autoscaling or replica settings** in the CLI or the endpoint spec; we treat it as one fixed instance.
- **`--env` takes one `KEY=VALUE` per flag.** Our first script passed several comma-joined in one flag and
  silently set one variable. A warning on commas would help.
- **Object Storage default class:** our first upload failed with `QuotaLimitExceeded` because the tenant had no
  standard-class quota in eu-west2 (only enhanced throughput). Setting the bucket's default class fixed it; the
  error didn't point there.
- **`iam static-key issue` doesn't cover Object Storage;** S3 keys come from `iam v2 access-key create`, and the
  secret is read from `.status.secret` of `access-key get`. Found it on the AWS CLI docs page, not the IAM one.
- **Startup time:** our endpoint installs Python dependencies on boot (~10 minutes). A pre-built image in the
  Container Registry is the fix; a quickstart that shows build → push → endpoint end to end would help.

## NVIDIA Nemotron models

- **Ultra is a strong planner and teacher.** With a JSON schema it chose sensible candidate families per task and
  wrote clarifying questions tailored to each request. As a zero-shot classifier on our tasks it scored macro-F1
  0.456 (procurement, 19 categories) and 0.738 (Banking77, 77 intents) on sealed samples, which is exactly why a
  trained specialist plus Ultra as fallback is worth building.
- **Self-reported confidence is coarse:** Ultra's confidences cluster at 0.90 to 0.95, so it can't rank log windows
  at a 1% false-positive rate (recall 0.000 there, while its own labels catch 62.7% of anomalies). Calibrated
  scores or logprobs would make it usable as a detector.
- **Nano with 10 retrieved examples was the best prompted rung for procurement** (validation macro-F1 0.677) at
  a small fraction of Ultra's price. Its 100 RPM limit is the main thing holding it back as a cascade stage.
- **Qwen3-Embedding-8B + a small MLP was the strongest single model on Banking77** (validation 0.936) at $0.47 per
  1M predictions; as a cascade's second stage behind TF-IDF it costs $0.12 per 1M overall.
