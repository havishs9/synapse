"""Product routes behind the Phase 3 UI (docs/TEAM_PLAN.md §3): intake, compare, corrections, improve.

- Intake (spec 01 §2.2): Nemotron Ultra matches the request to a task and writes one message with at most 7
  clarifying questions; the answers become a task card, and every answer shows the plan change it causes.
- Compare (spec 01 §2.6): the same input to Nemotron Ultra zero-shot and the specialist at the same time, with
  measured latency, the cost of each call and a yearly projection at the task card's monthly volume.
- Corrections and improve (spec 01 §2.9): the user's corrections (or wrong predictions on held-back real
  records) train a new version that deploys only if it passes the version gate (backend/improve.py).
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import config
from backend.agents import evaluator_agent as ev
from backend.auth import User, current_user, require_edit, require_view, uid
from backend.candidates import CascadeH
from backend.demo_tasks import DEMO_TASKS
from backend.improve import Improver, ImproveUnavailable, recorded_improve
from backend.llm_client import LLMClient, call_cost_usd
from backend.schemas import TaskCard
from backend.sealed import load_split
from backend.serving import server as spec_server
from backend.serving.predictor import InputError
from backend.versions import registry

router = APIRouter(prefix="/api")
MAIN_ROLE = "main_chat_planner_teacher_baseline"
MAX_QUESTIONS = 7          # DECISION D5: one message, at most 7 questions
_llm: LLMClient | None = None
_llm_lock = threading.Lock()


def llm() -> LLMClient:
    """Interactive LLM client for intake and compare; counted by the daily demo guard in main.py."""
    global _llm
    with _llm_lock:
        if _llm is None:
            _llm = LLMClient(budget_usd=float("inf"))
            _llm.RETRY_ATTEMPTS = 2          # interactive: fail fast to the cached fallback, don't wait ~90 s
        return _llm


def spent_usd() -> float:
    return _llm.spend.spent_usd if _llm else 0.0


def _guard():
    from backend.main import demo_guard      # main imports this module; import late
    demo_guard()


class _Uncached:
    """Client view that never answers from the disk cache, so compare measures a real call."""

    def __init__(self, inner):
        self._inner = inner

    def chat(self, *args, **kwargs):
        return self._inner.chat(*args, **{**kwargs, "use_cache": False})

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ---- intake ---------------------------------------------------------------------------
def _recorded_card(task_id: str) -> dict | None:
    from backend.main import recorded_runs
    run = recorded_runs().get(task_id)
    p = config.runs_dir() / run / "task_card.json" if run else None
    return json.loads(p.read_text()) if p and p.exists() else None


def base_card(task_id: str) -> TaskCard:
    """The task's default card. Labels come from the dataset; without the raw data (replay deployments) they
    come from the recorded run's task card."""
    card = DEMO_TASKS[task_id]()
    if not card.labels:
        rec = _recorded_card(task_id)
        if rec:
            card = card.model_copy(update={"labels": TaskCard.model_validate(rec).labels})
    return card


KEYWORDS = {
    "procurement": ["purchase", "procure", "spend", "contract", "invoice", "vendor", "categor", "buying", "expense"],
    "hdfs_logs": ["log", "anomal", "hdfs", "server", "incident", "outage", "failure", "syslog"],
    "support_tickets": ["support", "ticket", "customer", "intent", "route", "routing", "helpdesk", "bank", "message"],
}
TASK_BLURB = {
    "procurement": "federal purchase records (USAspending.gov), sorted into spending categories",
    "hdfs_logs": "HDFS system logs (LogHub), each block's log window flagged as normal or anomalous",
    "support_tickets": "bank customer support messages (Banking77), routed to one of 77 intents",
}


def match_task_fallback(text: str) -> str | None:
    t = text.lower()
    scores = {k: sum(w in t for w in ws) for k, ws in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else None


def _fmt_int(n: int) -> str:
    return f"{n / 1e6:g} million" if n >= 1_000_000 else f"{n / 1e3:g}k" if n >= 1000 else str(n)


def questions_for(card: TaskCard) -> list[dict]:
    """The seven questions of spec 01 §2.2 with answer options that map deterministically onto the task card.
    Every question also takes a free-text answer."""
    binary = card.output_type == "binary"
    cap = config.credit_budget_usd()
    pos = next((l for l in card.labels if l.name == card.positive_definition), None)
    vols = sorted({100_000, 1_000_000, card.monthly_volume or config.demo_monthly_volume()})
    lats = sorted({20, 50, 500, int(card.latency_budget_ms or 50)})
    budgets = sorted({round(cap / 4, 2), round(cap / 2, 2), cap})
    q = [
        {"id": "labels", "text": (f"Is the positive case \"{pos.name}\": {pos.definition.lower()}?" if binary and pos else
                                  f"I'll use the {len(card.labels)} categories from the dataset's label mapping. Do they fit?"),
         "options": [{"value": "keep", "label": "Yes, use them"}], "default": "keep"},
        {"id": "error_preference",
         "text": ("Which mistake is worse: missing a real anomaly or raising a false alarm?" if binary else
                  "Do all categories matter equally, or are some costlier to get wrong?"),
         "options": ([{"value": "recall_first", "label": "Missing one is worse"},
                      {"value": "precision_first", "label": "False alarms are worse"},
                      {"value": "balanced", "label": "Both equally"}] if binary else
                     [{"value": "balanced", "label": "All equally"},
                      {"value": "recall_first", "label": "Some categories are costlier to miss"}]),
         "default": card.error_preference},
        {"id": "needs_reason", "text": "Do you need just the category, or the category with a short reason?",
         "options": [{"value": False, "label": "Just the category"}, {"value": True, "label": "Category and a reason"}],
         "default": card.needs_reason},
        {"id": "monthly_volume", "text": "Roughly how many items a month?",
         "options": [{"value": v, "label": _fmt_int(v)} for v in vols],
         "default": card.monthly_volume or config.demo_monthly_volume()},
        {"id": "latency_budget_ms", "text": "What's the latency budget per item?",
         "options": [{"value": v, "label": f"Under {v} ms"} for v in lats] + [{"value": None, "label": "No limit"}],
         "default": card.latency_budget_ms},
        {"id": "deployment", "text": "Must it run fully on your own servers, or are cloud API calls allowed at prediction time?",
         "options": [{"value": "cloud_ok", "label": "Cloud calls are fine"},
                     {"value": "offline", "label": "Our own servers only"}], "default": card.deployment},
        {"id": "build_budget_usd", "text": "What's the build budget for model calls?",
         "options": [{"value": b, "label": f"${b:.2f}"} for b in budgets], "default": cap},
    ]
    return q[:MAX_QUESTIONS]


INTAKE_SCHEMA = {
    "type": "json_schema", "json_schema": {"name": "intake", "strict": True, "schema": {
        "type": "object", "additionalProperties": False,
        "required": ["task_id", "why", "intro", "questions"],
        "properties": {
            "task_id": {"type": "string", "enum": [*DEMO_TASKS, "none"]},
            "why": {"type": "string"},
            "intro": {"type": "string"},
            "questions": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["id", "text"],
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}}}},
        }}}}


def _llm_intake(text: str, samples: list[str]) -> dict | None:
    tasks = "\n".join(f"- {k}: {v}" for k, v in TASK_BLURB.items())
    prompt = (
        "You are the intake step of Synapse, which builds small specialist models for repetitive classification "
        f"tasks. It can build from these vetted datasets today:\n{tasks}\n\nThe user wrote:\n\"\"\"{text[:2000]}\"\"\"\n"
        + (f"Sample rows they pasted:\n" + "\n".join(f"- {s[:200]}" for s in samples[:10]) + "\n" if samples else "")
        + "\nPick the task_id whose data matches the request, or \"none\". Write a one-sentence intro that says "
        "which task you'll build and that a few answers set the quality bar. Then rewrite each of these questions "
        "in plain, friendly words for this user's task, keeping its id and meaning (one sentence each):\n"
        + "\n".join(f"- {q['id']}: {q['text']}" for q in questions_for(base_card("procurement"))))
    try:
        res = llm().chat(MAIN_ROLE, [{"role": "user", "content": prompt}], agent="Planner", purpose="intake_questions",
                         max_tokens=900, temperature=0.0, thinking=False, response_format=INTAKE_SCHEMA)
        return res.json()
    except Exception:
        return None


class IntakeStartIn(BaseModel):
    text: str = Field(max_length=8000)
    samples: list[str] = Field(default_factory=list, max_length=50)


@router.post("/intake/start")
def intake_start(body: IntakeStartIn, user: User | None = Depends(current_user)):
    """One message with at most 7 clarifying questions, written by Nemotron Ultra (canned wording if it's
    unreachable or the daily demo budget is used up)."""
    out, source = None, "fallback"
    try:
        _guard()
        out = _llm_intake(body.text, body.samples)
    except HTTPException:
        out = None
    task_id = (out or {}).get("task_id")
    if task_id not in DEMO_TASKS:
        task_id = None if out else match_task_fallback(body.text)
    if out:
        source = "llm"
    if task_id is None:
        return {"task_id": None, "source": source, "questions": [],
                "message": "I can build specialists from three vetted datasets today: "
                           + "; ".join(TASK_BLURB.values()) + ". Building from your own uploaded data is "
                           "coming next. Pick one of the examples, or describe one of these tasks."}
    card = base_card(task_id)
    qs = questions_for(card)
    llm_text = {q.get("id"): q.get("text") for q in (out or {}).get("questions", []) if isinstance(q, dict)}
    for q in qs:
        if source == "llm" and isinstance(llm_text.get(q["id"]), str) and 8 < len(llm_text[q["id"]]) < 300:
            q["text"] = llm_text[q["id"]].strip()
    intro = (out or {}).get("intro") if source == "llm" else None
    return {"task_id": task_id, "task_name": card.task_name, "source": source, "questions": qs,
            "categories": [l.name for l in card.labels],
            "message": intro or f"I'll build a {card.task_name.lower()} from {TASK_BLURB[task_id]}. "
                                "A few answers set the quality bar and the plan.",
            "samples_hint": "Paste 10 to 20 sample rows of your real data (labels not needed): models learn the shape "
                            "of the data they're trained on, so the build checks how well the dataset matches it.",
            "replay": config.app_mode() == "replay"}


_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}


def parse_number(text: str) -> float | None:
    """'about 2 million' → 2e6, '500k' → 5e5, '50 ms' → 50, '$1.50' → 1.5, '2,000,000' → 2e6."""
    m = re.search(r"(\d[\d,]*\.?\d*)\s*(k|thousand|mm|m|million|b|billion)?\b", text.lower().replace("$", ""))
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return n * _MULT.get(m.group(2) or "", 1)


def _parse_text_answers(texts: dict[str, str]) -> dict[str, Any]:
    """Map free-text answers to card fields: Nemotron Ultra first, number parsing as the fallback."""
    out: dict[str, Any] = {}
    if not texts:
        return out
    prompt = ("Map each answer to a task-card field value. Fields: error_preference (recall_first | precision_first "
              "| balanced), needs_reason (true | false), monthly_volume (integer items per month), latency_budget_ms "
              "(number, null for no limit), deployment (offline | cloud_ok), build_budget_usd (number). Use null when "
              "an answer doesn't say. Answers:\n" + "\n".join(f"- {k}: {v[:300]}" for k, v in texts.items())
              + '\nReturn JSON with only these keys: {"<field>": <value>}')
    try:
        _guard()
        res = llm().chat(MAIN_ROLE, [{"role": "user", "content": prompt}], agent="Planner", purpose="intake_answers",
                         max_tokens=300, thinking=False, response_format={"type": "json_object"})
        parsed = res.json()
        out = {k: v for k, v in parsed.items() if k in texts and v is not None}
    except Exception:
        pass
    for k, v in texts.items():
        if k not in out and k in ("monthly_volume", "latency_budget_ms", "build_budget_usd"):
            n = parse_number(v)
            if n is not None:
                out[k] = n
    return out


def apply_answers(card: TaskCard, answers: dict[str, Any], notes: dict[str, str]) -> tuple[TaskCard, list[dict]]:
    """Apply answers to the default card. Every answer returns the plan change it causes, worded from what
    the planner, frontier choice and version gate actually do with that field."""
    u: dict[str, Any] = {}
    changes: list[dict] = []
    binary = card.output_type == "binary"

    def change(qid: str, answer: str, line: str):
        changes.append({"question": qid, "answer": answer, "change": line})

    if notes.get("labels"):
        u["description"] = f"{card.description} User note: {notes['labels'][:500]}"
        change("labels", notes["labels"], "Your note is added to the task description the planner and teacher read; "
               "categories still come from the dataset's label mapping")
    elif binary:
        change("labels", "Use them", f"Positive case: {card.positive_definition}")
    else:
        change("labels", "Use them", f"{len(card.labels)} categories; macro-F1 weights every category equally")

    ep = answers.get("error_preference", card.error_preference)
    if ep not in ("recall_first", "precision_first", "balanced"):
        ep = card.error_preference
    u["error_preference"] = ep
    if binary and ep == "recall_first":
        u.update(optimization_metric="recall_at_fpr", fpr_target=0.01)
        change("error_preference", "Missing one is worse", "Metric switched to recall at 1% false-positive rate; the "
               "recommendation is the best detector that meets the target, cost only breaks ties")
    elif binary and ep == "precision_first":
        u.update(optimization_metric="recall_at_fpr", fpr_target=0.001)
        change("error_preference", "False alarms are worse", "Metric switched to recall at 0.1% false-positive rate "
               "(false alarms capped 10× harder); the cheapest candidate meeting the target is recommended")
    elif binary:
        u.update(optimization_metric="pr_auc", fpr_target=None)
        change("error_preference", "Both equally", "Metric switched to PR-AUC, which weighs misses and false alarms "
               "together (never plain accuracy on rare anomalies)")
    elif ep == "recall_first":
        u.update(optimization_metric="macro_f1",
                 thresholds=card.thresholds.model_copy(update={"per_class_floor": 0.30}))
        change("error_preference", "Some categories are costlier to miss", "Version gate adds a recall floor of 0.30 "
               "for every category; the recommendation is the most accurate candidate meeting the target, not the cheapest")
    else:
        u.update(optimization_metric="macro_f1", thresholds=card.thresholds.model_copy(update={"per_class_floor": None}))
        change("error_preference", "All equally", "Metric: macro-F1; the cheapest candidate that meets the "
               f"{card.thresholds.primary_min:.2f} target is recommended")

    # What the planner tries per input type (planner_agent.plan_deterministic): log windows never get the
    # embedding rungs or Super, so the lines below only name candidates that would really be in the plan.
    logs = card.input_type == "log_window"
    nr = answers.get("needs_reason", card.needs_reason)
    u["needs_reason"] = bool(nr)
    if nr:
        line = ("Each prediction carries a reason: feature-based for classic models, a one-line rationale from "
                "prompted rungs")
    elif logs:
        line = "Predictions return the verdict and score only; no reasons are generated"
    else:
        line = "Explanation-heavy candidates (prompted Nemotron Super, L) dropped; predictions return the category only"
    change("needs_reason", "Category and a reason" if nr else "Just the category", line)

    vol = answers.get("monthly_volume")
    vol = int(vol) if isinstance(vol, (int, float)) and vol > 0 else (card.monthly_volume or config.demo_monthly_volume())
    u["monthly_volume"] = vol
    change("monthly_volume", f"{vol:,} a month", f"Cost projections and compare mode use {_fmt_int(vol)} records a "
           f"month ({_fmt_int(vol * 12)} a year)")

    if "latency_budget_ms" in answers:
        lat = answers["latency_budget_ms"]
        lat = float(lat) if isinstance(lat, (int, float)) and lat > 0 else None
    else:
        lat = card.latency_budget_ms
    u["latency_budget_ms"] = lat
    if lat is None:
        change("latency_budget_ms", "No limit", "No latency limit: any rung can be recommended, including prompted "
               "Nemotron on its own")
    else:
        change("latency_budget_ms", f"Under {lat:g} ms", f"Candidates with p50 latency over {lat:g} ms can't be "
               "recommended" + ("; prompted LLM rungs (about a second per call) can only answer escalations inside a "
                                "cascade" if lat < 1000 else ""))

    dep = answers.get("deployment", card.deployment)
    dep = dep if dep in ("offline", "cloud_ok") else card.deployment
    u["deployment"] = dep
    if dep == "offline":
        change("deployment", "Our own servers only", (
            "Cloud candidates removed: prompted Nemotron (K); rules, TF-IDF and LightGBM on window features stay; "
            "no cascade to Nemotron" if logs else
            "Cloud candidates removed: Qwen3 embeddings (B), cloud embedding kNN (I), prompted Nemotron (K, L); "
            "local embeddings (C) and classic models stay; no cascade to Nemotron"))
    else:
        change("deployment", "Cloud calls are fine", (
            "Prompted Nemotron (K) competes, and a cascade can send hard windows to it" if logs else
            "Cloud candidates compete: Qwen3 embeddings (B) and prompted Nemotron (K, L), and a cascade can send "
            "hard cases to Nemotron"))

    cap = config.credit_budget_usd()
    b = answers.get("build_budget_usd")
    b = float(b) if isinstance(b, (int, float)) and b > 0 else cap
    u["build_budget_usd"] = min(b, cap)
    change("build_budget_usd", f"${b:.2f}", f"LLM spend for this build stops at ${min(b, cap):.2f}"
           + (f" (the server caps one build at ${cap:.2f})" if b > cap else ""))

    t = answers.get("target")
    if isinstance(t, (int, float)) and 0 < t <= 1:
        u["thresholds"] = u.get("thresholds", card.thresholds).model_copy(update={"primary_min": float(t)})
        change("target", f"{t:g}", f"Quality bar: {u.get('optimization_metric', card.optimization_metric)} at least "
               f"{t:g}; the version gate rejects any version below it on the sealed test set")

    new = card.model_copy(update=u)
    new = TaskCard.model_validate({**new.model_dump(), "plan_changes": [c["change"] for c in changes]})
    return new, changes


class IntakeCardIn(BaseModel):
    task_id: str
    answers: dict[str, Any] = Field(default_factory=dict)      # question id → chosen option value
    texts: dict[str, str] = Field(default_factory=dict)        # question id → free-text answer
    samples: list[str] = Field(default_factory=list, max_length=50)


@router.post("/intake/card")
def intake_card(body: IntakeCardIn, user: User | None = Depends(current_user)):
    if body.task_id not in DEMO_TASKS:
        raise HTTPException(404, "Unknown task.")
    texts = {k: v.strip() for k, v in body.texts.items() if isinstance(v, str) and v.strip()}
    notes = {"labels": texts.pop("labels")} if "labels" in texts else {}
    answers = {**body.answers, **_parse_text_answers(texts)}
    card, changes = apply_answers(base_card(body.task_id), answers, notes)
    samples = [s.strip() for s in body.samples if s.strip()][:20]
    if samples:
        card = card.model_copy(update={"sample_inputs": samples})
    return {"card": card.model_dump(), "plan_changes": changes, "replay": config.app_mode() == "replay"}


# ---- specialist helpers ------------------------------------------------------------------
def _spec(sid: str, user: User | None):
    if not registry.exists(sid):
        raise HTTPException(404, f"No specialist '{sid}'.")
    v = registry.load(sid)
    require_view(v, user)
    return v


def _live(v):
    rec = registry.live(v)
    if rec is None:
        raise HTTPException(503, "This specialist has no live version yet.")
    return rec


def _run_files(run_id: str) -> tuple[TaskCard | None, dict, dict]:
    d = config.runs_dir() / run_id
    card = TaskCard.read(d / "task_card.json") if (d / "task_card.json").exists() else None
    rc = json.loads((d / "report_card.json").read_text()) if (d / "report_card.json").exists() else {}
    rep = json.loads((d / "eval_report.json").read_text()) if (d / "eval_report.json").exists() else {}
    return card, rc, rep


# ---- compare -----------------------------------------------------------------------------
class CompareIn(BaseModel):
    input: str = Field(max_length=200_000)


def _stage_costs(rc: dict, rep: dict) -> dict[str, float]:
    pts = rep.get("pareto_points") or rc.get("pareto_points") or []
    return {p["cand"]: p["cost_per_1m_usd"] for p in pts if p.get("cost_per_1m_usd") is not None}


def _ultra(card: TaskCard, labels: list[str], text: str) -> dict:
    """Nemotron Ultra zero-shot on one input, using the task card as the prompt (the report's baseline prompt).
    A live call is measured; if Nemotron is unreachable, a cached answer for the same prompt is shown as cached."""
    api_id = config.model_id(MAIN_ROLE)
    model = ev.make_baseline(card, labels, _Uncached(llm()))
    model.ctx.needs_reason = True                # compare shows both reasons
    t0 = time.perf_counter()
    out = model.predict_one(text)
    wall = (time.perf_counter() - t0) * 1000
    cached = False
    if out.get("label") is None:
        offline = LLMClient(budget_usd=0.0)       # budget 0: answers only from the disk cache, never calls out
        model = ev.make_baseline(card, labels, offline)
        model.ctx.needs_reason = True
        out = model.predict_one(text)
        if out.get("label") is None:
            return {"error": "Nemotron Ultra didn't answer and there's no cached answer for this input. Try again."}
        cached = True
    call = model.calls[-1]
    return {"model": config.models()[MAIN_ROLE]["display_name"], "label": out.get("label"),
            "confidence": out.get("confidence"), "reason": out.get("reason"), "cached": cached,
            "latency_ms": call["latency_ms"] if cached else wall,
            "cost_usd": call_cost_usd(api_id, call["prompt_tokens"], call["completion_tokens"]),
            "prompt_tokens": call["prompt_tokens"], "completion_tokens": call["completion_tokens"],
            "cost_method": f"measured tokens × list price for {api_id} (config/pricing.yaml)"}


def _specialist_call(sid: str, version: int, text: str, costs: dict[str, float], bundle: dict) -> dict:
    pred = spec_server.predictor(sid, version)
    t0 = time.perf_counter()
    out = pred.predict([text], with_reason=True)[0]
    wall = (time.perf_counter() - t0) * 1000
    stage = out.get("answered_by") or bundle.get("candidate")
    per_1m = costs.get(stage) if stage in costs else bundle.get("cost_per_1m_usd")
    return {**out, "latency_ms": wall, "model_latency_ms": out.get("latency_ms"),
            "cost_usd": per_1m / 1e6 if per_1m is not None else None, "stage": stage,
            "cost_method": (f"measured cost per 1M predictions of {stage} (the stage that answered), from the build's "
                            "run files, ÷ 1M" if out.get("answered_by") else
                            "measured cost per 1M predictions from the build's run files, ÷ 1M")}


@router.post("/specialists/{sid}/compare")
def compare(sid: str, body: CompareIn, user: User | None = Depends(current_user)):
    _guard()
    v = _spec(sid, user)
    live = _live(v)
    card, rc, rep = _run_files(live.run_id)
    if card is None:
        raise HTTPException(503, f"The task card for v{live.version} isn't on this server.")
    bundle = registry.bundle_meta(sid, live.version)
    labels = bundle["labels"]
    try:
        from backend.serving.predictor import validate
        validate(body.input, bundle["input_type"], bundle.get("expected_format") or "One text record")
    except InputError as exc:
        raise HTTPException(422, str(exc))
    with ThreadPoolExecutor(max_workers=2) as ex:      # both calls at the same time
        f_spec = ex.submit(_specialist_call, sid, live.version, body.input, _stage_costs(rc, rep), bundle)
        f_ultra = ex.submit(_ultra, card, labels, body.input)
        try:
            spec_out = f_spec.result()
        except InputError as exc:
            raise HTTPException(422, str(exc))
        ultra_out = f_ultra.result()

    volume_src = "task card" if card.monthly_volume else "DEMO_MONTHLY_VOLUME (the task card has no monthly volume)"
    volume = card.monthly_volume or config.demo_monthly_volume()
    base_1m = (rc.get("baseline") or rep.get("baseline") or {}).get("cost_per_1m_usd")
    spec_1m = bundle.get("cost_per_1m_usd") if bundle.get("cost_per_1m_usd") is not None else rc.get("cost_per_1m_usd")
    yearly = volume * 12 / 1e6
    projection = None
    if base_1m is not None and spec_1m is not None:
        projection = {
            "monthly_volume": volume, "volume_source": volume_src,
            "nemotron_yearly_usd": base_1m * yearly, "specialist_yearly_usd": spec_1m * yearly,
            "nemotron_per_1m_usd": base_1m, "specialist_per_1m_usd": spec_1m,
            "method": (f"cost per 1M predictions measured in the build (Nemotron Ultra on {rc.get('baseline', {}).get('n', 'the')} "
                       "sealed records; the specialist with its measured cascade split) × monthly volume × 12 ÷ 1M. "
                       "Marginal cost: the shared Serverless endpoint's hourly cost is spread over all specialists."),
        }
    return {"specialist": {"name": f"{v.display_name} v{live.version}", **spec_out}, "nemotron": ultra_out,
            "projection": projection, "agree": ultra_out.get("label") == spec_out.get("label")}


# ---- corrections -----------------------------------------------------------------------
def _corrections_path(sid: str, user: User | None) -> Path:
    d = config.artifacts_dir() / "corrections" / sid
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{uid(user) or 'local'}.json"


def _load_corrections(sid: str, user: User | None) -> list[dict]:
    p = _corrections_path(sid, user)
    return json.loads(p.read_text()) if p.exists() else []


def _save_corrections(sid: str, user: User | None, rows: list[dict]) -> None:
    _corrections_path(sid, user).write_text(json.dumps(rows, indent=1))


class CorrectionIn(BaseModel):
    input: str = Field(max_length=200_000)
    predicted_label: str
    corrected_label: str
    source: str = "user"


class CorrectionsIn(BaseModel):
    corrections: list[CorrectionIn] = Field(max_length=2000)


@router.get("/specialists/{sid}/corrections")
def list_corrections(sid: str, user: User | None = Depends(current_user)):
    _spec(sid, user)
    return {"corrections": _load_corrections(sid, user)}


@router.post("/specialists/{sid}/corrections")
def add_corrections(sid: str, body: CorrectionsIn, user: User | None = Depends(current_user)):
    v = _spec(sid, user)
    labels = registry.bundle_meta(sid, _live(v).version)["labels"]
    rows = _load_corrections(sid, user)
    have = {(r["input"], r["corrected_label"]) for r in rows}
    for c in body.corrections:
        if c.corrected_label not in labels:
            raise HTTPException(422, f"'{c.corrected_label}' isn't one of this specialist's labels.")
        if not c.input.strip() or (c.input, c.corrected_label) in have:
            continue
        have.add((c.input, c.corrected_label))
        rows.append({"input": c.input, "predicted_label": c.predicted_label, "corrected_label": c.corrected_label,
                     "timestamp": time.time(), "source": c.source})
    _save_corrections(sid, user, rows)
    return {"corrections": rows}


@router.delete("/specialists/{sid}/corrections")
def clear_corrections(sid: str, index: int | None = None, user: User | None = Depends(current_user)):
    _spec(sid, user)
    rows = _load_corrections(sid, user)
    rows = [] if index is None else [r for i, r in enumerate(rows) if i != index]
    _save_corrections(sid, user, rows)
    return {"corrections": rows}


_holdback_cache: dict[tuple[str, int], dict] = {}


@router.get("/specialists/{sid}/holdback")
def holdback(sid: str, limit: int = 200, user: User | None = Depends(current_user)):
    """Held-back real labeled records (never in train, validation or the sealed test) that the live version gets
    wrong: the demo's source of "user corrections". Only records the cheap first stage answers on its own are
    scored, so this costs no model calls; their labels equal the full specialist's."""
    v = _spec(sid, user)
    live = _live(v)
    key = (sid, live.version)
    if key not in _holdback_cache:
        path = None
        for run_id in [live.run_id] + [r.run_id for r in sorted(v.versions, key=lambda r: r.version)]:
            p = config.runs_dir() / run_id / "holdback.jsonl"
            if p.exists():
                path = p
                break
        if path is None:
            raise HTTPException(404, "No held-back records are stored for this specialist (logs can't be committed "
                                     "raw). Correct predictions from the input box instead.")
        rows = load_split(path)
        pred = spec_server.predictor(sid, live.version)
        model, labels = pred.model, pred.labels
        texts = [r["text"] for r in rows]
        if isinstance(model, CascadeH):
            P = model.base_proba(texts)
            keep = np.where(P.max(axis=1) >= model.taus[0])[0]
        elif model.uses_cloud:
            raise HTTPException(409, "This specialist calls a cloud model on every prediction; correct predictions "
                                     "from the input box instead.")
        else:
            P = pred._calibrate(model.predict_proba(texts))
            keep = np.arange(len(rows))
        wrong = []
        for i in keep:
            lab, conf = pred._label(P[i])
            if lab != rows[i]["label"]:
                wrong.append({"input": rows[i]["text"], "predicted_label": lab, "corrected_label": rows[i]["label"],
                              "confidence": round(float(conf), 4), "id": rows[i]["id"]})
        _holdback_cache[key] = {"scored": int(len(keep)), "total": len(rows), "wrong": wrong,
                                "source": f"held-back slice of run {path.parent.name} (real labeled records, never in "
                                          "train, validation or the sealed test set)"}
    hit = _holdback_cache[key]
    return {**hit, "wrong": hit["wrong"][:max(1, min(limit, 2000))], "n_wrong": len(hit["wrong"])}


# ---- improve ------------------------------------------------------------------------------
@router.post("/specialists/{sid}/improve")
def improve(sid: str, user: User | None = Depends(current_user)):
    v = _spec(sid, user)
    require_edit(v, user)
    if config.app_mode() == "replay":
        run = recorded_improve(v.task_id)
        if not run:
            raise HTTPException(409, "Replay mode plays recorded runs only, and there's no recorded improve run for "
                                     "this specialist.")
        return {"run_id": run, "replay": True}
    rows = _load_corrections(sid, user)
    if not rows:
        raise HTTPException(422, "Add at least one correction first.")
    try:
        imp = Improver(sid, rows, user_id=uid(user))
    except ImproveUnavailable as exc:
        raise HTTPException(409, str(exc))
    _save_corrections(sid, user, [])           # they're in the run's corrections.json now
    threading.Thread(target=imp.run, daemon=True).start()
    return {"run_id": imp.run_id, "replay": False}

