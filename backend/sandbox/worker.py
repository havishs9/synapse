"""Train and validate one candidate config. Prints one JSON line per step to stdout (spec 02 section 5.12).

Run as: python -m backend.sandbox.worker <job.json>
The worker only receives train/val paths; `load_split` refuses the sealed directory.
"""
from __future__ import annotations

import json
import random
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

import numpy as np


def emit(**kw):
    print(json.dumps(kw), flush=True)


def stratified_fraction(rows, frac, seed):
    if frac >= 1.0:
        return rows
    rng = random.Random(seed)
    by = defaultdict(list)
    for r in rows:
        by[r["label"]].append(r)
    out = []
    for label in sorted(by):
        rs = by[label][:]
        rng.shuffle(rs)
        out.extend(rs[:max(2, round(len(rs) * frac))])
    rng.shuffle(out)
    return out


def main(job_path: str) -> int:
    job = json.loads(Path(job_path).read_text())
    cand = job["cand"]
    from backend import metrics as M
    from backend.candidates import LLM_FAMILIES, Context, build
    from backend.sealed import load_split

    t_start = time.perf_counter()
    train = stratified_fraction(load_split(Path(job["train_path"])), job["data_frac"], job["seed"])
    if job.get("bootstrap"):
        # Seed reruns: resample the training set with replacement so seeds measure data variance.
        rng = random.Random(job["seed"])
        train = [rng.choice(train) for _ in range(len(train))]
    val = load_split(Path(job["val_path"]))
    if job["family"] in LLM_FAMILIES or job.get("max_eval"):
        cap = job.get("max_eval") or 150
        val = stratified_fraction(val, min(1.0, cap / max(len(val), 1)), 0)[:cap]   # same sample for every LLM config
    llm = None
    if job.get("needs_llm"):
        from backend.llm_client import LLMClient
        llm = LLMClient(run_dir=Path(job["run_dir"]), budget_usd=job.get("budget_remaining_usd"))
    ctx = Context(labels=job["labels"], input_type=job["input_type"], task_description=job["task_description"],
                  label_definitions=job["label_definitions"], needs_reason=False, positive=job.get("positive"),
                  seed=job["seed"], llm=llm,
                  log_templates=[tuple(t) for t in job["log_templates"]] if job.get("log_templates") else None)
    model = build(job["family"], job["params"], ctx)
    base = {"cand": cand, "round": job["round"], "data_frac": job["data_frac"]}
    emit(**base, event="start", n_train=len(train), n_val=len(val))

    model.fit([r["text"] for r in train], [r["label"] for r in train],
              progress=lambda d: emit(**base, event="progress", **d))
    t_fit = time.perf_counter() - t_start

    texts, y = [r["text"] for r in val], [r["label"] for r in val]
    t0 = time.perf_counter()
    P = model.predict_proba(texts)
    batch_s = time.perf_counter() - t0
    m = M.classification_metrics(y, P, job["labels"], primary=job["primary_metric"], positive=job.get("positive"),
                                 fpr_target=job.get("fpr_target"))
    secondary = m.get("pr_auc") if job.get("positive") else m["macro_f1"]
    emit(**base, event="progress", step="val", **{f"val_{job['primary_metric']}": m["primary"]})

    usage = model.usage_stats()
    if job.get("score_only"):
        emit(**base, event="done", primary=m["primary"], secondary=secondary, ms_per_item=None, cost_per_1m_usd=None,
             fit_s=round(t_fit, 2), metrics_path=None, usage=None)
        return 0
    if job["family"] in LLM_FAMILIES and usage:
        p50, p99 = usage["p50_ms"], usage["p99_ms"]
        throughput = 1000.0 / p50 if p50 else 0.0
        cost, formula = M.token_cost_per_1m(job["model_ids"][usage["role"]], usage["mean_prompt_tokens"],
                                            usage["mean_completion_tokens"])
    else:
        # Latency and throughput are measured with caches bypassed: real local inference, real API calls.
        model.bypass_cache = True
        n_lat = 30 if model.uses_cloud else 100
        lat = []
        for t in texts[:n_lat]:
            s = time.perf_counter()
            model.predict_proba([t])
            lat.append((time.perf_counter() - s) * 1000)
        p50, p99 = float(np.percentile(lat, 50)), float(np.percentile(lat, 99))
        sample = texts[:300]
        s = time.perf_counter()
        model.predict_proba(sample)
        throughput = len(sample) / max(time.perf_counter() - s, 1e-9)
        model.bypass_cache = False
        cost, formula = M.cpu_cost_per_1m(throughput)
        if usage and usage.get("mean_prompt_tokens"):
            cost, formula = M.token_cost_per_1m(job["model_ids"][usage["role"]], usage["mean_prompt_tokens"], 0.0,
                                                extra_cpu_per_1m=cost)
        formula["latency_measured"] = (f"single-item predict_proba on {n_lat} items, caches bypassed, on this "
                                       "machine's CPU" + (" including the embedding API call" if model.uses_cloud else ""))
        formula["throughput_measured"] = f"batch predict_proba on {len(sample)} items, caches bypassed"

    out = Path(job["out_dir"])
    path = model.save(out)
    size_mb = path.stat().st_size / 1e6
    metrics = {**{k: m[k] for k in ("primary_metric", "primary", "macro_precision", "macro_recall", "macro_f1",
                                    "accuracy", "per_class", "calibration_error", "n")},
               "pr_auc": m.get("pr_auc"), "recall_at_fpr": m.get("recall_at_fpr"), "fpr_target": m.get("fpr_target"),
               "p50_ms": p50, "p99_ms": p99, "throughput_per_s": throughput, "model_size_mb": size_mb,
               "cost_per_1m_usd": cost, "cost_formula": formula, "split": "val", "secondary": secondary}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    np.save(out / "val_proba.npy", P)
    (out / "val_ids.json").write_text(json.dumps([r["id"] for r in val]))
    emit(**base, event="done", primary=m["primary"], secondary=secondary, ms_per_item=p50, cost_per_1m_usd=cost,
         fit_s=round(t_fit, 2), metrics_path=str(out / "metrics.json"), usage=usage)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1]))
    except Exception as exc:
        emit(event="error", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc()[-4000:])
        sys.exit(1)
