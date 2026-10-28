"""Trainer agent: run candidate configs in parallel through successive-halving rounds (DECISION D4).

Round 1: every config on 10% of the training data. Round 2: the top quarter on 40%. Round 3: the top 2-3 on
100%. A small-data guard skips early rounds when a fraction would be too small to rank configs. Failed runs
get up to two fix attempts: Nemotron Nano reads the error and proposes a config patch.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Callable

from backend import config
from backend.agents.planner_agent import SPACES
from backend.candidates import LLM_FAMILIES
from backend.sandbox.launcher import get_launcher
from backend.sealed import load_split
from backend.schemas import CandidatePlan, CandidateRun, Runs, TaskCard

Emit = Callable[..., None]
MIN_ROWS_FOR_ROUND = 400


def schedule_for(n_train: int, full: bool = True) -> list[float]:
    """Data fractions per round, skipping fractions that would leave fewer than MIN_ROWS_FOR_ROUND rows."""
    if not full:
        return [1.0]
    fracs = [f for f in (0.1, 0.4) if n_train * f >= MIN_ROWS_FOR_ROUND]
    return fracs + [1.0]


def keep_count(round_idx: int, n_rounds: int, n: int) -> int:
    remaining = n_rounds - round_idx - 1
    if remaining <= 0:
        return n
    if remaining == 1:          # going into the last round: top 2-3
        return min(n, 3)
    return min(n, max(3, math.ceil(n / 4)))   # top quarter


class Trainer:
    def __init__(self, card: TaskCard, run_dir: Path, train_path: Path, val_path: Path, labels: list[str],
                 emit: Emit, spend: Callable[[], float], budget_usd: float, llm=None, max_eval_llm: int = 150):
        self.card, self.run_dir, self.labels, self.emit = card, run_dir, labels, emit
        self.train_path, self.val_path = train_path, val_path
        self.spend, self.budget_usd, self.llm, self.max_eval_llm = spend, budget_usd, llm, max_eval_llm
        self.launcher = get_launcher(lambda msg: emit("Trainer", "train", msg))
        templates = config.data_dir() / "raw" / "hdfs_v1" / "preprocessed" / "HDFS.log_templates.csv"
        self.templates = None
        if card.input_type == "log_window":
            from backend.features.logs import TemplateParser
            self.templates = TemplateParser.from_csv(templates).templates
        self.runs: dict[str, CandidateRun] = {}

    def _job(self, run: CandidateRun, round_no: int, frac: float, out_name: str) -> dict:
        roles = {r: spec["api_id"] for r, spec in config.models().items() if "api_id" in spec}
        return {
            "cand": run.cand, "family": run.family, "params": run.config, "seed": run.seed, "round": round_no,
            "data_frac": frac, "run_dir": str(self.run_dir), "train_path": str(self.train_path),
            "val_path": str(self.val_path), "out_dir": str(self.run_dir / "candidates" / out_name),
            "labels": self.labels, "input_type": self.card.input_type, "task_description": self.card.description,
            "label_definitions": {l.name: l.definition for l in self.card.labels},
            "primary_metric": self.card.optimization_metric, "positive": self.card.positive_definition,
            "fpr_target": self.card.fpr_target, "model_ids": roles,
            "needs_llm": run.family in LLM_FAMILIES or run.family == "B" or run.config.get("backend") == "cloud",
            "max_eval": self.max_eval_llm if run.family in LLM_FAMILIES else None,
            "budget_remaining_usd": max(self.budget_usd - self.spend(), 0.0),
            "log_templates": self.templates,
        }

    def _write_runs(self):
        Runs(runs=list(self.runs.values())).write(self.run_dir / "runs.json")

    def _on_event(self, ev: dict):
        cand = ev.get("cand")
        run = self.runs.get(cand.split("@")[0]) if cand else None
        if run is None:
            return
        kind = ev.get("event")
        if kind == "start":
            run.status = "running"
        elif kind == "progress" and ev.get("step") == "val":
            val = ev.get(f"val_{self.card.optimization_metric}")
            run.history.append({"round": ev["round"], "data_frac": ev["data_frac"], "val": val})
            self.emit("Trainer", "train", "", kind="candidate", data={"cand": run.cand, "family": run.family,
                      "round": ev["round"], "data_frac": ev["data_frac"], "val": val, "status": "validating"})
        elif kind == "done":
            self.emit("Trainer", "train", "", kind="candidate", data={
                "cand": run.cand, "family": run.family, "round": ev["round"], "data_frac": ev["data_frac"],
                "val": ev["primary"], "cost_per_1m_usd": ev["cost_per_1m_usd"], "p50_ms": ev["ms_per_item"],
                "status": "done", "usage": ev.get("usage")})

    def _fix(self, run: CandidateRun, error: str) -> dict | None:
        """Ask Nemotron Nano for a config patch after a crash. Returns new params or None."""
        if self.llm is None:
            return None
        prompt = (f"A training run for candidate family {run.family} crashed.\nConfig: {json.dumps(run.config)}\n"
                  f"Allowed values: {json.dumps(SPACES.get(run.family, {}))}\nError (tail):\n{error[-1500:]}\n"
                  'Propose a corrected config using only allowed values. Return JSON: {"params": {...}, "why": "..."}')
        try:
            res = self.llm.chat("trainer_error_fixer", [{"role": "user", "content": prompt}], agent="Trainer",
                                purpose="error_fix", max_tokens=400, thinking=False,
                                response_format={"type": "json_object"})
            out = res.json()
            params = {k: v for k, v in out.get("params", {}).items() if v in SPACES.get(run.family, {}).get(k, [v])}
            if params and params != run.config:
                self.emit("Trainer", "train", f"Trainer: {run.cand} crashed; retrying with {params} ({out.get('why', '')[:80]})")
                return params
        except Exception:
            pass
        return None

    def _run_round(self, active: list[CandidateRun], round_no: int, frac: float) -> None:
        jobs = [self._job(r, round_no, frac, f"{r.cand}/r{round_no}") for r in active]
        for r in active:
            r.status, r.round_reached, r.data_frac = "queued", round_no, frac
        self._write_runs()
        pending = {j["cand"]: j for j in jobs}
        attempt = 0
        while pending and attempt <= 2:
            results = self.launcher.run(list(pending.values()), self._on_event)
            retry = {}
            for res in results:
                run = self.runs[res["cand"]]
                if res["status"] == "done":
                    run.status, run.val_score = "done", res["primary"]
                    run.metrics_path = res["metrics_path"]
                    continue
                run.status, run.error_log = res["status"], res.get("error_log")
                err = res.get("error") or ""
                self.emit("Trainer", "train", f"Trainer: {run.cand} {res['status']}: {err.strip().splitlines()[-1][:120] if err.strip() else 'no output'}",
                          kind="candidate", data={"cand": run.cand, "family": run.family, "status": res["status"]})
                if attempt < 2 and res["status"] == "failed":
                    patch = self._fix(run, (res.get("traceback") or "") + err)
                    if patch:
                        run.config, run.fix_attempts = patch, run.fix_attempts + 1
                        retry[run.cand] = self._job(run, round_no, frac, f"{run.cand}/r{round_no}-fix{run.fix_attempts}")
            pending, attempt = retry, attempt + 1
            self._write_runs()

    def search(self, plan: CandidatePlan, schedule: list[float]) -> list[CandidateRun]:
        self.runs = {c.id: CandidateRun(cand=c.id, family=c.family, config=c.params) for c in plan.candidates}
        active = list(self.runs.values())
        for i, frac in enumerate(schedule):
            round_no = i + 1
            self.emit("Trainer", "train", f"Trainer: round {round_no}, {len(active)} candidates on {frac:.0%} of data",
                      kind="round", data={"round": round_no, "data_frac": frac, "n": len(active),
                                          "cands": [r.cand for r in active]})
            t0 = time.time()
            self._run_round(active, round_no, frac)
            done = sorted([r for r in active if r.status == "done"], key=lambda r: -(r.val_score or -1))
            keep = keep_count(i, len(schedule), len(done))
            survivors = done[:keep]
            for r in done[keep:]:
                r.status = "eliminated"
                cut = survivors[-1].val_score if survivors else 0.0
                r.elimination_reason = (f"{self.card.optimization_metric} {r.val_score:.3f} < {cut:.3f} "
                                        f"(round {round_no} cutoff)")
                self.emit("Trainer", "train", "", kind="candidate", data={
                    "cand": r.cand, "family": r.family, "status": "eliminated", "reason": r.elimination_reason,
                    "round": round_no})
            if i < len(schedule) - 1:
                self.emit("Trainer", "train", f"Trainer: round {round_no} done in {time.time() - t0:.0f}s; "
                          f"{len(survivors)} of {len(active)} go on to {schedule[i + 1]:.0%} of data")
            active = survivors
            self._write_runs()
            if self.spend() >= self.budget_usd:
                self.emit("Trainer", "train", "Trainer: LLM budget reached; stopping the search early")
                break
        self._write_runs()
        return [r for r in self.runs.values() if r.status == "done" and r.round_reached == len(schedule)] or active

    def retrain(self, runs: list[CandidateRun], tag: str, seed: int | None = None, frac: float = 1.0) -> list[dict]:
        """Retrain configs on the current training set (repair, seeds, improve). Returns worker results."""
        jobs = []
        for r in runs:
            rr = CandidateRun(cand=r.cand, family=r.family, config=r.config, seed=r.seed if seed is None else seed)
            jobs.append(self._job(rr, 99, frac, f"{r.cand}/{tag}"))
        return self.launcher.run(jobs, lambda ev: None)


def train_rows(train_path: Path) -> int:
    return sum(1 for _ in Path(train_path).open())


def load_labels(train_path: Path, val_path: Path) -> list[str]:
    return sorted({r["label"] for r in load_split(train_path)} | {r["label"] for r in load_split(val_path)})
