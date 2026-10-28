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

- `POST /api/builds` (exists) returns `{"run_id", "status": "queued"}` once the queue lands (today it starts at once).
- `POST /api/builds/{run_id}/cancel`, `POST /api/builds/{run_id}/retry`: 200 with the build object.
- Progress stays on the existing stream `GET /api/runs/{run_id}/events` (same event schema as spec file 02).
  It must keep working after a reconnect: it replays from the first event, and `?after=<n>` skips the first n.
- Raj ships a day-1 stub of `GET /api/builds` that reads `run_state.json` files, so the shape is real at once.

**Auth.** The frontend signs in with Supabase Auth (`@supabase/supabase-js`) and sends
`Authorization: Bearer <Supabase access token>` on every `/api/*` call. The backend verifies it. Until Raj's
verification lands, the backend accepts calls without a token (local dev, replay), so login UI never blocks.
Specialist prediction routes keep their own per-specialist API keys (unchanged).

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

1. **Supabase.** Project, schema as SQL migrations in `supabase/migrations/`: `specialists`, `versions`,
   `api_keys` (hashes only), `builds`, `build_events`, all with `user_id` and row-level security. The registry
   (`backend/versions/registry.py`) reads and writes Postgres, with the current files kept as the local/replay
   fallback. JWT verification in `backend/auth.py`; every route checks ownership. Fixes: keys lost on endpoint
   restart; anyone can regenerate (revoke) a key on the public demo.
2. **Nebius Object Storage.** Bucket, `backend/storage/`: bundles and run folders under
   `users/<user_id>/...`. The endpoint loads a specialist's bundle on first call and keeps recent ones in memory
   (LRU); it loads only bundles our pipeline wrote. Replaces the repo download at startup.
3. **Build queue and workers.** `builds` table as the queue (`FOR UPDATE SKIP LOCKED`), a dispatcher loop on the
   endpoint with caps (default 2 builds at once overall because of the Token Factory rate limit, 1 per user),
   one **Nebius AI Job** per build (`nebius ai job create`: run-to-completion container, 1 h to 168 h timeout,
   Object Storage volume). Worker heartbeats; a stale heartbeat marks the build failed. Cancel between rounds;
   retry button. Events written to `build_events`; the stream reads from there. VERIFY and record: job pricing,
   job start time, service-account permissions.
4. **Pre-built image** in Nebius Container Registry for the endpoint and the workers (startup is ~10 min today,
   mostly `pip install`). Fix `_reload_remote` (imports a missing `backend.serving.sync`). The running endpoint was created with `RUNS_DIR=./runs`; `deploy.sh` now sets `./artifacts/demo/runs`, so replay on the endpoint needs this redeploy.
5. **Budgets.** Per-user training budget; cascade escalations on public predictions count against the daily
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

## 5. Inputs needed before Claude can do each part

**Raj's track**

| # | What | Who | Blocks |
|---|---|---|---|
| R-a | Supabase project: project URL, anon key, service-role key, JWT secret (or JWKS URL), Postgres connection string (pooler) in `.env` | Raj (supabase.com) | step 1 |
| R-b | Login methods: email magic link (default) and/or Google (needs a Google OAuth client ID and secret set in the Supabase dashboard). Who can sign up during the hackathon: open, or invite-only to protect credits (recommended) | Raj, decision | step 1 |
| R-c | Nebius Object Storage: bucket name, access key ID + secret (service-account static key), endpoint URL. Or approve Claude creating them with the CLI | Raj (console) | step 2 |
| R-d | Nebius service account that can create AI Jobs (and its authorized key), plus a Container Registry. Or approve Claude creating them | Raj | steps 3-4 |
| R-e | Approval for billed resources: one AI Job per build, registry storage, bucket storage | Raj | steps 2-4 |
| R-f | Limits: concurrent builds (default 2 overall, 1 per user), per-user build budget (default $5, like `CREDIT_BUDGET_USD`), daily demo budget | Raj, decision | step 3, 5 |
| R-g | `TAVILY_API_KEY` (and optional `HF_TOKEN`) | Raj | step 6 |

**Havish's track**

| # | What | Who | Blocks |
|---|---|---|---|
| H-a | `.env` with a Token Factory key (see §4) | Havish / Raj | live predictions, compare, chat |
| H-b | Vercel account linked to the GitHub repo | Havish | hosting |
| H-c | Supabase project URL and anon key | from Raj (after R-a) | login screens only |
| H-d | `CORS_ORIGINS` with the Vercel URL set on the endpoint | Raj redeploys | public URL calling the API |
| H-e | Exact example record for compare mode in the video (`TEAM_INPUTS.md`) | Havish, decision | video |
| H-f | YouTube channel for the public video | Havish | submission |

**Team, for `TEAM_INPUTS.md`:** current Token Factory credit balance, the budget per run for the final demo
recordings, and the Tavily credits available.

## 6. Running costs to keep in mind

- Nebius endpoint: ~$0.07/h while running (`docs/VERIFICATION.md` §4). Stop it when not needed:
  `~/.nebius/bin/nebius ai endpoint stop aiendpoint-e04txwn4spe6v76nes`. Restarts clear API keys until
  Raj's step 1 lands.
- Builds: Phase 2b runs cost $0.07 to $0.31 of Token Factory credits each.
