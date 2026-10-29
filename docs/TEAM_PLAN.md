# Team plan: remaining work and Phase 3 (agreed 2026-10-28)

Two parallel tracks. **Raj** owns the backend platform: storage, login on the server side, the build queue and
workers, deployment of the API endpoint. **Havish** owns the product: every frontend feature, the product
API routes behind them, Vercel hosting, docs and the video. Each track can ship on its own; the contracts below
are the only meeting points.

Claude Code sessions: read this file, then work only on your own track's items.

## 0. Already done for both (2026-10-28)

- Replay recordings of all three tasks are committed in `artifacts/demo/runs/` (`p2b-support-c`,
  `p2b-procurement-d`, `p2b-logs-d`; no raw HDFS lines; saved paths made relative), and the specialists in
  `artifacts/demo/specialists/`. `make replay` serves them with no dataset download.
- The live Nebius endpoint serves the three specialists: https://port8000-b3arav7mmzek3n6.tunnel.applications.eu-west2.nebius.cloud

## 1. Contracts (agree before coding; change only together)

**Builds list** (Raj builds it; Havish codes the sidebar against it from day 1). `GET /api/builds` returns the
caller's builds, newest first:

```json
[{"run_id": "p2b-support-c", "task_id": "support_tickets", "task_name": "Support Ticket Router",
  "status": "queued | running | done | failed | cancelled", "stage": "train", "round": 2, "n_rounds": 3,
  "spend_usd": 0.31, "budget_usd": 5.0, "created_at": 1793205797.9, "updated_at": 1793206344.9,
  "message": "Run complete", "specialist_id": "support-ticket-router", "version": 1}]
```

- `POST /api/builds` takes `"replay": true` to play a demo task's recorded run instead of building (the public
  endpoint runs in live mode now, so the video and "Try an example" should send it).
- `POST /api/builds` returns `{"run_id", "status": "queued"}` with the database configured (the queue), or
  `"status": "running"` without it (local, starts at once). 429 when the user hit `MAX_BUILDS_PER_USER_PER_DAY`.
- `POST /api/builds/{run_id}/cancel`, `POST /api/builds/{run_id}/retry`: 200 with the build object.
  **Landed (Raj, queue):** cancel on a queued build → `cancelled` at once; on a running one the message becomes
  "Cancelling after the current step" and the worker stops after its current search round or stage (409 if it
  already ended). Retry (failed/cancelled only, else 409) returns the **new** build with a new `run_id`. Both are
  501 without the database. Builds list statuses: `queued | running | done | failed | cancelled`; `stage` is
  `null` while a worker is starting.
- Progress stays on the existing stream `GET /api/runs/{run_id}/events` (same event schema as spec file 02).
  It must keep working after a reconnect: it replays from the first event, and `?after=<n>` skips the first n.
- Raj ships a day-1 stub of `GET /api/builds` that reads `run_state.json` files, so the shape is real at once.
  **Done** (`backend/builds/api.py`): also returns `deployed` (true/false once the build ends: whether its version
  passed the gate) and `kind` (`build | improve`). Until the queue lands, cancel/retry return 501, a `running`
  build with no event for 20 min shows as `failed`, and every run in `RUNS_DIR` is listed (no users yet).

**Auth.** The frontend signs in with Supabase Auth (`@supabase/supabase-js`) and sends
`Authorization: Bearer <Supabase access token>` on every `/api/*` call. The backend verifies it. Until Raj's
verification lands, the backend accepts calls without a token (local dev, replay), so login UI never blocks.
Specialist prediction routes keep their own per-specialist API keys (unchanged).
**Landed (Raj, 2026-10-28, `backend/auth.py`):**
- A token that is sent is always verified (project signing keys, ES256). `AUTH_REQUIRED=false` (default) lets
  calls without a token through as anonymous; the public deployment switches it to `true` once the login screens ship.
- The SSE stream (`GET /api/runs/{id}/events`) also takes the token as `?access_token=<token>`, because the
  browser's `EventSource` can't send headers. Other calls: use the header.
- What a user sees: their own specialists and builds plus the public demo ones (no owner); someone else's
  specialist or run is a 404. `GET /api/specialists/{id}` adds `"owned": true|false`, and `keys`/`has_key`
  cover only the caller's own keys.
- Keys: on a demo specialist every signed-in user has their own key; "Regenerate" revokes only the caller's
  earlier key. Rollback (and later deploy/improve) needs the owner: 403 on demo specialists when sign-in is required.
- Havish's routes in `backend/routes/product.py` use the same helpers: `user: User | None = Depends(current_user)`,
  then `require_view(spec, user)` / `require_edit(spec, user)` and `uid(user)` (all in `backend/auth.py`).

**Frontend → API origin.** The frontend reads `VITE_API_BASE_URL` (empty = same origin, as today). The backend
allows the origins in `CORS_ORIGINS` (comma-separated).

**Files, to avoid merge conflicts.**

| Owner | Files |
|---|---|
| Raj | `backend/storage/` (new), `backend/auth.py` (new), `backend/builds/` (new: queue, dispatcher, worker entry), `backend/versions/registry.py`, `backend/orchestrator.py`, `backend/agents/`, `backend/sandbox/`, `backend/llm_client.py`, `deploy/`, `supabase/` (migrations), `Dockerfile*` |
| Havish | `frontend/**`, `backend/routes/product.py` (new APIRouter: intake, compare, corrections, improve), `vercel.json`, `docs/DESIGN.md`, `docs/DEVPOST.md`, `docs/VIDEO_SCRIPT.md`, `docs/FEEDBACK.md`, `README.md` |
| Shared, small edits only | `backend/main.py` (each side adds `include_router` lines), `backend/schemas/`, `docs/PROGRESS.md`, `config/*.yaml` |

Work on short-lived branches (`raj/<topic>`, `havish/<topic>`), open PRs to `main`, and rebase often.

## 2. Raj: backend platform

Order matters; each step is usable on its own.

1. **Supabase.** (**Done 2026-10-28**, see `docs/VERIFICATION.md` "Phase 3: Supabase".) Project, schema as SQL migrations in `supabase/migrations/`: `specialists`, `versions`,
   `api_keys` (hashes only), `builds`, `build_events`, all with `user_id` and row-level security. The registry
   (`backend/versions/registry.py`) reads and writes Postgres, with the current files kept as the local/replay
   fallback. JWT verification in `backend/auth.py`; every route checks ownership. Fixes: keys lost on endpoint
   restart; anyone can regenerate (revoke) a key on the public demo.
2. **Nebius Object Storage.** (**Done 2026-10-28**; the endpoint switches over at the step-4 redeploy.) Bucket, `backend/storage/`: bundles and run folders under
   `users/<user_id>/...`. The endpoint loads a specialist's bundle on first call and keeps recent ones in memory
   (LRU); it loads only bundles our pipeline wrote. Replaces the repo download at startup.
3. **Build queue and workers.** (**Done 2026-10-29**; see `docs/VERIFICATION.md` "Phase 3: build queue".) `builds` table as the queue (`FOR UPDATE SKIP LOCKED`), a dispatcher loop on the
   endpoint with caps (default 2 builds at once overall because of the Token Factory rate limit, 1 per user),
   one **Nebius AI Job** per build (`nebius ai job create`: run-to-completion container, 1 h to 168 h timeout,
   Object Storage volume). Worker heartbeats; a stale heartbeat marks the build failed. Cancel between rounds;
   retry button. Events written to `build_events`; the stream reads from there. VERIFY and record: job pricing,
   job start time, service-account permissions.
4. **Pre-built image** (**built 2026-10-29**: `Dockerfile`, `.github/workflows/image.yml` pushes `synapse:main` and
   `synapse:<sha>`; one-time step for Raj: `bash scripts/setup_registry_ci.sh`; then the endpoint is recreated with
   `make deploy`, which gives it a **new URL**) in Nebius Container Registry for the endpoint and the workers (startup is ~10 min today,
   mostly `pip install`). Fix `_reload_remote` (imports a missing `backend.serving.sync`). The running endpoint was created with `RUNS_DIR=./runs`; `deploy.sh` now sets `./artifacts/demo/runs`, so replay on the endpoint needs this redeploy.
5. **Budgets.** (**Builds part done 2026-10-29**: at enqueue, 429 when the caller's builds in the last 24 h reach
   `MAX_BUILDS_PER_USER_PER_DAY` or `USER_DAILY_BUILD_BUDGET_USD`, all builds today reach `GLOBAL_DAILY_BUILD_BUDGET_USD`,
   or all builds ever reach `TOKEN_FACTORY_TOTAL_BUDGET_USD`; callers without sign-in share one allowance. Still to do:
   chat/compare spend in the total, escalations.) Per-user training budget; cascade escalations on public predictions count against the daily
   demo guard.
6. **Data sourcing backend** (spec file 03 §1.1): uploads saved as the user's own dataset (Object Storage) →
   same dedupe / sealed split; unlabeled uploads get teacher labels from Nano; live Tavily + Hugging Face search
   with license check and format-match score; synthetic gap-filling reported separately. Havish builds the
   upload and approval UI against the routes Raj defines here (agree on them before step 6 starts).
7. Update spec file 02 (Supabase and Object Storage replace SQLite; AI Jobs replace Sandboxes) and
   `docs/VERIFICATION.md`.

## 3. Havish: product, frontend, hosting, demo

Works against the current API from day 1: `make replay` for recorded runs, or `make dev` for live builds.

1. **Phase 3 product features** (each = UI plus its route in `backend/routes/product.py`):
   clarifying questions → editable task card with plan-change lines (`lib/useIntake.ts`); compare mode with
   measured latency, cost and yearly projection (`PanelOverlays.tsx`); "Use via API" dialog with reveal-once key,
   regenerate, curl and Python snippets; v1 → v2 improvement flow: corrections, version gate, deploy or reject,
   rollback, version history (`PanelExtras.tsx`); agent lanes, tournament bracket, budget meter
   (`TrainingExtras.tsx`).
2. **Cascade display** (new in Phase 2b): show the split ("TF-IDF 76% / embeddings 24%") on the specialist panel
   and report card, and `answered_by` on each prediction.
3. **Builds sidebar** against the contract in §1 (works with Raj's day-1 stub): status, stage, round, spend;
   clicking reopens the training view; cancel and retry buttons.
4. **Login screens** with Supabase Auth (needs only the project URL and anon key from Raj), behind
   `VITE_AUTH_ENABLED` until Raj's backend verification lands.
5. **Vercel hosting**: project linked to the GitHub repo, `VITE_API_BASE_URL` = the Nebius endpoint URL,
   `CORS_ORIGINS` set on the endpoint (ask Raj to redeploy, or Raj adds it in the next deploy). Public demo URL.
6. **UI polish** against file 01 §2.11 with screenshots (light/dark, desktop/mobile); Phase 1 polish notes
   (button state after a build, cost format, "Ultra vs specialist" label); logs "Try an example" (we can't commit a
   raw HDFS window: let the user paste one, or show a template-built example clearly labeled as such).
7. **Docs and demo**: complete README, `docs/FEEDBACK.md`, `docs/DEVPOST.md`, `docs/VIDEO_SCRIPT.md`; record the
   3-minute video from replay on the public URL; frontend smoke test (file 05).

**Both, at the end:** acceptance criteria check (file 05 §5) and a full dry run of the demo.

## 4. Havish: getting started from a fresh clone

1. `git pull` (or clone https://github.com/havishs9/synapse).
2. `make setup` (Python 3.12, Node 20+; macOS: `brew install libomp`).
3. `.env` in the repo root (never commit it). Copy `.env.example`; values below.
4. `make test` (41 tests), then `make replay` and open http://127.0.0.1:8000. This shows all three recorded
   builds and lets you try the specialists. No data download needed.
5. Only for live builds on your machine: `make demo-data` (~10+ min, ~2.2 GB), then `make dev`.

Nothing else is needed from Raj's laptop. Optional: copying Raj's `data/cache/` (~270 MB of cached Nemotron and
embedding responses) makes specialist predictions that hit embeddings or Nano free and instant locally.

`.env` values for Havish:

| Variable | Needed for | Where it comes from |
|---|---|---|
| `NEBIUS_API_KEY`, `NEBIUS_BASE_URL`, `NEBIUS_PROJECT_ID` | chat, compare, predictions that escalate to embeddings or Nano, live builds | his own Token Factory key from Phase 0 works, but spends his account's credits; or Raj shares the team key over a secure channel |
| `API_KEY_PEPPER`, `SPECIALIST_ADMIN_TOKEN` | API keys locally | any random values for local dev; the deployed endpoint has its own (Raj) |
| `APP_MODE`, `TRAINING_BACKEND=local` | | defaults are fine; `make replay` sets replay itself |
| `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | Vercel and login (later) | endpoint URL; Supabase values from Raj (public, safe for the browser) |

## 5. Inputs and status (decisions by Raj, 2026-10-28)

**Raj's track**

| # | What | Status |
|---|---|---|
| R-a | Supabase project: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `SUPABASE_DB_URL` in `.env` | **Done (Raj)**: project `kcwqhcmvanweadzrpwsp` in us-west-2 (kept there for now; ~130-150 ms per query from eu-west2, reads are cached); session pooler URL; signing keys ES256, so `SUPABASE_JWT_SECRET` isn't needed. Schema applied with `make db-migrate`, demo specialists loaded with `make db-seed` |
| R-b | Login: **Google sign-in, open sign-up** | Decided. **To do (Raj)**: set up Google OAuth (steps below) |
| R-c | Object Storage bucket | **Done**: `synapse-artifacts-e04crhvwbc` (eu-west2, 50 GiB cap, endpoint `https://storage.eu-west2.nebius.cloud`) |
| R-d | Container Registry | **Done**: `registry-e04cjwm2bdv5k5b8hc` (`cr.eu-west2.nebius.cloud/e04cjwm2bdv5k5b8hc`; push/pull path VERIFY on first push) |
| R-d2 | Service account `synapse-backend` (editors group), its S3 access key and authorized key | **Done 2026-10-28 (Raj ran the script)**: `serviceaccount-e04vfj54jr4tvp1qz0`; S3 key and `NEBIUS_SA_CREDENTIALS_FILE` are in Raj's `.env`; keys expire 2026-12-27. Bucket uploads verified (the bucket's default storage class is ENHANCED_THROUGHPUT; standard has no quota in eu-west2) |
| R-e | Billed resources (AI Jobs, registry, bucket) | Approved |
| R-f | Limits and budgets | Decided: §6 and `.env.example` |
| R-g | `TAVILY_API_KEY` | In `.env` (Raj) |

**Google sign-in setup (Raj, ~10 min, browser):**
1. Google Cloud console → APIs & Services → OAuth consent screen: External, app name "Synapse", your email;
   publish it (In production), or every user must be added as a test user.
2. Credentials → Create credentials → OAuth client ID → Web application. Authorized redirect URI:
   `https://<project-ref>.supabase.co/auth/v1/callback`.
3. Supabase → Authentication → Providers → Google: paste the client ID and secret, enable.
4. Supabase → Authentication → URL Configuration: Site URL = the Vercel URL (Havish); add redirect URLs
   `http://localhost:5173/**`, `http://127.0.0.1:8000/**` and the Vercel URL.

**Havish's track**

| # | What | Who | Blocks |
|---|---|---|---|
| H-a | `.env` with a Token Factory key (see §4) | Havish / Raj | live predictions, compare, chat |
| H-b | Vercel account linked to the GitHub repo | Havish | hosting |
| H-c | `frontend/.env.local` (template `frontend/.env.example`): `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | from Raj after R-a | login screens only |
| H-d | `CORS_ORIGINS` with the Vercel URL set on the endpoint | Raj redeploys | public URL calling the API |
| H-e | Exact example record for compare mode in the video (`TEAM_INPUTS.md`) | Havish, decision | video |
| H-f | YouTube channel for the public video | Havish | submission |

## 6. Budgets (credits: Token Factory $25, Nebius AI Cloud $25, Tavily $25)

Budgets are enforced by the backend (Raj, step 5) from the `.env` values in `.env.example`. With open sign-up
the hard totals matter most: when one is reached, live builds and chat pause and replay keeps working.

**Token Factory ($25).** Measured: Phase 2b builds cost $0.07 to $0.31 each (`docs/VERIFICATION.md`), **but those
runs reused the laptop's response cache**. The first build on a fresh worker (logs, phase-1 profile) cost $0.80, almost
all of it the Nemotron Ultra baseline (451 calls). Expect roughly $0.5 to $1 per new build. **Decided (Raj, 2026-10-29):** per-build cap raised to $2.50; the Ultra
baseline stays at 300 sealed records (accuracy of the comparison first). The $17 total then covers ~20 typical builds.

| Use | Limit | Variable |
|---|---|---|
| Kept for the final demo recordings and rehearsals | $8 (outside the app's total) | |
| Hard total for everything live (builds, chat, compare, escalations) | $17 | `TOKEN_FACTORY_TOTAL_BUDGET_USD` |
| One build | $2.50 | `CREDIT_BUDGET_USD` |
| One user's builds per day | $2.50, at most 3 builds | `USER_DAILY_BUILD_BUDGET_USD`, `MAX_BUILDS_PER_USER_PER_DAY` |
| All users' builds per day | $5.00 | `GLOBAL_DAILY_BUILD_BUDGET_USD` |
| Public chat, compare, cascade escalations per day | $1.00 | `DEMO_DAILY_BUDGET_USD` |
| Builds running at once | 2 overall, 1 per user (rate limit is shared) | `MAX_CONCURRENT_BUILDS`, `MAX_CONCURRENT_BUILDS_PER_USER` |

**Nebius AI Cloud ($25).** Rates from `config/pricing.yaml` (`docs/VERIFICATION.md` §3): endpoint 2 vCPU / 8 GB
$0.0699/h; a 4 vCPU / 16 GB worker $0.1359/h.

| Use | Budget | What it buys |
|---|---|---|
| API endpoint | $12 | ~170 hours: **not** 24/7 for the whole hackathon (24/7 is ~$1.68/day). Stop it between work sessions; run it continuously only during judging |
| Build workers (AI Jobs, 4 vCPU / 16 GB) | $6, enforced (`WORKER_TOTAL_BUDGET_USD`) | ~44 worker-hours; a build is estimated at 20 to 60 min on 4 vCPUs (VERIFY on the first worker run) |
| Object Storage and registry | < $1 | 50 GiB cap at $0.0147/GiB-month; images a few GB |
| Reserve | $6 | |

Spend so far: the endpoint has been running since its creation on 2026-10-28; check the balance in the console.

**Tavily ($25).** At most 5 searches per build and 100 per day for all users (`TAVILY_MAX_SEARCHES_PER_BUILD`,
`TAVILY_DAILY_SEARCH_LIMIT`). Price per search: VERIFY on Tavily's pricing page when Raj's step 6 starts. The demo never
depends on live search results (spec file 03 §1.2).
