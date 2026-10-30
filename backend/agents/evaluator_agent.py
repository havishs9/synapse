"""Evaluator agent: metrics in code, calibration, frontier, cascade, error patterns, the sealed final exam,
the Nemotron Ultra baseline, teacher agreement and the version gate.

This is the only module allowed to call `sealed.read_sealed` (enforced in backend/sealed.py).
"""
from __future__ import annotations

import itertools
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

import numpy as np
from scipy.optimize import minimize_scalar

from backend import config
from backend import metrics as M
from backend.candidates import LLM_FAMILIES, Candidate, CascadeH, Context
from backend.candidates.prompted_k import PromptedK
from backend.sealed import load_split, read_sealed
from backend.schemas import ErrorPattern, ErrorPatterns, FrontierEntry, TaskCard

Emit = Callable[..., None]
BASELINE_ROLE = "main_chat_planner_teacher_baseline"


# ---- calibration --------------------------------------------------------------
class TemperatureCalibrator:
    """Temperature scaling on log-probabilities, fitted on validation predictions."""

    def __init__(self, T: float = 1.0):
        self.T = T

    @staticmethod
    def _scale(P, T):
        z = np.log(np.clip(P, 1e-9, 1)) / T
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def fit(self, P: np.ndarray, y: np.ndarray) -> "TemperatureCalibrator":
        def nll(logT):
            Q = self._scale(P, np.exp(logT))
            return -np.mean(np.log(np.clip(Q[np.arange(len(y)), y], 1e-12, 1)))
        self.T = float(np.exp(minimize_scalar(nll, bounds=(-3, 3), method="bounded").x))
        return self

    def apply(self, P: np.ndarray) -> np.ndarray:
        return self._scale(P, self.T)


def calibration_report(P: np.ndarray, y: np.ndarray, seed: int = 0) -> tuple[TemperatureCalibrator, dict]:
    """Fit on all of val; report ECE before/after with 2-fold cross-fitting so 'after' isn't fit-on-test.

    If cross-fit ECE doesn't improve (e.g. kNN scores that are already softmax-sharpened), keep T = 1.
    """
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    halves = np.array_split(idx, 2)
    after = []
    for a, b in ((halves[0], halves[1]), (halves[1], halves[0])):
        cal = TemperatureCalibrator().fit(P[a], y[a])
        Q = cal.apply(P[b])
        after.append(M.expected_calibration_error(Q.max(1), Q.argmax(1) == y[b]))
    before = M.expected_calibration_error(P.max(1), P.argmax(1) == y)
    after_mean = float(np.mean(after))
    if after_mean >= before:
        return TemperatureCalibrator(1.0), {
            "method": "none (temperature scaling skipped: cross-fit ECE did not improve)", "temperature": 1.0,
            "ece_before": before, "ece_after_crossfit": after_mean, "skipped": True}
    cal = TemperatureCalibrator().fit(P, y)
    return cal, {"method": "temperature scaling (fit on validation)", "temperature": cal.T,
                 "ece_before": before, "ece_after_crossfit": after_mean}


# ---- helpers -------------------------------------------------------------------
def load_val_proba(cand_dir: Path) -> tuple[np.ndarray, list[str]]:
    return np.load(cand_dir / "val_proba.npy"), json.loads((cand_dir / "val_ids.json").read_text())


def stratified_sample(rows: list[dict], n: int, seed: int = 0) -> list[dict]:
    if len(rows) <= n:
        return rows
    rng = random.Random(seed)
    by = defaultdict(list)
    for r in rows:
        by[r["label"]].append(r)
    out = []
    for label in sorted(by):
        k = max(1, round(n * len(by[label]) / len(rows)))
        out.extend(rng.sample(by[label], min(k, len(by[label]))))
    rng.shuffle(out)
    return out[:n]


def metric_kwargs(card: TaskCard) -> dict:
    return {"primary": card.optimization_metric, "positive": card.positive_definition,
            "fpr_target": card.fpr_target}


def pareto_front(points: list[dict]) -> list[dict]:
    """Non-dominated points: higher val_primary and lower cost."""
    front = []
    for p in points:
        if not any(q is not p and q["val_primary"] >= p["val_primary"] and q["cost_per_1m_usd"] <= p["cost_per_1m_usd"]
                   and (q["val_primary"] > p["val_primary"] or q["cost_per_1m_usd"] < p["cost_per_1m_usd"])
                   for q in points):
            front.append(p)
    return sorted(front, key=lambda p: p["cost_per_1m_usd"])


def allowed(p: dict, card: TaskCard) -> tuple[bool, str]:
    if card.deployment == "offline" and p.get("uses_cloud"):
        return False, "calls a cloud API, but the task must run offline"
    if card.latency_budget_ms and p["p50_ms"] > card.latency_budget_ms:
        return False, f"p50 latency {p['p50_ms']:.0f} ms is over the {card.latency_budget_ms:.0f} ms budget"
    return True, ""


def choose_frontier(points: list[dict], card: TaskCard) -> tuple[list[FrontierEntry], str, str]:
    """Pick the recommended candidate from the task card's priorities.

    balanced / precision_first: the cheapest allowed candidate that meets the target.
    recall_first: the best detector that meets the target (primary metric, then the secondary metric:
    PR-AUC for binary tasks), with cost only breaking ties. If nothing meets the target: the most accurate
    allowed candidate (within 0.005 of the best, the cheaper one).
    """
    ok = [p for p in points if allowed(p, card)[0]] or points
    passing = [p for p in ok if p["val_primary"] >= card.thresholds.primary_min]
    sec = lambda p: p.get("val_secondary") or 0.0
    best = max(ok, key=lambda p: (p["val_primary"], sec(p), -p["cost_per_1m_usd"]))
    cheapest = min(ok, key=lambda p: (p["cost_per_1m_usd"], -p["val_primary"]))
    sec_name = "PR-AUC" if card.positive_definition else "macro-F1"
    if passing and card.error_preference == "recall_first":
        rec = max(passing, key=lambda p: (p["val_primary"], sec(p), -p["cost_per_1m_usd"]))
        why = (f"misses cost more than false alarms (task card), so among candidates meeting the "
               f"{card.optimization_metric} target of {card.thresholds.primary_min:.2f} this is the best detector: "
               f"{rec['val_primary']:.3f}, {sec_name} {sec(rec):.4f} on validation")
    elif passing:
        rec = min(passing, key=lambda p: (p["cost_per_1m_usd"], -p["val_primary"]))
        why = (f"cheapest candidate that meets the {card.optimization_metric} target of "
               f"{card.thresholds.primary_min:.2f} on validation ({rec['val_primary']:.3f})")
    else:
        near = [p for p in ok if p["val_primary"] >= best["val_primary"] - 0.005]
        rec = min(near, key=lambda p: p["cost_per_1m_usd"])
        why = (f"no candidate met the target of {card.thresholds.primary_min:.2f}; this is the most accurate "
               f"(within 0.005 of the best, then cheapest) at {rec['val_primary']:.3f} on validation")
    entries = [FrontierEntry(cand=rec["cand"], family=rec["family"], role="recommended", val_primary=rec["val_primary"],
                             cost_per_1m_usd=rec["cost_per_1m_usd"], p50_ms=rec["p50_ms"])]
    for role, p in (("most_accurate", best), ("cheapest", cheapest)):
        if p["cand"] not in {e.cand for e in entries}:
            entries.append(FrontierEntry(cand=p["cand"], family=p["family"], role=role, val_primary=p["val_primary"],
                                         cost_per_1m_usd=p["cost_per_1m_usd"], p50_ms=p["p50_ms"]))
    return entries, rec["cand"], why


# ---- baseline and LLM prediction ------------------------------------------------
def make_baseline(card: TaskCard, labels: list[str], llm) -> PromptedK:
    ctx = Context(labels=labels, input_type=card.input_type, task_description=card.description,
                  label_definitions={l.name: l.definition for l in card.labels}, positive=card.positive_definition,
                  llm=llm)
    model = PromptedK({"role": BASELINE_ROLE, "n_examples": 0, "concurrency": 16}, ctx)
    model.fit([], [])
    return model


def score_baseline(card: TaskCard, labels: list[str], rows: list[dict], llm, emit: Emit) -> dict:
    model = make_baseline(card, labels, llm)
    P = model.predict_proba([r["text"] for r in rows])
    m = M.classification_metrics([r["label"] for r in rows], P, labels, **metric_kwargs(card))
    usage = model.usage_stats() or {}
    cost, formula = M.token_cost_per_1m(config.model_id(BASELINE_ROLE), usage.get("mean_prompt_tokens", 0),
                                        usage.get("mean_completion_tokens", 0))
    return {"model": config.model_id(BASELINE_ROLE), "display_name": config.models()[BASELINE_ROLE]["display_name"],
            "metrics": m, "p50_ms": usage.get("p50_ms"), "p99_ms": usage.get("p99_ms"),
            "cost_per_1m_usd": cost, "cost_formula": formula, "n": len(rows), "usage": usage,
            "labels_pred": M.predictions(P, labels), "ids": [r["id"] for r in rows],
            "prompt": "zero-shot: task card description + category definitions, JSON schema output, reasoning off"}


# ---- error analysis --------------------------------------------------------------
def error_patterns(card: TaskCard, val: list[dict], P: np.ndarray, labels: list[str], llm, emit: Emit,
                   max_pairs: int = 4) -> ErrorPatterns:
    pred = M.predictions(P, labels)
    pairs = Counter((r["label"], p) for r, p in zip(val, pred) if r["label"] != p)
    top = pairs.most_common(max_pairs)
    examples = {pair: [r for r, p in zip(val, pred) if (r["label"], p) == pair][:8] for pair, _ in top}
    if not top:
        return ErrorPatterns(patterns=[], source="confusion_fallback")
    fallback = ErrorPatterns(source="confusion_fallback", patterns=[ErrorPattern(
        pattern=f"{t} records predicted as {p}", count=n, example_ids=[r["id"] for r in examples[(t, p)]],
        suggested_data_fix=f"add clearer {t} examples that resemble {p}", true_label=t, predicted_label=p)
        for (t, p), n in top])
    if llm is None:
        return fallback
    blocks = []
    for (t, p), n in top:
        ex = "\n".join(f"  - {r['text'][:300]}" for r in examples[(t, p)])
        blocks.append(f"True {t} predicted as {p} ({n} times). Examples:\n{ex}")
    prompt = ("You are analyzing a classifier's mistakes on validation data for this task: "
              f"{card.description}\n\n" + "\n\n".join(blocks) +
              "\n\nFor each confusion, describe the pattern behind the mistakes in one sentence and suggest one "
              'concrete data fix. Return JSON: {"patterns": [{"true_label": "...", "predicted_label": "...", '
              '"pattern": "...", "suggested_data_fix": "..."}]}')
    try:
        res = llm.chat(BASELINE_ROLE, [{"role": "user", "content": prompt}], agent="Evaluator",
                       purpose="error_analysis", max_tokens=4000, response_format={"type": "json_object"})
        found = {(x.get("true_label"), x.get("predicted_label")): x for x in res.json().get("patterns", [])}
    except Exception as exc:
        emit("Evaluator", "validate", f"Error analysis by Nemotron failed ({exc}); using confusion counts")
        return fallback
    out = []
    for (t, p), n in top:
        x = found.get((t, p), {})
        out.append(ErrorPattern(pattern=x.get("pattern") or f"{t} records predicted as {p}", count=n,
                                example_ids=[r["id"] for r in examples[(t, p)]],
                                suggested_data_fix=x.get("suggested_data_fix") or f"add clearer {t} examples",
                                true_label=t, predicted_label=p))
    return ErrorPatterns(patterns=out, source="llm")


# ---- cascade (H) -----------------------------------------------------------------------
CASCADE_TOLERANCE = 0.005


TAU_GRID = np.round(np.arange(0.3, 0.96, 0.05), 2)


def fit_cascade_chain(card: TaskCard, labels: list[str], val: list[dict], stages: list[dict],
                      only_ids: set[str] | None = None) -> dict | None:
    """Fit one confidence threshold per stage (all but the last) for a chain ordered cheapest first.

    `stages`: dicts with P (validation proba), ids, cost (cost_per_1m_usd) and calibrator (or None), all scored
    on the rows every stage has (the LLM rung's capped sample), optionally limited to `only_ids` so chains
    with and without an LLM stage are compared on the same rows. Among threshold combinations scoring within
    CASCADE_TOLERANCE of the best, take the lowest expected cost per record: every item pays for stage 0, and
    for each later stage it reaches.
    """
    pos = [{i: k for k, i in enumerate(s["ids"])} for s in stages]
    common = [i for i in stages[-1]["ids"] if all(i in p for p in pos) and (only_ids is None or i in only_ids)]
    if len(common) < 30:
        return None
    by_id = {r["id"]: r for r in val}
    y = [by_id[i]["label"] for i in common]
    Ps = []
    for s, p in zip(stages, pos):
        P = s["P"][[p[i] for i in common]]
        Ps.append(s["calibrator"].apply(P) if s.get("calibrator") is not None else P)
    kw = metric_kwargs(card)
    alone = [M.classification_metrics(y, P, labels, **kw)["primary"] for P in Ps]
    costs = [float(s["cost"]) for s in stages]
    n_st, tried = len(stages), []
    for taus in itertools.product(TAU_GRID, repeat=n_st - 1):
        stage = np.zeros(len(common), int)
        P = Ps[0].copy()
        todo = Ps[0].max(1) < taus[0]
        for k in range(1, n_st):
            P[todo], stage[todo] = Ps[k][todo], k
            if k < n_st - 1:
                todo = todo & (Ps[k].max(1) < taus[k])
        reach = [float((stage >= k).mean()) for k in range(n_st)]
        tried.append({"taus": [float(t) for t in taus], "primary": M.classification_metrics(y, P, labels, **kw)["primary"],
                      "shares": [float((stage == k).mean()) for k in range(n_st)],
                      "cost_per_1m_usd": sum(r * c for r, c in zip(reach, costs)), "escalation_rate": reach[1]})
    top = max(t["primary"] for t in tried)
    best = min((t for t in tried if t["primary"] >= top - CASCADE_TOLERANCE),
               key=lambda t: (t["cost_per_1m_usd"], -t["primary"]))
    return {**best, "tau": best["taus"][0], "n": len(common), "ids": common, "alone_same_sample": alone,
            "base_primary_same_sample": alone[0], "llm_primary_same_sample": alone[-1],
            "best_primary_any_tau": top,
            "tau_rule": f"lowest expected cost within {CASCADE_TOLERANCE} of the best threshold combination",
            "sample": "the LLM rung's capped validation sample"}


def score_on_ids(card: TaskCard, labels: list[str], val: list[dict], P: np.ndarray, ids: list[str],
                 calibrator, only_ids: list[str]) -> float:
    """One model's primary metric on a given subset of validation rows."""
    pos = {i: k for k, i in enumerate(ids)}
    by_id = {r["id"]: r for r in val}
    Q = P[[pos[i] for i in only_ids]]
    Q = calibrator.apply(Q) if calibrator is not None else Q
    return M.classification_metrics([by_id[i]["label"] for i in only_ids], Q, labels, **metric_kwargs(card))["primary"]


def fit_cascade(card: TaskCard, labels: list[str], val: list[dict], base_P: np.ndarray, base_ids: list[str],
                llm_P: np.ndarray, llm_ids: list[str], calibrator: TemperatureCalibrator,
                base_cost: float = 0.0, llm_cost: float = 1.0) -> dict | None:
    """Two-stage cascade: base → LLM. With the LLM dearer than the base, lowest cost = least escalation."""
    return fit_cascade_chain(card, labels, val, [
        {"P": base_P, "ids": base_ids, "cost": base_cost, "calibrator": calibrator},
        {"P": llm_P, "ids": llm_ids, "cost": llm_cost, "calibrator": None}])


# ---- final exam ----------------------------------------------------------------------
def final_exam(card: TaskCard, run_dir: Path, sealed_run_dir: Path, model: Candidate, labels: list[str],
               calibrator: TemperatureCalibrator | None, threshold: float | None, emit: Emit) -> dict:
    """Score the chosen model on the sealed test set. Called exactly once per version."""
    rows = read_sealed(sealed_run_dir)
    texts, y = [r["text"] for r in rows], [r["label"] for r in rows]
    P = model.predict_proba(texts)
    if calibrator is not None and not isinstance(model, CascadeH):
        P = calibrator.apply(P)
    kw = metric_kwargs(card)
    m = M.classification_metrics(y, P, labels, **kw)
    if threshold is not None and card.positive_definition:
        # The threshold chosen on validation, applied as deployed. Reported next to the re-fit number.
        pi = labels.index(card.positive_definition)
        ypos = np.array([v == card.positive_definition for v in y])
        flagged = P[:, pi] > threshold
        m["at_val_threshold"] = {"threshold": threshold, "recall": float(flagged[ypos].mean()),
                                 "fpr": float(flagged[~ypos].mean())}
        m.update({k: v for k, v in M.classification_metrics(y, P, labels, threshold=threshold, **kw).items()
                  if k in ("per_class", "macro_f1", "macro_precision", "macro_recall", "accuracy")})
    if isinstance(model, CascadeH):
        m["escalation_rate"] = model.last_escalated / max(len(rows), 1)
        m["stage_shares"] = {name: c / max(len(rows), 1) for name, c in zip(model.names, model.last_stage_counts)}
    np.save(run_dir / "sealed_proba.npy", P)
    (run_dir / "sealed_ids.json").write_text(json.dumps([r["id"] for r in rows]))
    emit("Evaluator", "final", f"Final score on the sealed test set: {card.optimization_metric} {m['primary']:.3f} "
         f"on {len(rows):,} records")
    return m


def baseline_on_sealed(card: TaskCard, run_dir: Path, sealed_run_dir: Path, labels: list[str], llm, emit: Emit,
                       n: int = 300) -> tuple[dict, list[dict]]:
    """Nemotron Ultra zero-shot on a stratified sample of the sealed set (same rows used for comparison)."""
    rows = read_sealed(sealed_run_dir)
    if card.positive_definition:
        # keep every positive so a rare-class metric is measurable, then fill with negatives
        pos = [r for r in rows if r["label"] == card.positive_definition]
        neg = [r for r in rows if r["label"] != card.positive_definition]
        rng = random.Random(0)
        sample = pos[:max(n // 3, 1)] + rng.sample(neg, min(len(neg), n - min(len(pos), max(n // 3, 1))))
        rng.shuffle(sample)
    else:
        sample = stratified_sample(rows, n)
    emit("Evaluator", "baseline", f"Running the Nemotron Ultra zero-shot baseline on {len(sample)} sealed records")
    return score_baseline(card, labels, sample, llm, emit), sample


def teacher_agreement(specialist_pred: list[str], teacher_pred: list[str]) -> dict:
    agree = sum(a == b for a, b in zip(specialist_pred, teacher_pred))
    return {"agreement_rate": agree / max(len(teacher_pred), 1), "n": len(teacher_pred),
            "note": "agreement with Nemotron Ultra's labels, not accuracy"}


def score_rows(card: TaskCard, model: Candidate, rows: list[dict], labels: list[str],
               calibrator: TemperatureCalibrator | None = None) -> tuple[dict, list[str]]:
    P = model.predict_proba([r["text"] for r in rows])
    if calibrator is not None and not isinstance(model, CascadeH):
        P = calibrator.apply(P)
    return M.classification_metrics([r["label"] for r in rows], P, labels, **metric_kwargs(card)), M.predictions(P, labels)


# ---- version gate ------------------------------------------------------------------------
def version_gate(card: TaskCard, new: dict, current: dict | None) -> tuple[bool, str]:
    """A new version deploys only if it passes every threshold and beats the live version on the fixed benchmark."""
    t = card.thresholds
    if new["primary"] < t.primary_min:
        return False, f"{card.optimization_metric} {new['primary']:.3f} is below the target {t.primary_min:.2f}"
    if t.per_class_floor is not None:
        low = {k: v["recall"] for k, v in new["per_class"].items() if v["recall"] < t.per_class_floor}
        if low:
            worst = min(low, key=low.get)
            return False, f"recall for {worst} is {low[worst]:.2f}, below the per-class floor {t.per_class_floor:.2f}"
    if current is not None and new["primary"] <= current["primary"]:
        return False, (f"{card.optimization_metric} {new['primary']:.3f} does not beat the live version's "
                       f"{current['primary']:.3f} on the same sealed test set")
    if current is None:
        return True, f"first version; meets the target with {card.optimization_metric} {new['primary']:.3f}"
    return True, f"beats the live version ({new['primary']:.3f} vs {current['primary']:.3f}) and passes every threshold"


def real_vs_synthetic(card: TaskCard, run_dir: Path, model: Candidate, labels: list[str],
                      calibrator: TemperatureCalibrator | None) -> dict | None:
    train = load_split(run_dir / "train.jsonl")
    n_syn = sum(1 for r in train if r.get("synthetic"))
    if not n_syn:
        return None
    out = {"synthetic_training_rows": n_syn, "real_training_rows": len(train) - n_syn}
    val = [r for r in load_split(run_dir / "val.jsonl") if not r.get("synthetic")]
    if val:
        out["real_validation"] = score_rows(card, model, val, labels, calibrator)[0]["primary"]
    else:
        out["real_validation"] = None
        out["note"] = ("No real labeled data was available: training, validation and the sealed test set are all "
                       "synthetic, so every score here is measured on synthetic data.")
    syn_path = run_dir / "synthetic_eval.jsonl"
    if syn_path.exists():
        syn = load_split(syn_path)
        syn = [r for r in syn if r["label"] in labels]
        if syn:
            m, _ = score_rows(card, model, syn, labels, calibrator)
            out["synthetic_heldout"] = m["accuracy"]
            out["synthetic_heldout_n"] = len(syn)
            out["synthetic_metric"] = "accuracy (held-out synthetic examples are single-class per pattern)"
    return out
