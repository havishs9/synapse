"""One-off repair for runs made before the cascade point was saved in eval_report.json (report card showed n/a).

Rebuilds the shipped cascade's Pareto point from the same report's `cascade` block, then rewrites the report card.
  python scripts/backfill_cascade_point.py <run_id> [...]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import config  # noqa: E402
from backend.report import write_report_card  # noqa: E402

for rid in sys.argv[1:]:
    d = config.runs_dir() / rid
    rep = json.loads((d / "eval_report.json").read_text())
    c, chosen = rep.get("cascade") or {}, rep.get("chosen")
    if not c or not chosen or not chosen.startswith("H("):
        print(f"{rid}: nothing to do")
        continue
    if not any(p["cand"] == chosen for p in rep["pareto_points"]):
        rep["pareto_points"].append({"cand": chosen, "family": "H", "rung": 0, "round": 0, "data_frac": 1.0,
                                     "val_primary": c["primary"], "cost_per_1m_usd": c["cost_per_1m_usd"],
                                     "p50_ms": c["p50_ms"], "p99_ms": c["p99_ms"], "eliminated": False,
                                     "final_round": True, "uses_cloud": True, "n_val": c["n"]})
    (d / "eval_report.json").write_text(json.dumps(rep, indent=2))
    write_report_card(d)
    print(f"{rid}: added {chosen}")
    # The deployed bundle took its cost and latency from the same missing point.
    for vfile in (config.artifacts_dir() / "specialists").glob("*/versions.json"):
        for v in json.loads(vfile.read_text())["versions"]:
            b = vfile.parent / f"v{v['version']}" / "bundle.json"
            if v["run_id"] == rid and b.exists():
                meta = json.loads(b.read_text())
                for k in ("cost_per_1m_usd", "p50_ms", "p99_ms"):
                    if meta.get(k) is None:
                        meta[k] = c[k]
                b.write_text(json.dumps(meta, indent=2))
                print(f"  patched {b.relative_to(config.artifacts_dir())}")
