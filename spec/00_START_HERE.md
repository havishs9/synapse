# Synapse: Final Build Plan (start here)

Handoff for Claude Code. This merges the team plan ("Hackathon build plan" doc) with the earlier Claude Code build prompt. **Read all six files and `TEAM_INPUTS.md` (repo root) before writing any code.** These files replace the old `SPEC.md`.

| File | Contents |
|---|---|
| `00_START_HERE.md` | Conventions, hard constraints, deadline, team decisions |
| `01_PRODUCT_SPEC.md` | What we're building and every user-facing feature |
| `02_ARCHITECTURE.md` | Tech stack, env vars, orchestrator + agents, pipeline stages, JSON schemas, repo layout |
| `03_ML_PIPELINE.md` | Data handling, candidate ladder, planner rules, search, sandbox, repair, cascade, evaluation rules |
| `04_NEBIUS_AND_VERIFICATION.md` | Model roles, Token Factory, Sandboxes, Serverless hosting, what is already confirmed vs. still to verify |
| `05_DEMO_BUILD_ORDER_AND_ACCEPTANCE.md` | Demo tasks, build phases by day, cut order, tests, acceptance criteria, README, don'ts, submission checklist |
| `../TEAM_INPUTS.md` | Team names, credits, platform facts found by hand, Discord answers. Values there override defaults here |

## Conventions

- Every item is a **requirement** unless marked **STRETCH**.
- **VERIFY**: do not assume it works. Check the official docs or test it. If it fails, use the stated fallback and record what happened in `docs/VERIFICATION.md`.
- **CONFIRMED**: already checked against official docs or the Token Factory console on 2026-10-27 (source in file 04). Re-check only if a call fails.
- **DECISION**: a team choice. The default is already applied throughout these files.
- Work in the build order in file 05. Do not start a later phase until the earlier one works end to end.

## Deadline

Submissions close **Friday Oct 30, 2026, 10:00 AM PT (1:00 PM ET)**. Team target: submit by **11:00 AM ET**.

## Hard constraints (non-negotiable)

1. The project runs on **Nebius Token Factory and/or Nebius AI Cloud**.
2. It uses at least one **NVIDIA open source model (Nemotron)**, and Nemotron is load-bearing, not decorative.
3. The repo is **public with an MIT license file** at the repo root.
4. The README has setup instructions, run instructions, and a **"Built on Nebius and NVIDIA"** section (requirements in file 05).
5. A **publicly accessible working demo URL** exists.
6. A **demo video of 3 minutes or less** (public on YouTube). Replay mode (file 02) makes recording reliable.
7. **Never commit secrets.** All keys come from environment variables; provide `.env.example`.
8. **Never hardcode model IDs, prices or endpoint URLs.** They live in `config/models.yaml` and `config/pricing.yaml`. Fill model IDs from Token Factory's list-models endpoint (VERIFY).
9. Token Factory exposes an **OpenAI-compatible API** at `https://api.tokenfactory.nebius.com/v1/` (CONFIRMED). Use the OpenAI Python SDK with that base URL.
10. **Nemotron cannot be fine-tuned on Token Factory** (CONFIRMED). Nemotron is the planner, teacher, judge, error analyst, baseline, prompted ladder rungs, and cascade fallback. Build nothing that assumes Nemotron fine-tuning.
11. **Use only authorized data.** Public datasets with recorded licenses. No Corvo or customer records anywhere in the repo.

## Submission package (Devpost)

Track: **Coding and Agentic Engineering**. Project description, working demo URL, public repo (MIT + README), demo video under 3 minutes, and detailed feedback on Nebius/NVIDIA tools (from `docs/FEEDBACK.md`). Judging weights four criteria equally: Technological Implementation, Design, Potential Impact, Quality of the Idea.

## Team decisions (final)

Where the team plan and the earlier Claude Code prompt disagreed, the team decided as follows. These are applied throughout the files.

| ID | Topic | Decision | Where |
|---|---|---|---|
| D1 | Demo tasks | **Two showcase tasks:** procurement categorization (USAspending) as the main walkthrough, and system log anomaly detection (LogHub HDFS) as a second task with a different winner. Banking77 is optional; prompt injection is STRETCH | 05 |
| D2 | Model access | **API only.** No download button; model files stay managed by us | 01 |
| D3 | Specialist serving | **Every specialist gets its own API**: its own URL path and its own API key, served by one shared specialist server on one Nebius Serverless CPU endpoint. (Not a Nebius "dedicated endpoint", which is a paid GPU product we avoid) | 01, 02, 04 |
| D4 | Search schedule | **Successive halving by training-data fraction:** all candidates on 10% of the data, top quarter on 40%, top 2 to 3 on 100%, with a small-data guard | 03 |
| D5 | Clarifying questions | One message, **at most 7** questions | 01 |
| D6 | Cost projection volume | Projected at the **monthly volume from the task card** | 01 |
| D7 | Demo video centerpiece | **Compare mode and the validated v1 to v2 update** (video outline is flexible) | 05 |

Minor alignments (no decision needed):

- UI streaming uses **SSE end to end** (the team plan mentioned websockets; SSE is simpler and matches the earlier prompt).
- `CREDIT_BUDGET_USD` defaults to **5 per run**, because total Token Factory credit is about $25.
- The progress panel keeps the earlier prompt's agent lanes and adds the team plan's live Pareto scatter and narration feed.
- "Never cut" lists from both plans are merged (file 05).
