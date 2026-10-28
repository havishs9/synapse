# Team Inputs

Claude Code: read this file together with the spec files in `spec/` (start with `spec/00_START_HERE.md`). The team decisions D1 to D7 in `spec/00_START_HERE.md` are final. This file adds facts only the team can provide. Anything marked UNKNOWN must be checked during Phase 0 and recorded in `docs/VERIFICATION.md`. Never put API keys in this file; keys live only in `.env`.

## Project
- Project name: Synapse
- Public GitHub repo URL: https://github.com/havishs9/synapse
- License: MIT

## Team and ownership
- Person A (pipeline, Sandboxes, agents):
- Person B (UI, compare mode, deployment, demo video):
- Other members and roles:

## Credits and budget
- Token Factory credits claimed (promo form + Builders Program): yes / no
- Current Token Factory credit balance: $
- CREDIT_BUDGET_USD per run during development: 5
- CREDIT_BUDGET_USD per run for the final demo recordings:
- Tavily credits available:

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
- Serverless CPU endpoint created successfully: UNKNOWN
- Object Storage bucket created: UNKNOWN
- Rate limits on our account: UNKNOWN
- Answers received from Nebius Discord (paste with date):

## Decisions (defaults from spec/00_START_HERE.md; change only if the team agrees)
- Main demo task: procurement categorization (USAspending)
- Second showcase task: system log anomaly detection (LogHub HDFS)
- Optional third task: Banking77 (yes / no)
- Prompt-injection task (STRETCH): no
- Specialist hosting: one shared specialist server on one Nebius Serverless CPU endpoint (fallback: main backend)
- Public demo app hosting:
- Exact example record for compare mode in the video:

## Data
- Dataset licenses read and approved by a human:
  - USAspending (data-use terms): yes / no
  - LogHub HDFS: yes / no
  - Banking77 (CC-BY-4.0): yes / no

## Notes for Claude Code
- Anything else it should know:
