"""Copy recorded demo runs and their specialists into the committed demo folders (replay mode + public deploy).

  python scripts/snapshot_demo.py <run_id> [<run_id> ...]

For each run: keeps every JSON handoff file, events.jsonl and the report card, and marks it replayable.
Procurement (USAspending) runs also keep train/val/holdback/sealed so v1 -> v2 improvement works on the
deployed app. HDFS runs drop every file containing raw log lines (team rule: don't redistribute raw logs).
The specialist's versions.json and bundles go to artifacts/demo/specialists/ with API keys stripped.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import config  # noqa: E402

KEEP_ALWAYS = {"task_card.json", "dataset_manifest.json", "dataset_stats.json", "candidate_plan.json", "runs.json",
               "eval_report.json", "error_patterns.json", "report_card.json", "report_card.md", "events.jsonl",
               "run_state.json", "llm_calls.jsonl", "labels.json", "corrections.json", "versions_gate.json"}
DATA_FILES = {"train.jsonl", "val.jsonl", "holdback.jsonl", "synthetic_eval.jsonl"}
DEST_RUNS = ROOT / "runs"
DEST_ART = ROOT / "artifacts" / "demo" / "specialists"


def snapshot(run_id: str) -> None:
    src = config.runs_dir() / run_id
    card = json.loads((src / "task_card.json").read_text())
    raw_logs = card["input_type"] == "log_window"
    dest = DEST_RUNS / run_id
    if src.resolve() != dest.resolve():
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for name in KEEP_ALWAYS | (set() if raw_logs else DATA_FILES):
            if (src / name).exists():
                shutil.copy2(src / name, dest / name)
        if not raw_logs and (src / "sealed").exists():
            shutil.copytree(src / "sealed", dest / "sealed")
        for m in src.glob("candidates/*/*/metrics.json"):
            out = dest / m.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(m, out)
    (dest / "replay.ok").write_text("recorded demo run\n")

    for vfile in (config.artifacts_dir() / "specialists").glob("*/versions.json"):
        v = json.loads(vfile.read_text())
        if not any(r["run_id"] == run_id for r in v["versions"]):
            continue
        sdest = DEST_ART / v["specialist_id"]
        sdest.mkdir(parents=True, exist_ok=True)
        for r in v["versions"]:
            b = vfile.parent / f"v{r['version']}"
            if b.exists() and not (sdest / f"v{r['version']}").exists():
                shutil.copytree(b, sdest / f"v{r['version']}")
        v["api_keys"] = []          # deployed instances create their own keys
        (sdest / "versions.json").write_text(json.dumps(v, indent=2))
        print(f"specialist {v['specialist_id']}: {len(v['versions'])} version(s)")
    print(f"snapshotted {run_id} ({'no raw logs' if raw_logs else 'with data files'})")


if __name__ == "__main__":
    for rid in sys.argv[1:]:
        snapshot(rid)
