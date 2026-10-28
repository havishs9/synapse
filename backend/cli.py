"""Command line: run a build for a demo task.

  python -m backend.cli build procurement [--phase1]
  python -m backend.cli build hdfs_logs
"""
from __future__ import annotations

import argparse
import json

from backend.demo_tasks import DEMO_TASKS
from backend.orchestrator import PHASE1, Options, Orchestrator


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("task", choices=sorted(DEMO_TASKS))
    b.add_argument("--phase1", action="store_true", help="hardcoded plan, single round, no agents")
    b.add_argument("--run-id")
    b.add_argument("--set", action="append", default=[], help="task card override, e.g. thresholds.primary_min=0.6")
    args = ap.parse_args()
    card = DEMO_TASKS[args.task]()
    for kv in args.set:
        key, val = kv.split("=", 1)
        data = card.model_dump()
        obj = data
        *path, last = key.split(".")
        for p in path:
            obj = obj[p]
        obj[last] = json.loads(val)
        card = type(card).model_validate(data)
    orch = Orchestrator(card, run_id=args.run_id, options=PHASE1 if args.phase1 else Options())
    print(f"run {orch.run_id} -> {orch.dir}")
    res = orch.run()
    print(json.dumps({"status": orch.state.status, "message": orch.state.message, "spend_usd": orch.spend(), **res}))


if __name__ == "__main__":
    main()
