"""Orchestrator (plain Python, not an LLM): runs the stages in a fixed order, enforces the budget and the
repair cap, and writes events.jsonl / run_state.json. Agents never talk to each other directly; every
handoff is a file in runs/<run_id>/.
"""
from __future__ import annotations

import itertools
import json
import random
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from backend import config
from backend import metrics as M
from backend.agents import evaluator_agent as ev
from backend.agents.data_agent import add_targeted_examples, run_data_agent
from backend.agents.planner_agent import run_planner
from backend.agents.trainer_agent import Trainer, load_labels, schedule_for, train_rows
from backend.demo_tasks import input_hint
from backend.candidates import LLM_FAMILIES, Candidate, CascadeH
from backend.llm_client import BudgetExceeded, LLMClient
from backend.sealed import load_split
from backend.schemas import (CandidateRun, ErrorPatterns, EvalReport, Event, RunState, TaskCard)
from backend.versions import registry


class _Uncached:
    """LLM client view that never serves chat answers from the disk cache (for timing real calls)."""

    def __init__(self, llm):
        self._llm = llm

    def chat(self, *args, **kwargs):
        return self._llm.chat(*args, **{**kwargs, "use_cache": False})

    def __getattr__(self, name):
        return getattr(self._llm, name)


# Cascade tiers, cheapest first: rung 1 (rules, TF-IDF, LightGBM), embeddings, prompted LLMs.
TIER = {"J": 1, "A": 1, "E": 1, "I": 2, "B": 2, "C": 2, "K": 3, "L": 3}


@dataclass
class Options:
    llm_planner: bool = True
    full_search: bool = True
    repair: bool = True
    cascade: bool = True
    seeds: bool = True
    families: list[str] | None = None
    limit_per_family: int | None = None
    baseline_n: int = 300
    max_eval_llm: int = 150
    cascade_eval_n: int = 400        # validation rows the chosen LLM stage is scored on before fitting cascades
    deploy: bool = True
    extra: dict = field(default_factory=dict)


PHASE1 = Options(llm_planner=False, full_search=False, repair=False, cascade=False, seeds=False,
                 families=["J", "A", "I", "E", "K"], limit_per_family=1)


def new_run_id(task_id: str) -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{task_id}-{uuid.uuid4().hex[:4]}"


class Orchestrator:
    def __init__(self, card: TaskCard, run_id: str | None = None, options: Options | None = None):
        self.card = card
        self.run_id = run_id or new_run_id(card.task_id)
        self.dir = config.runs_dir() / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.opt = options or Options()
        budget = min(config.credit_budget_usd(), card.build_budget_usd or float("inf"))
        self.llm = LLMClient(run_dir=self.dir, budget_usd=budget)
        self.budget = budget
        self.t0 = time.time()
        self._lock = threading.Lock()
        self.state = RunState(run_id=self.run_id, task_id=card.task_id, stage="intake", budget_usd=budget,
                              started=self.t0, updated=self.t0)
        self.result: dict = {}

    # ---- bookkeeping ---------------------------------------------------------
    def spend(self) -> float:
        path = self.dir / "llm_calls.jsonl"
        if not path.exists():
            return 0.0
        total = 0.0
        for line in path.open():
            try:
                total += json.loads(line)["cost_usd"]
            except (json.JSONDecodeError, KeyError):
                continue
        return total

    def emit(self, agent: str, stage: str, message: str, data_ref: str | None = None, kind: str = "narration",
             data: dict | None = None) -> None:
        e = Event(ts=time.time(), agent=agent, stage=stage, message=message, data_ref=data_ref,
                  spend_usd=round(self.spend(), 6), kind=kind, data=data)
        with self._lock:
            with (self.dir / "events.jsonl").open("a") as f:
                f.write(e.model_dump_json() + "\n")
            self.state.stage, self.state.updated, self.state.spend_usd = stage, e.ts, e.spend_usd
            self.state.write(self.dir / "run_state.json")

    def _check_budget(self):
        if self.spend() >= self.budget:
            raise BudgetExceeded(f"LLM spend reached the budget of ${self.budget:.2f}")

    # ---- stages -----------------------------------------------------------------
    def run(self) -> dict:
        registry.record_run(self.run_id, self.card.task_id, "build", "running")
        try:
            self._run()
            self.state.status, self.state.message = "done", "Run complete"
        except BudgetExceeded as exc:
            self.state.status, self.state.message = "stopped_budget", str(exc)
            self.emit("Orchestrator", "stopped", f"Stopped: {exc}", kind="error")
        except Exception as exc:
            self.state.status, self.state.message = "failed", f"{type(exc).__name__}: {exc}"
            (self.dir / "error.log").write_text(traceback.format_exc())
            self.emit("Orchestrator", "failed", f"Run failed: {type(exc).__name__}: {exc}", kind="error",
                      data_ref="error.log")
        finally:
            self.state.finished = time.time()
            self.state.spend_usd = self.spend()
            self.state.write(self.dir / "run_state.json")
            registry.record_run(self.run_id, self.card.task_id, "build", self.state.status,
                                self.result.get("specialist_id"))
            self.emit("Orchestrator", "end", "", kind="done", data={"status": self.state.status, **self.result})
        return self.result

    def _run(self):
        card = self.card
        card.write(self.dir / "task_card.json")
        self.emit("Orchestrator", "intake", f"Building \"{card.task_name}\" (budget ${self.budget:.2f})",
                  data_ref="task_card.json", kind="handoff")

        paths = run_data_agent(card, self.dir, self.emit)
        labels = load_labels(paths.train, paths.val)
        (self.dir / "labels.json").write_text(json.dumps(labels))

        plan = run_planner(card, paths.stats, self.dir, self.emit, llm=self.llm if self.opt.llm_planner else None,
                           families=self.opt.families, limit_per_family=self.opt.limit_per_family)
        self.emit("Planner", "plan", "", kind="pareto", data={"plan": [c.id for c in plan.candidates]})

        # Baseline on the validation sample for the live scatter (the report uses the sealed sample).
        val = load_split(paths.val)
        base_val_rows = ev.stratified_sample(val, self.opt.max_eval_llm, seed=0)
        base_val = ev.score_baseline(card, labels, base_val_rows, self.llm, self.emit)
        self.emit("Evaluator", "baseline", f"Evaluator: Nemotron Ultra zero-shot scores {card.optimization_metric} "
                  f"{base_val['metrics']['primary']:.3f} on {len(base_val_rows)} validation records",
                  kind="pareto", data={"baseline": {"val": base_val["metrics"]["primary"],
                                                    "cost_per_1m_usd": base_val["cost_per_1m_usd"],
                                                    "p50_ms": base_val["p50_ms"], "n": len(base_val_rows)}})
        self._check_budget()

        trainer = Trainer(card, self.dir, paths.train, paths.val, labels, self.emit, self.spend, self.budget,
                          llm=self.llm, max_eval_llm=self.opt.max_eval_llm)
        schedule = schedule_for(train_rows(paths.train), self.opt.full_search)
        finalists = trainer.search(plan, schedule)
        self._remeasure_latency(trainer, len(schedule), load_split(paths.val))

        points = self._points(trainer, schedule)
        report = EvalReport(task_id=card.task_id, primary_metric=card.optimization_metric,
                            validation_rounds=self._rounds(trainer, schedule), frontier=[], pareto_points=points,
                            calibration={})
        frontier, winner_id, why = ev.choose_frontier([p for p in points if p["final_round"]] or points, card)
        report.frontier, report.winner, report.winner_reason = frontier, winner_id, why
        self.emit("Evaluator", "validate", f"Evaluator: best on validation is {winner_id} "
                  f"({card.optimization_metric} {next(p['val_primary'] for p in points if p['cand'] == winner_id):.3f}); {why}",
                  data_ref="eval_report.json", kind="pareto", data={"frontier": [f.model_dump() for f in frontier]})

        winner = trainer.runs[winner_id]
        model, wdir = self._load(winner, schedule)
        P, ids = ev.load_val_proba(wdir)
        by_id = {r["id"]: r for r in val}
        yv = np.array([labels.index(by_id[i]["label"]) for i in ids])
        calibrator, cal = ev.calibration_report(P, yv)
        report.calibration = {**cal, "candidate": winner_id}
        if cal.get("skipped"):
            self.emit("Evaluator", "validate", f"Evaluator: kept raw confidence; temperature scaling would not improve "
                      f"calibration (ECE {cal['ece_before']:.3f}, {cal['ece_after_crossfit']:.3f} after, cross-fit)")
        else:
            self.emit("Evaluator", "validate", f"Evaluator: calibrated confidence (ECE {cal['ece_before']:.3f} → "
                      f"{cal['ece_after_crossfit']:.3f})")

        patterns = ev.error_patterns(card, [by_id[i] for i in ids], calibrator.apply(P), labels,
                                     self.llm, self.emit)
        patterns.write(self.dir / "error_patterns.json")
        self.emit("Evaluator", "validate", "Evaluator: top error patterns: " +
                  "; ".join(f"{p.true_label} → {p.predicted_label} ({p.count})" for p in patterns.patterns[:3]),
                  data_ref="error_patterns.json", kind="handoff")

        val_primary = next(p["val_primary"] for p in points if p["cand"] == winner_id)
        if self.opt.repair:
            winner, model, wdir, calibrator, val_primary = self._repair(
                trainer, plan, finalists, winner, model, wdir, calibrator, val_primary, patterns, labels, val, report)
            P, ids = ev.load_val_proba(wdir)

        threshold = None
        if card.positive_definition:
            Pc = calibrator.apply(P)
            yl = [by_id[i]["label"] for i in ids]
            _, threshold = M.recall_at_fpr(np.array([y == card.positive_definition for y in yl]),
                                           Pc[:, labels.index(card.positive_definition)], card.fpr_target or 0.01)
            report.calibration["threshold_at_fpr"] = threshold

        chosen, chosen_id = model, winner.cand
        if self.opt.cascade:
            chosen, chosen_id = self._cascade(trainer, winner, model, calibrator, labels, val, report, points)

        report.chosen = chosen_id

        if self.opt.seeds:
            report.seeds = self._seeds(trainer, winner, report)
        report.more_data_curve = self._more_data(trainer, winner, schedule)

        # ---- final exam: exactly once for this version ---------------------------------
        self._check_budget()
        final = ev.final_exam(card, self.dir, self.dir, chosen, labels, calibrator, threshold, self.emit)
        report.final = final
        report.val_vs_sealed = {"validation": val_primary if chosen_id == winner.cand else report.cascade["primary"],
                                "sealed": final["primary"]}
        base, sample = ev.baseline_on_sealed(card, self.dir, self.dir, labels, self.llm, self.emit, self.opt.baseline_n)
        spec_on_sample, spec_pred = ev.score_rows(card, chosen, sample, labels, calibrator)
        report.baseline = {k: v for k, v in base.items() if k not in ("labels_pred", "ids")}
        report.final_sample = {"metrics": spec_on_sample, "n": len(sample),
                               "note": "the specialist on the same sealed rows the baseline was scored on"}
        report.teacher_agreement = ev.teacher_agreement(spec_pred, base["labels_pred"])
        self.emit("Evaluator", "final", f"Evaluator: on the same {len(sample)} sealed records, specialist "
                  f"{spec_on_sample['primary']:.3f} vs Nemotron Ultra {base['metrics']['primary']:.3f}; "
                  f"agreement with Ultra {report.teacher_agreement['agreement_rate']:.0%}",
                  kind="pareto", data={"sealed": {"specialist": spec_on_sample["primary"],
                                                  "baseline": base["metrics"]["primary"]}})
        report.real_vs_synthetic = ev.real_vs_synthetic(card, self.dir, chosen, labels, calibrator)
        report.weaknesses = [f"{p.true_label} confused with {p.predicted_label} ({p.count} validation errors): {p.pattern}"
                             for p in ErrorPatterns.read(self.dir / "error_patterns.json").patterns]
        manifest = json.loads((self.dir / "dataset_manifest.json").read_text())
        report.data_sources = manifest["sources"]
        passed, gate_reason = ev.version_gate(card, final, None)
        report.decision = {"passes_thresholds": passed, "reason": gate_reason,
                           "target": card.thresholds.model_dump()}
        report.write(self.dir / "eval_report.json")

        if self.opt.deploy:
            self._deploy(chosen, chosen_id, labels, calibrator, threshold, final, report)
        from backend.report import write_report_card
        write_report_card(self.dir)
        self.emit("Evaluator", "report", "Report card ready", data_ref="report_card.json", kind="handoff")

    # ---- helpers -----------------------------------------------------------------
    def _cand_dir(self, run: CandidateRun, schedule: list[float]) -> Path:
        return Path(run.metrics_path).parent

    def _load(self, run: CandidateRun, schedule) -> tuple[Candidate, Path]:
        d = self._cand_dir(run, schedule)
        return Candidate.load(d, llm=self.llm), d

    def _points(self, trainer: Trainer, schedule: list[float]) -> list[dict]:
        pts = []
        for r in trainer.runs.values():
            if not r.metrics_path:
                continue
            m = json.loads(Path(r.metrics_path).read_text())
            from backend.candidates import FAMILIES
            cls = FAMILIES.get(r.family)
            uses_cloud = bool(cls and cls.uses_cloud) or r.config.get("backend") == "cloud"
            pts.append({"cand": r.cand, "family": r.family, "rung": (cls.rung if cls else 0), "round": r.round_reached,
                        "data_frac": r.data_frac, "val_primary": m["primary"], "val_secondary": m.get("secondary"),
                        "cost_per_1m_usd": m["cost_per_1m_usd"],
                        "p50_ms": m["p50_ms"], "p99_ms": m["p99_ms"], "eliminated": r.status == "eliminated",
                        "final_round": r.status == "done" and r.round_reached == len(schedule),
                        "uses_cloud": uses_cloud, "n_val": m["n"], "metrics_path": r.metrics_path})
        return pts

    def _rounds(self, trainer: Trainer, schedule) -> list[dict]:
        out = []
        for i, frac in enumerate(schedule, 1):
            out.append({"round": i, "data_frac": frac, "scores": {
                r.cand: h["val"] for r in trainer.runs.values() for h in r.history if h["round"] == i}})
        return out

    def _repair(self, trainer, plan, finalists, winner, model, wdir, calibrator, val_primary, patterns, labels,
                val, report):
        rounds = 0
        while val_primary < self.card.thresholds.primary_min and rounds < config.max_repair_rounds():
            self._check_budget()
            rounds += 1
            self.state.repair_round = rounds
            top = patterns.patterns[0] if patterns.patterns else None
            self.emit("Evaluator", "repair", f"Repair round {rounds}: {top.pattern if top else 'low validation score'}"
                      f"{'; ' + top.suggested_data_fix if top else ''}", data_ref="error_patterns.json")
            added = add_targeted_examples(self.card, self.dir, patterns, self.llm, self.emit, rounds)
            top2 = sorted([r for r in finalists if r.val_score is not None], key=lambda r: -r.val_score)[:2]
            results = trainer.retrain(top2, tag=f"repair{rounds}")
            best = None
            for r, res in zip(top2, results):
                if res["status"] == "done":
                    entry = {"cand": r.cand, "before": r.val_score, "after": res["primary"],
                             "metrics_path": res["metrics_path"]}
                    best = entry if best is None or entry["after"] > best["after"] else best
            rec = {"round": rounds, "added_examples": added, "pattern": top.pattern if top else None,
                   "retrained": [r.cand for r in top2], "best": best}
            report.repair_rounds.append(rec)
            if best is None:
                break
            self.emit("Evaluator", "repair", f"Evaluator: after repair round {rounds}, {best['cand']} scores "
                      f"{best['after']:.3f} on validation (was {best['before']:.3f})")
            if best["after"] > val_primary:
                winner = trainer.runs[best["cand"]]
                winner.metrics_path, winner.val_score = best["metrics_path"], best["after"]
                model, wdir = Candidate.load(Path(best["metrics_path"]).parent, llm=self.llm), Path(best["metrics_path"]).parent
                val_primary = best["after"]
                P, ids = ev.load_val_proba(wdir)
                by_id = {r["id"]: r for r in val}
                yv = np.array([labels.index(by_id[i]["label"]) for i in ids])
                calibrator, cal = ev.calibration_report(P, yv)
                report.calibration = {**cal, "candidate": winner.cand}
                patterns = ev.error_patterns(self.card, [by_id[i] for i in ids], calibrator.apply(P), labels,
                                             self.llm, self.emit)
                patterns.write(self.dir / "error_patterns.json")
                report.winner = winner.cand
            else:
                self.emit("Evaluator", "repair", "Repair didn't improve validation; keeping the previous model")
                rec["kept_previous"] = True
                # Roll the training set back so the final model's data matches its artifact.
                train = [r for r in load_split(self.dir / "train.jsonl") if not str(r["id"]).startswith(f"syn-r{rounds}-")]
                from backend.sealed import write_split
                write_split(self.dir / "train.jsonl", train)
        if val_primary < self.card.thresholds.primary_min:
            self.emit("Evaluator", "repair", f"Evaluator: stopping repair after {rounds} round(s); best validation "
                      f"{self.card.optimization_metric} is {val_primary:.3f}, under the target "
                      f"{self.card.thresholds.primary_min:.2f}")
        return winner, model, wdir, calibrator, val_primary

    def _cascade(self, trainer, winner, model, calibrator, labels, val, report, points):
        """Wrap the winner in cascades with one candidate per later tier (winner → embeddings → LLM) and keep the
        best one if it beats the winner alone by more than 0.01 on the same validation rows."""
        if winner.family in LLM_FAMILIES:
            return model, winner.cand
        n_rounds = max((r.round_reached or 0) for r in trainer.runs.values())

        def best_of(tier: int) -> CandidateRun | None:
            if TIER.get(winner.family) == tier:
                return winner
            pool = [r for r in trainer.runs.values() if TIER.get(r.family) == tier and r.metrics_path
                    and (tier == 3 or (r.status == "done" and r.round_reached == n_rounds))]
            return max(pool, key=lambda r: r.val_score or -1) if pool else None

        reps = {t: best_of(t) for t in (1, 2, 3)}
        reps = {t: r for t, r in reps.items() if r is not None}
        if 3 not in reps:
            return model, winner.cand
        by_id = {r["id"]: r for r in val}
        info = {}
        for t, r in reps.items():
            P, ids = ev.load_val_proba(Path(r.metrics_path).parent)
            m = json.loads(Path(r.metrics_path).read_text())
            if r is winner:
                cal = calibrator
            elif t == 3:
                cal = None
            else:
                cal, _ = ev.calibration_report(P, np.array([labels.index(by_id[i]["label"]) for i in ids]))
            info[t] = {"run": r, "P": P, "ids": ids, "cost": m["cost_per_1m_usd"], "calibrator": cal, "m": m}
        self._widen_llm_sample(info[3], val)
        shared = set(info[3]["ids"])
        wi = info[TIER[winner.family]]
        # H wraps the recommended single model (spec file 03): every chain starts with the winner's tier.
        wt = TIER[winner.family]
        chains = [list(c) for n in (2, 3) for c in itertools.combinations(sorted(info), n) if c[0] == wt]
        tried = []
        for chain in chains:
            res = ev.fit_cascade_chain(self.card, labels, val, [info[t] for t in chain], only_ids=shared)
            if not res:
                continue
            res["winner_alone_same_sample"] = ev.score_on_ids(self.card, labels, val, wi["P"], wi["ids"],
                                                              wi["calibrator"], res["ids"])
            cands = [info[t]["run"].cand for t in chain]
            ms = [info[t]["m"] for t in chain]
            reach = np.cumsum([0.0] + res["shares"][:-1])
            reach = [1.0 - x for x in reach]              # share of items that reach each stage
            cum = np.cumsum(res["shares"])
            k50 = int(np.searchsorted(cum, 0.5))
            k99 = int(np.searchsorted(cum, 0.99))
            p50 = float(sum(m["p50_ms"] for m in ms[:k50 + 1]))
            p99 = float(sum(m["p99_ms"] for m in ms[:min(k99, len(ms) - 1) + 1]))
            point = {"cand": "H(" + "→".join(cands) + ")", "family": "H", "rung": 0, "round": 0, "data_frac": 1.0,
                     "val_primary": res["primary"], "cost_per_1m_usd": res["cost_per_1m_usd"], "p50_ms": p50,
                     "p99_ms": p99, "eliminated": False, "final_round": True,
                     "uses_cloud": any(info[t]["run"].family in LLM_FAMILIES or info[t]["run"].family == "B"
                                       or info[t]["run"].config.get("backend") == "cloud" for t in chain),
                     "n_val": res["n"]}
            stages = [{"cand": c, "family": info[t]["run"].family, "share": sh,
                       "tau": res["taus"][k] if k < len(res["taus"]) else None, "reach": rch}
                      for k, (t, c, sh, rch) in enumerate(zip(chain, cands, res["shares"], reach))]
            gain = res["primary"] - (res["winner_alone_same_sample"] or 0)
            ok, why_not = ev.allowed(point, self.card)
            tried.append({"chain": chain, "res": res, "point": point, "stages": stages, "gain": gain, "ok": ok,
                          "why_not": why_not})
            split = " / ".join(f"{s['cand']} {s['share']:.0%}" for s in stages)
            self.emit("Evaluator", "cascade", f"Evaluator: cascade {' → '.join(cands)} answers {split} and scores "
                      f"{res['primary']:.3f} vs {res['winner_alone_same_sample']:.3f} for {winner.cand} alone on the "
                      f"same {res['n']} validation records", kind="pareto", data={"cascade_tried": point})
        if not tried:
            return model, winner.cand
        good = [t for t in tried if t["ok"] and t["gain"] > 0.01 and t["res"]["escalation_rate"] > 0]
        summary = [{"cascade": t["point"]["cand"], "primary": t["res"]["primary"], "gain": t["gain"],
                    "cost_per_1m_usd": t["res"]["cost_per_1m_usd"], "stages": t["stages"],
                    "allowed": t["ok"], "why_not_allowed": t["why_not"] or None} for t in tried]
        pick = None
        if good:
            top = max(t["res"]["primary"] for t in good)
            pick = min((t for t in good if t["res"]["primary"] >= top - ev.CASCADE_TOLERANCE),
                       key=lambda t: (t["res"]["cost_per_1m_usd"], -t["res"]["primary"]))
        show = pick or max(tried, key=lambda t: t["gain"])
        r = {k: v for k, v in show["res"].items() if k != "ids"}
        report.cascade = {**r, "base": show["stages"][0]["cand"], "fallback": show["stages"][-1]["cand"],
                          "stages": show["stages"], "cost_per_1m_usd": r["cost_per_1m_usd"],
                          "cost_formula": "sum over stages of (share of items reaching the stage × its cost)",
                          "p50_ms": show["point"]["p50_ms"], "p99_ms": show["point"]["p99_ms"],
                          "cascades_tried": summary,
                          "pick_rule": f"gain over {winner.cand} alone > 0.01, then the cheapest within "
                                       f"{ev.CASCADE_TOLERANCE} of the best cascade"}
        # report.pareto_points is the report's own copy of `points`; the report card reads the chosen point there.
        points.extend(t["point"] for t in tried)
        report.pareto_points.extend(t["point"] for t in tried)
        self.emit("Evaluator", "cascade", f"Evaluator: {'using' if pick else 'closest'} cascade {show['point']['cand']}"
                  + ("" if pick else " (not used)"), kind="pareto", data={"point": show["point"]})
        if pick is None:
            report.cascade["used"] = False
            report.cascade["why_not"] = ("no cascade gained over 0.01 on the shared validation sample"
                                         if not any(t["gain"] > 0.01 for t in tried) else
                                         "the cascades that gained break a latency or deployment constraint")
            return model, winner.cand
        stage_models = [model if info[t]["run"] is winner else Candidate.load(Path(info[t]["run"].metrics_path).parent,
                                                                                llm=self.llm) for t in pick["chain"]]
        cals = [info[t]["calibrator"] for t in pick["chain"][:-1]]
        split = ", ".join(f"{s['share']:.0%} {s['cand']}" for s in pick["stages"])
        report.winner_reason += (f"; wrapped in a cascade that answers {split} "
                                 f"(+{pick['gain']:.3f} on the shared sample)")
        return (CascadeH(stage_models, r["taus"], cals, names=[s["cand"] for s in pick["stages"]]),
                pick["point"]["cand"])

    def _remeasure_latency(self, trainer, n_rounds: int, val: list[dict], n_llm: int = 10, n_emb: int = 20) -> None:
        """Latency measured during the search is inflated for cloud candidates: dozens of jobs share the API at
        once, and rate-limit retries count as latency. Once nothing else is running, re-measure each cloud
        finalist one call at a time with caches bypassed, as a single caller would see it."""
        from backend.candidates import FAMILIES
        texts = [r["text"] for r in val[:max(n_llm, n_emb)]]
        for r in trainer.runs.values():
            if not (r.status == "done" and r.round_reached == n_rounds and r.metrics_path):
                continue
            cls = FAMILIES.get(r.family)
            is_llm = r.family in LLM_FAMILIES
            if not (is_llm or (cls and cls.uses_cloud) or r.config.get("backend") == "cloud"):
                continue
            self._check_budget()
            model = Candidate.load(Path(r.metrics_path).parent, llm=_Uncached(self.llm))
            model.bypass_cache = True
            lat = []
            for t in texts[:n_llm if is_llm else n_emb]:
                t0 = time.perf_counter()
                model.predict_proba([t])
                lat.append((time.perf_counter() - t0) * 1000)
            mp = Path(r.metrics_path)
            m = json.loads(mp.read_text())
            before = m["p50_ms"]
            m.update({"p50_ms_during_search": m["p50_ms"], "p99_ms_during_search": m["p99_ms"],
                      "p50_ms": float(np.percentile(lat, 50)), "p99_ms": float(np.percentile(lat, 99)),
                      "latency_note": f"re-measured after the search: {len(lat)} single-item calls one at a time, "
                                      "caches bypassed, from this machine"})
            mp.write_text(json.dumps(m, indent=2))
            self.emit("Evaluator", "validate", f"Evaluator: re-measured {r.cand} latency alone: p50 "
                      f"{m['p50_ms']:.0f} ms (was {before:.0f} ms while sharing the API with the search)")

    def _widen_llm_sample(self, llm_info: dict, val: list[dict]) -> None:
        """The search scores LLM rungs on a small capped sample. Cascade thresholds need more rows (with many
        labels, 150 rows is about two per class), so score the chosen LLM stage on a larger stratified sample."""
        have = set(llm_info["ids"])
        want = [r for r in ev.stratified_sample(val, self.opt.cascade_eval_n, seed=0) if r["id"] not in have]
        if not want:
            return
        self._check_budget()
        run = llm_info["run"]
        self.emit("Evaluator", "cascade", f"Evaluator: scoring {run.cand} on {len(want)} more validation records so "
                  f"cascade thresholds are fitted on {len(have) + len(want)} rows")
        P = Candidate.load(Path(run.metrics_path).parent, llm=self.llm).predict_proba([r["text"] for r in want])
        llm_info["P"] = np.vstack([llm_info["P"], P])
        llm_info["ids"] = list(llm_info["ids"]) + [r["id"] for r in want]

    def _seeds(self, trainer, winner, report) -> dict:
        """Rerun the final 2 (the shipped single model and the best alternative) with 3 bootstrap seeds."""
        alts = [trainer.runs[f.cand] for f in report.frontier if f.cand in trainer.runs and f.cand != winner.cand]
        final2 = [r for r in [winner] + alts if r.family not in LLM_FAMILIES][:2]
        out = {}
        for r in final2:
            scores = []
            for seed in (1, 2, 3):
                res = trainer.retrain([r], tag=f"seed{seed}", seed=seed, score_only=True, bootstrap=True)[0]
                if res["status"] == "done":
                    scores.append(res["primary"])
            if scores:
                out[r.cand] = {"mean": float(np.mean(scores)), "std": float(np.std(scores)), "n_seeds": len(scores),
                               "scores": scores, "method": "bootstrap resample of the training set per seed"}
        if out:
            self.emit("Evaluator", "seeds", "Evaluator: seed reruns " + "; ".join(
                f"{k} {v['mean']:.3f} ± {v['std']:.3f}" for k, v in out.items()))
        return out

    def _more_data(self, trainer, winner, schedule) -> list[dict]:
        pts = {h["data_frac"]: h["val"] for h in winner.history if h.get("val") is not None}
        for frac in (0.1, 0.4):
            if frac not in pts:
                res = trainer.retrain([winner], tag=f"curve{int(frac * 100)}", frac=frac, score_only=True)[0]
                if res["status"] == "done":
                    pts[frac] = res["primary"]
        if 1.0 not in pts and winner.val_score is not None:
            pts[1.0] = winner.val_score
        return [{"data_frac": k, "val_primary": v} for k, v in sorted(pts.items())]

    def _deploy(self, model, cand_id, labels, calibrator, threshold, final, report):
        bundle = self.dir / "bundle"
        if bundle.exists():
            shutil.rmtree(bundle)
        model.save(bundle)
        winner_metrics = next((p for p in report.pareto_points if p["cand"] == cand_id), {})
        val = load_split(self.dir / "val.jsonl")
        example = random.Random(1).choice(val)["text"]
        meta = {"task_name": self.card.task_name, "task_id": self.card.task_id, "labels": labels,
                "input_type": self.card.input_type, "positive": self.card.positive_definition, "threshold": threshold,
                "calibrator_T": None if isinstance(model, CascadeH) else calibrator.T,
                "needs_reason": self.card.needs_reason, "candidate": cand_id, "family": model.family,
                "uses_cloud": bool(model.uses_cloud), "run_id": self.run_id, "example_input": example,
                "cost_per_1m_usd": winner_metrics.get("cost_per_1m_usd"), "p50_ms": winner_metrics.get("p50_ms"),
                "p99_ms": winner_metrics.get("p99_ms"),
                "expected_format": input_hint(self.card.task_id, self.card.input_type)}
        (bundle / "bundle.json").write_text(json.dumps(meta, indent=2))
        v = registry.get_or_create(self.card)
        current = registry.live(v)
        passed, reason = ev.version_gate(self.card, final, current.sealed_metrics if current else None)
        summary = {k: final.get(k) for k in ("primary", "primary_metric", "macro_f1", "accuracy", "pr_auc",
                                              "recall_at_fpr", "per_class", "at_val_threshold", "escalation_rate", "n")}
        rec = registry.add_version(v, self.run_id, bundle, summary, passed, reason, cand_id)
        if passed and not any(k.revoked is None for k in v.api_keys):
            registry.create_key(v)   # plain key is not kept; the UI's "Use" dialog regenerates and reveals once
        self.result = {"specialist_id": v.specialist_id, "version": rec.version, "deployed": passed, "reason": reason}
        self.emit("Deploy", "deploy", f"Deployed v{rec.version}" if passed else f"v{rec.version} not deployed: {reason}",
                  data_ref="eval_report.json", kind="handoff", data=self.result)
