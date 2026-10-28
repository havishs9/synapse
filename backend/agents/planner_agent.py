"""Planner agent: choose candidate families and search ranges from task properties.

`deterministic_plan` encodes the rules (it is the Phase 1 plan and the fallback). `llm_plan` asks Nemotron
Ultra for a structured plan, validates it against the ladder, and falls back to the rules if anything is off.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Callable

from backend.candidates import FAMILIES, RUNG
from backend.schemas import CandidatePlan, CandidateSpec, DatasetStats, TaskCard

Emit = Callable[..., None]

# Search spaces per family: the planner picks values from these.
SPACES: dict[str, dict[str, list]] = {
    "J": {"min_support": [5, 10, 20], "min_precision": [0.8, 0.9]},
    "A": {"model": ["logreg", "svm"], "C": [1.0, 4.0, 16.0], "char": [True, False]},
    "E": {"num_leaves": [15, 31, 63], "learning_rate": [0.05, 0.1], "n_estimators": [300]},
    "I": {"method": ["knn", "centroid"], "k": [10, 25], "backend": ["local", "cloud"]},
    "B": {"C": [1.0, 4.0, 16.0]},
    "C": {"C": [1.0, 4.0, 16.0]},
    "K": {"role": ["ladder_K_primary", "ladder_K_alternative"], "n_examples": [0, 5, 10], "instruction": [0, 1]},
    "L": {"n_examples": [5], "instruction": [1]},
}
NAMES = {"J": "rules", "A": "TF-IDF", "E": "LightGBM", "I": "embedding similarity", "B": "cloud embeddings",
         "C": "local embeddings", "K": "prompted Nemotron Nano/Lightning", "L": "prompted Nemotron Super"}
ALWAYS_EXCLUDED = {
    "F": "span extraction only; this task outputs one label per input",
    "D": "fine-tuning an encoder on CPU doesn't fit the build time budget",
    "G": "LoRA tier is STRETCH and off by default (needs a paid dedicated endpoint)",
}


def expand(family: str, space: dict[str, list], limit: int | None = None) -> list[dict]:
    keys = sorted(space)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*(space[k] for k in keys))]
    if family == "I":   # k only matters for knn
        seen, out = set(), []
        for c in combos:
            if c.get("method") == "centroid":
                c = {**c, "k": None}
            key = json.dumps(c, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append(c)
        combos = out
    return combos[:limit] if limit else combos


def deterministic_plan(card: TaskCard, stats: DatasetStats | None, *, families: list[str] | None = None,
                       limit_per_family: int | None = None) -> CandidatePlan:
    excluded = dict(ALWAYS_EXCLUDED)
    spaces = {k: {kk: list(vv) for kk, vv in v.items()} for k, v in SPACES.items()}
    if card.input_type == "log_window":
        chosen = ["E", "J", "A", "K"]
        excluded.update({
            "I": "log windows are long event sequences; sentence embeddings truncate them and lose event counts",
            "B": "same as I, and each window would cost one embedding call",
            "C": "same as I",
            "L": "rung K already covers prompted LLMs for this task; Super costs 5x more per call",
        })
        spaces["K"] = {"role": ["ladder_K_alternative"], "n_examples": [0, 3], "instruction": [1]}
        reason = {"E": "window features (event counts, levels, duration) suit structured logs",
                  "J": "single events can be strong rules for failures", "A": "masked log text as a text baseline",
                  "K": "prompted Lightning with similar labeled windows, for comparison"}
        because = "inputs are structured log windows with rare anomalies"
    else:
        chosen = ["J", "A", "I", "C", "B", "E", "K", "L"]
        reason = {"J": "short, keyword-heavy descriptions often have decisive words",
                  "A": "TF-IDF is strong on short keyword-heavy text", "I": "embedding similarity needs no training",
                  "C": "local embeddings + classifier, offline", "B": "Qwen3-Embedding-8B handles paraphrases",
                  "E": "LightGBM on compressed text features, for comparison",
                  "K": "prompted Nemotron Nano/Lightning with retrieved examples, for fuzzy categories",
                  "L": "prompted Nemotron Super for harder cases"}
        because = (f"descriptions are short and keyword-heavy with "
                   f"{stats.n_classes if stats else len(card.labels)} categories")
    if card.deployment == "offline":
        for f in ("B", "K", "L"):
            if f in chosen:
                chosen.remove(f)
                excluded[f] = "calls a cloud API at inference time; the task must run offline"
        if "I" in spaces:
            spaces["I"]["backend"] = ["local"]
    if not card.needs_reason and "L" in chosen:
        chosen.remove("L")
        excluded["L"] = "no reasons needed; explanation-heavy prompted Super dropped"
    if families:
        for f in list(chosen):
            if f not in families:
                chosen.remove(f)
                excluded.setdefault(f, "not in this plan")
    names = [f"{NAMES[f]} ({f})" for f in chosen]
    summary = "Trying " + (", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]) + f", because {because}"
    cands = []
    for f in chosen:
        for i, params in enumerate(expand(f, spaces[f], limit_per_family), 1):
            params = {k: v for k, v in params.items() if v is not None}
            cands.append(CandidateSpec(id=f"{f}-{i:02d}", family=f, rung=RUNG[f], params=params,
                                       search_space=spaces[f], reason=reason.get(f, "")))
    return CandidatePlan(candidates=cands, excluded={k: v for k, v in excluded.items() if k not in chosen},
                         summary=summary, planner_source="deterministic_fallback")


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "families": {"type": "array", "items": {"type": "object", "properties": {
            "family": {"type": "string", "enum": sorted(FAMILIES)},
            "reason": {"type": "string"},
            "search_space": {"type": "object", "additionalProperties": {"type": "array", "items": {}}}},
            "required": ["family", "reason", "search_space"], "additionalProperties": False}},
        "excluded": {"type": "object", "additionalProperties": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["families", "excluded", "summary"], "additionalProperties": False,
}


def llm_plan(card: TaskCard, stats: DatasetStats, llm, emit: Emit, max_configs: int = 40) -> CandidatePlan:
    fallback = deterministic_plan(card, stats)
    ladder = {
        "J": "keyword/event rules, microseconds", "A": "TF-IDF + logistic regression / linear SVM",
        "E": "LightGBM on engineered features (window features for logs)", "I": "embedding kNN or centroids (local or cloud)",
        "B": "Qwen3-Embedding-8B (cloud) + logistic regression; requires cloud_ok",
        "C": "local MiniLM embeddings + logistic regression; offline", "K": "prompted Nemotron Nano or Lightning + retrieved examples",
        "L": "prompted Nemotron Super", "F": "span tagger (not implemented)", "D": "fine-tuned encoder (not implemented)",
        "G": "LoRA LLM (STRETCH, off)"}
    prompt = (
        "You plan which candidate model families to benchmark for a classification task. Pick 3 to 6 families "
        "and narrow each search space to values from the allowed lists. Exclude the rest with a one-line reason.\n"
        f"Task card: {card.model_dump_json(include={'description', 'input_type', 'output_type', 'error_preference', 'optimization_metric', 'needs_reason', 'deployment', 'latency_budget_ms', 'monthly_volume'})}\n"
        f"Labels: {[l.name for l in card.labels]}\n"
        f"Dataset stats: {stats.model_dump_json()}\n"
        f"Ladder: {json.dumps(ladder)}\n"
        f"Allowed search values per family: {json.dumps(SPACES)}\n"
        f"Rules: offline tasks can't use B, cloud I, K or L. F, D and G are not implemented and must be excluded. "
        f"Log windows are long; prefer engineered features. Keep the total configs under {max_configs}.\n"
        "summary: one plain-English sentence like 'Trying rules (J), TF-IDF (A) ... because ...'.")
    try:
        res = llm.chat("main_chat_planner_teacher_baseline", [{"role": "user", "content": prompt}], agent="Planner",
                       purpose="plan", max_tokens=6000, temperature=0.2,
                       response_format={"type": "json_schema", "json_schema": {"name": "plan", "schema": PLAN_SCHEMA}})
        raw = res.json()
        cands, excluded = [], dict(ALWAYS_EXCLUDED)
        for fam in raw["families"]:
            f = fam["family"]
            if f not in FAMILIES:
                continue
            if card.deployment == "offline" and f in ("B", "K", "L"):
                excluded[f] = "calls a cloud API; the task must run offline"
                continue
            space = {}
            for k, allowed_vals in SPACES[f].items():
                picked = [v for v in fam["search_space"].get(k, []) if v in allowed_vals]
                space[k] = picked or allowed_vals[:1]
            if card.deployment == "offline" and f == "I":
                space["backend"] = ["local"]
            for i, params in enumerate(expand(f, space), 1):
                params = {k: v for k, v in params.items() if v is not None}
                cands.append(CandidateSpec(id=f"{f}-{i:02d}", family=f, rung=RUNG[f], params=params,
                                           search_space=space, reason=fam["reason"]))
        if not cands or len(cands) > max_configs * 2:
            raise ValueError(f"plan had {len(cands)} configs")
        chosen = {c.family for c in cands}
        if card.deployment == "cloud_ok" and not chosen & {"K", "L"}:
            # The cascade (H) is always evaluated on top of the best single candidate; it needs an LLM rung.
            k = next(c for c in fallback.candidates if c.family == "K")
            space = k.search_space
            for i, params in enumerate(expand("K", space), 1):
                cands.append(CandidateSpec(id=f"K-{i:02d}", family="K", rung=RUNG["K"], params=params,
                                           search_space=space, reason="added so the cascade (H) can escalate "
                                           "uncertain items to a prompted Nemotron model"))
            chosen.add("K")
            raw["summary"] += "; prompted Nemotron (K) added so the cascade can be evaluated"
        for f, why in raw.get("excluded", {}).items():
            if f not in chosen:
                excluded[f] = why
        for f in set(RUNG) - chosen - set(excluded) - {"H"}:
            excluded[f] = "not chosen by the planner"
        return CandidatePlan(candidates=cands, excluded=excluded, summary=raw["summary"], planner_source="llm")
    except Exception as exc:
        emit("Planner", "plan", f"Planner output wasn't usable ({type(exc).__name__}); using the rule-based plan")
        return fallback


def run_planner(card: TaskCard, stats_path: Path, run_dir: Path, emit: Emit, llm=None, *,
                families: list[str] | None = None, limit_per_family: int | None = None) -> CandidatePlan:
    stats = DatasetStats.read(stats_path) if stats_path.exists() else None
    if llm is not None and families is None:
        plan = llm_plan(card, stats, llm, emit)
    else:
        plan = deterministic_plan(card, stats, families=families, limit_per_family=limit_per_family)
    plan.write(run_dir / "candidate_plan.json")
    emit("Planner", "plan", f"Planner: {plan.summary}", data_ref="candidate_plan.json", kind="handoff",
         data={"families": sorted({c.family for c in plan.candidates}), "configs": len(plan.candidates),
               "source": plan.planner_source})
    return plan
