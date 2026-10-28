"""Metric calculations used by the Trainer (validation) and the Evaluator (validation and sealed test)."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_fscore_support

from backend import config


def recall_at_fpr(y_true_pos: np.ndarray, scores: np.ndarray, fpr_target: float) -> tuple[float, float]:
    """Highest recall reachable while the false-positive rate stays at or below fpr_target.

    Returns (recall, threshold). Ties are handled by thresholding strictly above a negative score.
    """
    y = np.asarray(y_true_pos, dtype=bool)
    s = np.asarray(scores, dtype=float)
    neg = np.sort(s[~y])[::-1]
    if len(neg) == 0 or y.sum() == 0:
        return float("nan"), float("nan")
    allowed = int(np.floor(fpr_target * len(neg)))       # negatives allowed above threshold
    thr = neg[allowed] if allowed < len(neg) else -np.inf  # predict positive iff score > thr
    return float((s[y] > thr).mean()), float(thr)


def expected_calibration_error(conf: np.ndarray, correct: np.ndarray, bins: int = 10) -> float:
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            ece += m.mean() * abs(conf[m].mean() - correct[m].mean())
    return float(ece)


def classification_metrics(y_true: list[str], proba: np.ndarray, labels: list[str], *, primary: str,
                           positive: str | None = None, fpr_target: float | None = None,
                           threshold: float | None = None) -> dict:
    """Metrics for multiclass or binary tasks. For binary tasks with a threshold, the positive class is
    predicted when P(positive) > threshold; otherwise argmax."""
    proba = np.asarray(proba, dtype=float)
    idx = {l: i for i, l in enumerate(labels)}
    yt = np.array([idx[y] for y in y_true])
    if positive is not None and threshold is not None and len(labels) == 2:
        pi = idx[positive]
        pred = np.where(proba[:, pi] > threshold, pi, 1 - pi)
    else:
        pred = proba.argmax(axis=1)
    p, r, f, s = precision_recall_fscore_support(yt, pred, labels=list(range(len(labels))), zero_division=0)
    out = {
        "accuracy": float((pred == yt).mean()),
        "macro_precision": float(p.mean()), "macro_recall": float(r.mean()), "macro_f1": float(f.mean()),
        "per_class": {l: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(s[i])}
                      for i, l in enumerate(labels)},
        "n": int(len(yt)),
    }
    conf = proba.max(axis=1)
    out["calibration_error"] = expected_calibration_error(conf, pred == yt)
    if positive is not None:
        pi = idx[positive]
        ypos = yt == pi
        out["pr_auc"] = float(average_precision_score(ypos, proba[:, pi])) if ypos.any() else float("nan")
        if fpr_target is not None:
            rec, thr = recall_at_fpr(ypos, proba[:, pi], fpr_target)
            out["recall_at_fpr"], out["fpr_target"], out["threshold_at_fpr"] = rec, fpr_target, thr
    out["primary_metric"] = primary
    out["primary"] = float(out[primary])
    return out


def predictions(proba: np.ndarray, labels: list[str]) -> list[str]:
    return [labels[i] for i in np.asarray(proba).argmax(axis=1)]


def cpu_cost_per_1m(throughput_per_s: float) -> tuple[float, dict]:
    """Cost of 1M predictions on the Serverless CPU endpoint at the measured single-thread throughput."""
    hourly = config.serverless_hourly_usd()
    s = config.pricing()["serverless_cpu"]
    seconds = 1e6 / max(throughput_per_s, 1e-9)
    cost = hourly * seconds / 3600
    return cost, {"kind": "cpu", "endpoint_hourly_usd": hourly, "preset": s["chosen_preset"],
                  "platform": s["platform"], "throughput_per_s": throughput_per_s,
                  "formula": "endpoint_hourly_usd × (1e6 / throughput_per_s) / 3600"}


def token_cost_per_1m(api_id: str, mean_prompt_tokens: float, mean_completion_tokens: float,
                      extra_cpu_per_1m: float = 0.0) -> tuple[float, dict]:
    p = config.token_price(api_id)
    per_item = (mean_prompt_tokens * p["input"] + mean_completion_tokens * p.get("output", 0.0)) / 1e6
    cost = per_item * 1e6 + extra_cpu_per_1m
    return cost, {"kind": "tokens", "model": api_id, "mean_prompt_tokens": mean_prompt_tokens,
                  "mean_completion_tokens": mean_completion_tokens, "price_per_1m_tokens": p,
                  "cpu_part_per_1m_usd": extra_cpu_per_1m,
                  "formula": "1e6 × (prompt_tokens × input_price + completion_tokens × output_price) / 1e6 + cpu_part"}
