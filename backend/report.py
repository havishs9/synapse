"""Report card (spec 01 section 2.7): built only from files in runs/<run_id>/. JSON + Markdown."""
from __future__ import annotations

import json
from pathlib import Path

from backend import config


def _fmt(x, nd=3):
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def build_report_card(run_dir: Path) -> dict:
    rd = Path(run_dir)
    card = json.loads((rd / "task_card.json").read_text())
    rep = json.loads((rd / "eval_report.json").read_text())
    manifest = json.loads((rd / "dataset_manifest.json").read_text())
    plan = json.loads((rd / "candidate_plan.json").read_text())
    winner = rep.get("winner")
    chosen = rep.get("chosen") or winner
    pts = {p["cand"]: p for p in rep["pareto_points"]}
    wp = pts.get(chosen) or {}
    mp = Path(wp["metrics_path"]) if wp.get("metrics_path") else None
    if mp is not None and not mp.is_absolute():
        mp = rd / mp                                   # snapshots store paths relative to the run folder
    metrics_file = json.loads(mp.read_text()) if mp is not None and mp.exists() else {}
    final = rep.get("final") or {}
    base = rep.get("baseline") or {}
    volume = card.get("monthly_volume") or config.demo_monthly_volume()
    out = {
        "run_id": rd.name, "task": card["task_name"], "task_id": card["task_id"],
        "winner": {"candidate": chosen, "family": wp.get("family"), "why": rep.get("winner_reason"),
                   "planner_summary": plan["summary"], "planner_source": plan["planner_source"]},
        "frontier": rep["frontier"],
        "excluded_families": plan["excluded"],
        "primary_metric": rep["primary_metric"],
        "sealed": final, "validation_vs_sealed": rep.get("val_vs_sealed"),
        "seeds": rep.get("seeds"), "teacher_agreement": rep.get("teacher_agreement"),
        "baseline": base, "specialist_on_baseline_sample": rep.get("final_sample"),
        "real_vs_synthetic": rep.get("real_vs_synthetic"),
        "latency": {"p50_ms": wp.get("p50_ms"), "p99_ms": wp.get("p99_ms")},
        "cost_per_1m_usd": wp.get("cost_per_1m_usd"),
        "cost_formula": metrics_file.get("cost_formula") or (rep.get("cascade") or {}).get("cost_formula"),
        "throughput_per_s": metrics_file.get("throughput_per_s"),
        "model_size_mb": metrics_file.get("model_size_mb"),
        "cascade": rep.get("cascade"), "more_data_curve": rep.get("more_data_curve"),
        "weaknesses": rep.get("weaknesses"), "repair_rounds": rep.get("repair_rounds"),
        "calibration": rep.get("calibration"), "decision": rep.get("decision"),
        "data_sources": manifest["sources"], "splits": {k: v["rows"] for k, v in manifest["splits"].items()},
        "pareto_points": rep["pareto_points"],
        "monthly_volume": volume, "monthly_volume_source": "task card" if card.get("monthly_volume") else "DEMO_MONTHLY_VOLUME",
    }
    if base.get("cost_per_1m_usd") and wp.get("cost_per_1m_usd") is not None:
        yearly = volume * 12 / 1e6
        out["projection"] = {"baseline_yearly_usd": base["cost_per_1m_usd"] * yearly,
                             "specialist_yearly_usd": wp["cost_per_1m_usd"] * yearly,
                             "method": "cost per 1M predictions × monthly_volume × 12 / 1e6 (marginal cost; the "
                                       "Serverless endpoint is shared by all specialists)"}
    return out


def to_markdown(rc: dict) -> str:
    pm = rc["primary_metric"]
    s = rc["sealed"] or {}
    lines = [f"# Report card: {rc['task']}", "", f"Run `{rc['run_id']}`", "",
             "## Winning strategy", "",
             f"**{rc['winner']['candidate']}** (family {rc['winner']['family']}): {rc['winner']['why']}.", "",
             f"Planner ({rc['winner']['planner_source']}): {rc['winner']['planner_summary']}", "",
             "Frontier alternatives:", ""]
    for f in rc["frontier"]:
        lines.append(f"- {f['role']}: {f['cand']} — {pm} {f['val_primary']:.3f} on validation, "
                     f"${f['cost_per_1m_usd']:.4f} per 1M predictions, p50 {f['p50_ms']:.2f} ms")
    lines += ["", "## Sealed test set (true labels)", "",
              f"- {pm}: **{_fmt(s.get('primary'))}** on {s.get('n')} records",
              f"- macro precision {_fmt(s.get('macro_precision'))}, macro recall {_fmt(s.get('macro_recall'))}, "
              f"macro F1 {_fmt(s.get('macro_f1'))}"]
    if s.get("pr_auc") is not None:
        lines.append(f"- PR-AUC {_fmt(s.get('pr_auc'))}; recall at {s.get('fpr_target', 0):.0%} FPR {_fmt(s.get('recall_at_fpr'))}")
    if s.get("at_val_threshold"):
        t = s["at_val_threshold"]
        lines.append(f"- with the threshold chosen on validation: recall {t['recall']:.3f} at FPR {t['fpr']:.3%}")
    vs = rc.get("validation_vs_sealed") or {}
    gap = ("sealed is lower, as expected: picking among many candidates inflates validation"
           if (vs.get("sealed") or 0) < (vs.get("validation") or 0) else
           "sealed is not lower here; with one config per family there was little selection to inflate validation")
    lines += [f"- validation {_fmt(vs.get('validation'))} vs sealed {_fmt(vs.get('sealed'))} ({gap})", "",
              "| Class | Precision | Recall | Support |", "|---|---|---|---|"]
    for k, v in sorted((s.get("per_class") or {}).items()):
        lines.append(f"| {k} | {v['precision']:.3f} | {v['recall']:.3f} | {v['support']} |")
    b = rc.get("baseline") or {}
    fs = rc.get("specialist_on_baseline_sample") or {}
    ta = rc.get("teacher_agreement") or {}
    lines += ["", "## Nemotron Ultra zero-shot baseline", "",
              f"On the same {b.get('n')} sealed records: Nemotron Ultra {pm} {_fmt((b.get('metrics') or {}).get('primary'))} "
              f"vs specialist {_fmt((fs.get('metrics') or {}).get('primary'))}.",
              f"Baseline p50 latency {_fmt(b.get('p50_ms'), 0)} ms, ${_fmt(b.get('cost_per_1m_usd'), 2)} per 1M predictions.", ""]
    pos = (rc["sealed"] or {}).get("positive_label") or next((k for k in ("anomaly",) if k in ((b.get("metrics") or {}).get("per_class") or {})), None)
    if pos:
        bp, sp = b["metrics"]["per_class"][pos], (fs.get("metrics") or {}).get("per_class", {}).get(pos, {})
        lines += [f"At their own labels ({pos} class): Nemotron Ultra recall {bp['recall']:.3f}, precision {bp['precision']:.3f}; "
                  f"specialist recall {sp.get('recall', 0):.3f}, precision {sp.get('precision', 0):.3f}. Ultra's self-reported "
                  "confidence is too coarse to rank windows, which is why its recall at a fixed 1% FPR is so low.", ""]
    lines += [
              f"Agreement with Nemotron Ultra (agreement, not accuracy): {ta.get('agreement_rate', 0):.1%} on {ta.get('n')} records.", ""]
    if rc.get("seeds"):
        lines += ["## Seed error bars (3 seeds, validation)", ""]
        lines += [f"- {k}: {v['mean']:.3f} ± {v['std']:.3f}" for k, v in rc["seeds"].items()]
        lines.append("")
    if rc.get("real_vs_synthetic"):
        r = rc["real_vs_synthetic"]
        lines += ["## Real vs synthetic", "", f"- trained on {r['real_training_rows']} real + {r['synthetic_training_rows']} synthetic rows",
                  f"- real validation {pm}: {_fmt(r.get('real_validation'))}",
                  f"- held-out synthetic: {_fmt(r.get('synthetic_heldout'))} ({r.get('synthetic_metric', '')}, n={r.get('synthetic_heldout_n')})", ""]
    lines += ["## Speed and cost", "",
              f"- latency p50 {_fmt(rc['latency']['p50_ms'], 3)} ms, p99 {_fmt(rc['latency']['p99_ms'], 3)} ms",
              f"- throughput {_fmt(rc.get('throughput_per_s'), 0)} items/s; model size {_fmt(rc.get('model_size_mb'), 2)} MB",
              f"- ${_fmt(rc.get('cost_per_1m_usd'), 4)} per 1M predictions; formula: "
              f"{(rc.get('cost_formula') or {}).get('formula', rc.get('cost_formula')) if isinstance(rc.get('cost_formula'), dict) else rc.get('cost_formula')}"]
    if rc.get("projection"):
        p = rc["projection"]
        lines.append(f"- at {rc['monthly_volume']:,} records/month ({rc['monthly_volume_source']}): Nemotron Ultra "
                     f"${p['baseline_yearly_usd']:,.0f}/year vs specialist ${p['specialist_yearly_usd']:,.2f}/year ({p['method']})")
    if rc.get("cascade"):
        c = rc["cascade"]
        stages = c.get("stages") or [{"cand": c["base"], "share": 1 - c["escalation_rate"]},
                                     {"cand": c["fallback"], "share": c["escalation_rate"]}]
        split = " / ".join(f"{s['cand']} {s['share']:.1%}" for s in stages)
        lines.append(f"- cascade {' → '.join(s['cand'] for s in stages)}: answered by {split} on validation "
                     f"({'used' if c.get('used', True) else 'not used: ' + c.get('why_not', '')})")
        sealed = (rc.get("sealed") or {}).get("stage_shares")
        if sealed:
            lines.append("- on the sealed test: " + " / ".join(f"{k} {v:.1%}" for k, v in sealed.items()))
    lines += ["", "## Would more data help?", ""]
    lines += [f"- {p['data_frac']:.0%} of training data: {p['val_primary']:.3f}" for p in rc.get("more_data_curve") or []]
    lines += ["", "## Known weaknesses", ""] + [f"- {w}" for w in rc.get("weaknesses") or []]
    lines += ["", "## Data sources", ""]
    for src in rc["data_sources"]:
        lines.append(f"- {src['name']} ({src['url']}): {src['license']}; {src['rows_used']:,} rows" +
                     (f". Cite: {'; '.join(src['citation'])}" if src.get("citation") else ""))
    return "\n".join(lines) + "\n"


def write_report_card(run_dir: Path) -> dict:
    rc = build_report_card(run_dir)
    (Path(run_dir) / "report_card.json").write_text(json.dumps(rc, indent=2, default=str))
    (Path(run_dir) / "report_card.md").write_text(to_markdown(rc))
    return rc
