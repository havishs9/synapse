"""Record a real dataset search for each demo task, so replay can show it (spec 03 §1.1).

  .venv/bin/python scripts/record_data_search.py [task_id ...]

For each demo task this runs the same search a new task gets: Nemotron Ultra drafts the search queries from the
demo request, then the Hugging Face Hub keyword search and Tavily (huggingface.co only) find candidates, each
one's license and columns are read, and Ultra judges which fit the task's labels. The result is saved to
artifacts/demo/data_search/<task_id>.json with the date it ran. Intake shows it next to the vetted dataset the
demo actually trains on (config/datasets.yaml), so the chat never claims the search found that dataset unless
it did. Costs: one Tavily search and two Nemotron Ultra calls per task.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import config, data_sourcing  # noqa: E402
from backend.llm_client import LLMClient  # noqa: E402

OUT = ROOT / "artifacts" / "demo" / "data_search"
# The request each demo starts from (frontend/src/components/MainChat.tsx EXAMPLES, docs/VIDEO_SCRIPT.md).
REQUESTS = {
    "procurement": "Sort our purchase records into spending categories",
    "hdfs_logs": "Flag anomalies in our system logs",
    "support_tickets": "Route our customer support tickets to the right team",
}


def record(task_id: str, llm: LLMClient) -> dict:
    from backend.routes.product import base_card
    card = base_card(task_id)
    draft = data_sourcing.draft_task(REQUESTS[task_id], [], llm)
    web_ids: list[str] = []
    search_web = data_sourcing.search_web

    def recording_search_web(query: str) -> list[str]:
        web_ids.extend(search_web(query))
        return web_ids

    data_sourcing.search_web = recording_search_web
    try:
        found = data_sourcing.find_datasets(card, draft, llm)
    finally:
        data_sourcing.search_web = search_web
    picks = [{k: o.get(k) for k in ("name", "url", "license", "rows", "fit", "why", "found_by", "labels", "gap_labels")}
             for o in found["options"] if o["kind"] == "hf"]
    return {"task_id": task_id, "request": REQUESTS[task_id], "searched_at": dt.date.today().isoformat(),
            "hub_queries": draft.get("search_queries") or [], "web_query": draft.get("web_query") or "",
            "web_dataset_ids": web_ids, "candidates_inspected": found["searched"]["candidates"],
            "fits": picks, "left_out": found["rejected"],
            "note": "Recorded by scripts/record_data_search.py. 'fits' are datasets Nemotron Ultra judged to match "
                    "the task's labels; the demo trains on the vetted dataset in config/datasets.yaml."}


def main(task_ids: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    llm = LLMClient(run_dir=OUT, budget_usd=0.5)
    for t in task_ids or list(REQUESTS):
        res = record(t, llm)
        (OUT / f"{t}.json").write_text(json.dumps(res, indent=1) + "\n")
        print(f"{t}: queries {res['hub_queries']}, web {res['web_dataset_ids']}, {res['candidates_inspected']} "
              f"inspected, fits {[p['name'] for p in res['fits']]}, left out {len(res['left_out'])}")
    print(f"LLM spend ${llm.spend.spent_usd:.4f}")


if __name__ == "__main__":
    if not config.env("TAVILY_API_KEY"):
        sys.exit("TAVILY_API_KEY is not set in .env")
    main(sys.argv[1:])
