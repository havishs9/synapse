# Synapse

Hackathon project for the Nebius x NVIDIA Global AI Hackathon (Coding and Agentic Engineering track).

The full build spec is in `spec/`. Before any work, read `spec/00_START_HERE.md`, then files 01 to 05 in order, then `TEAM_INPUTS.md`.

Standing rules for every session:
- Work only on the phase you are asked to do (build order in `spec/05_DEMO_BUILD_ORDER_AND_ACCEPTANCE.md`). Stop when its exit criterion is met, run the tests, and commit.
- Read API keys only from `.env`. Never print, log, or commit them, and never add `.env` to git.
- Never hardcode model IDs, prices or endpoint URLs; use `config/models.yaml` and `config/pricing.yaml`.
- Record the result of every VERIFY item in `docs/VERIFICATION.md`.
- Never invent numbers for the UI, README or video; every number comes from a file in `runs/`.
- If a spec file and the code disagree, follow the spec and tell me about the conflict.
