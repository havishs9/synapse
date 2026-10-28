# Team Inputs

Claude Code: read this file together with the spec files in `spec/` (start with `spec/00_START_HERE.md`). The team decisions D1 to D7 in `spec/00_START_HERE.md` are final. This file adds facts only the team can provide. Anything marked UNKNOWN must be checked during Phase 0 and recorded in `docs/VERIFICATION.md`. Never put API keys in this file; keys live only in `.env`.

## Project
- Project name: Synapse
- Public GitHub repo URL: https://github.com/havishs9/synapse
- License: MIT

## Team and ownership
- Person A (pipeline, Sandboxes, agents): Raj (Phase 3: storage, auth backend, build queue and workers, API endpoint deploys)
- Person B (UI, compare mode, deployment, demo video): Havish (Phase 3: all frontend, product routes, Vercel hosting, docs, video)
- Other members and roles: plan and contracts in `docs/TEAM_PLAN.md`

## Credits and budget
- Token Factory credits claimed (promo form + Builders Program): yes
- Current Token Factory credit balance: $25 (2026-10-28); Nebius AI Cloud: $25; Tavily: $25. Budgets in `docs/TEAM_PLAN.md` §6
- CREDIT_BUDGET_USD per run during development: 1 (was 5; Phase 2b builds cost $0.07 to $0.31)
- CREDIT_BUDGET_USD per run for the final demo recordings: 1; $8 of Token Factory credits kept aside for the recordings and rehearsals
- Tavily credits available: $25 (at most 5 searches per build, 100 per day)

## Platform facts (fill in what you know, write UNKNOWN otherwise)
- NEBIUS_PROJECT_ID set in .env: yes / no
- API model IDs from the console or GET /v1/models:
  - Nemotron-3-Ultra-550b-a55b: UNKNOWN
  - Nemotron-3-Super-120b-a12b: UNKNOWN
  - Nemotron-3-Nano-30B-A3B: UNKNOWN
  - Nemotron-3.5-Lightning: UNKNOWN
  - Qwen3-Embedding-8B: UNKNOWN
- Sandboxes enabled on our account: UNKNOWN
- Sandbox limits from whoami (timeout, CPU, memory): UNKNOWN
- Serverless CPU endpoint created successfully: yes (2026-10-28, `aiendpoint-e04txwn4spe6v76nes`, https://port8000-b3arav7mmzek3n6.tunnel.applications.eu-west2.nebius.cloud)
- Object Storage bucket created: yes (2026-10-28, `synapse-artifacts-e04crhvwbc`, eu-west2); Container Registry `registry-e04cjwm2bdv5k5b8hc`; service account pending (`scripts/setup_service_account.sh`, run by Raj)
- Rate limits on our account: UNKNOWN
- Answers received from Nebius Discord (paste with date):

## Decisions (defaults from spec/00_START_HERE.md; change only if the team agrees)
- Main demo task: procurement categorization (USAspending)
- Second showcase task: system log anomaly detection (LogHub HDFS)
- Optional third task: Banking77: yes (built 2026-10-28, `p2b-support-c`)
- Prompt-injection task (STRETCH): no
- Specialist hosting: one shared specialist server on one Nebius Serverless CPU endpoint (fallback: main backend)
- Public demo app hosting: frontend on Vercel, API and specialists on the Nebius Serverless endpoint (2026-10-28)
- Exact example record for compare mode in the video:

## Data
- Dataset licenses read and approved by a human:
  - USAspending (data-use terms): yes / no
  - LogHub HDFS: yes / no
  - Banking77 (CC-BY-4.0): yes / no

## Notes for Claude Code
- Anything else it should know:
