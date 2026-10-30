"""Improve: a validated v1 → v2 update from user corrections (spec 01 section 2.9, spec 02 stage 10).

Stages, in a fixed order, through the same agents as a build:
  Data      appends the corrections (and a few targeted variants) to the live version's training set only
  Trainer   retrains the live version's winner config and the runner-up on that training set
  Evaluator picks the better one on validation, gives it its one final exam on the original build's sealed test
            set (the fixed benchmark every version of this specialist is scored on), and runs the version gate
  Deploy    the new version goes live only if the gate passes; otherwise the live version stays
Every handoff is a file in runs/<run_id>/ and progress streams over the same events.jsonl / SSE as a build.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path

import numpy as np

from backend import config
from backend import metrics as M
from backend.agents import evaluator_agent as ev
from backend.agents.data_agent import add_corrections
from backend.agents.trainer_agent import Trainer, load_labels
from backend.candidates import Candidate, CascadeH
from backend.llm_client import BudgetExceeded, LLMClient
from backend.schemas import Corrections, Event, RunState, TaskCard
from backend.sealed import load_split, sealed_exists
from backend.storage import objects
from backend.versions import registry

MAX_CORRECTIONS = 2000
VARIANTS_UP_TO = 20         # with this many corrections or fewer, the Data agent also writes targeted variants
VARIANTS_PER_CORRECTION = 3
TIER = {"J": 1, "A": 1, "E": 1, "I": 2, "B": 2, "C": 2, "K": 3, "L": 3}     # cascade tiers, as in the orchestrator


class ImproveUnavailable(ValueError):
    """The live version's run folder lacks what an improve needs (train/val/sealed files)."""


def ensure_run(run_id: str) -> Path:
    """Local folder of a run; a run this server didn't execute is fetched from Object Storage when configured."""
    d = config.runs_dir() / run_id
    if not d.is_dir() and objects.enabled():
        try:
            objects.download_dir(objects.run_prefix(registry.run_owner(run_id)[1], run_id), d)
        except objects.StorageError:
            pass
    return d


def lineage(live) -> tuple[Path, Path, dict | None]:
    """(data run, benchmark run, previous improve report) for the live version.

    Training data comes from the live version's own run, so corrections accumulate across improvements. The
    sealed test set, search records and Pareto points come from the original build: every version in a chain is
    graded on that build's sealed test set, the fixed benchmark."""
    data = ensure_run(live.run_id)
    prev = json.loads((data / "improve_report.json").read_text()) if (data / "improve_report.json").exists() else None
    bench = ensure_run(prev["benchmark_run_id"]) if prev else data
    missing = [str(d.name + "/" + n) for d, names in ((data, ("task_card.json", "train.jsonl", "val.jsonl")),
                                                     (bench, ("runs.json", "eval_report.json")))
               for n in names if not (d / n).exists()]
    if missing or not sealed_exists(bench):
        raise ImproveUnavailable(
            f"v{live.version} was built in run {live.run_id}, whose training files aren't on this server "
            f"({', '.join(missing) or 'sealed test set'} missing), so it can't be retrained here.")
    return data, bench, prev


def new_run_id(sid: str) -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-improve-{sid[:24]}-{uuid.uuid4().hex[:4]}"


class Improver:
    def __init__(self, sid: str, corrections: list[dict], user_id: str | None = None, run_id: str | None = None):
        self.v = registry.load(sid)
        self.live = registry.live(self.v)
        if self.live is None:
            raise ImproveUnavailable("This specialist has no live version to improve.")
        self.base, self.bench, self.prev = lineage(self.live)
        self.card = TaskCard.read(self.base / "task_card.json")
        self.corrections = corrections[:MAX_CORRECTIONS]
        self.user_id = user_id
        self.run_id = run_id or new_run_id(sid)
        self.dir = config.runs_dir() / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.budget = min(config.credit_budget_usd(), self.card.build_budget_usd or float("inf"))
        self.llm = LLMClient(run_dir=self.dir, budget_usd=self.budget)
        self.t0 = time.time()
        self._lock = threading.Lock()
        self.state = RunState(run_id=self.run_id, task_id=self.card.task_id, stage="intake", budget_usd=self.budget,
                              started=self.t0, updated=self.t0, kind="improve")
        self.result: dict = {}

    # ---- bookkeeping (same files and event schema as Orchestrator) ------------------------
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

    def run(self) -> dict:
        sid = self.v.specialist_id
        registry.record_run(self.run_id, self.card.task_id, "improve", "running", sid, task_name=self.card.task_name,
                            user_id=self.user_id, budget_usd=self.budget)
        try:
            self._run()
            self.state.status, self.state.message = "done", "Improve complete"
        except BudgetExceeded as exc:
            self.state.status, self.state.message = "stopped_budget", str(exc)
            self.emit("Orchestrator", "stopped", f"Stopped: {exc}. v{self.live.version} stays live.", kind="error")
        except Exception as exc:
            self.state.status, self.state.message = "failed", f"{type(exc).__name__}: {exc}"
            (self.dir / "error.log").write_text(traceback.format_exc())
            self.emit("Orchestrator", "failed", f"Improve failed: {type(exc).__name__}: {exc}. "
                      f"v{self.live.version} stays live.", kind="error", data_ref="error.log")
        finally:
            self.state.finished = time.time()
            self.state.spend_usd = self.spend()
            self.state.write(self.dir / "run_state.json")
            registry.record_run(self.run_id, self.card.task_id, "improve", self.state.status, sid,
                                task_name=self.card.task_name, user_id=self.user_id, spend_usd=self.state.spend_usd,
                                budget_usd=self.budget, message=self.state.message,
                                version=self.result.get("version"), deployed=self.result.get("deployed"))
            self.emit("Orchestrator", "end", "", kind="done",
                      data={"status": self.state.status, "kind": "improve", "specialist_id": sid, **self.result})
            if objects.enabled():          # so any server can show it and a later improve can build on it
                try:
                    objects.upload_run(self.dir, self.user_id)
                except Exception as exc:
                    print(f"[improve] couldn't upload {self.run_id}: {type(exc).__name__}: {exc}", flush=True)
        return self.result

    # ---- stages ---------------------------------------------------------------------------
    def _run(self):
        card, base, live = self.card, self.base, self.live
        card.write(self.dir / "task_card.json")
        Corrections.model_validate({"corrections": self.corrections}).write(self.dir / "corrections.json")
        self.emit("Orchestrator", "intake", f"Improving {self.v.display_name} v{live.version} with "
                  f"{len(self.corrections):,} correction{'s' * (len(self.corrections) != 1)} "
                  f"(budget ${self.budget:.2f})", data_ref="corrections.json", kind="handoff")

        # Data: corrections (+ variants) go to the training set only; validation is copied unchanged.
        labels = json.loads((base / "labels.json").read_text()) if (base / "labels.json").exists() \
            else load_labels(base / "train.jsonl", base / "val.jsonl")
        unknown = sorted({c["corrected_label"] for c in self.corrections} - set(labels))
        if unknown:
            raise ValueError(f"corrected label(s) not in this specialist's labels: {', '.join(unknown[:3])}")
        variants = self._variants(labels) if len(self.corrections) <= VARIANTS_UP_TO else []
        paths = add_corrections(self.dir, base, self.corrections, self.emit, variants)
        (self.dir / "labels.json").write_text(json.dumps(labels))
        self.emit("Data", "data", f"Training set: {sum(1 for _ in paths.train.open()):,} rows; validation unchanged "
                  f"({sum(1 for _ in paths.val.open()):,} rows); the sealed test set is never touched",
                  data_ref="dataset_manifest.json", kind="handoff")

        # Trainer: the live winner's config and the runner-up, on the new training set.
        rep = json.loads((self.bench / "eval_report.json").read_text())
        runs = {r["cand"]: r for r in json.loads((self.bench / "runs.json").read_text())["runs"]}
        if self.prev:              # validation scores as of the live version, for the before/after lines
            for r in self.prev["retrained"]:
                if r["cand"] in runs:
                    runs[r["cand"]] = {**runs[r["cand"]], "val_score": r["val_after"]}
        from backend.schemas import CandidateRun
        winner_id = self.prev["winner"] if self.prev else rep.get("winner")
        if winner_id not in runs:
            raise ValueError(f"the base run has no record of its winner {winner_id}")
        # Runner-up: the best other finalist on the winner's rung of the ladder. It can take the winner's place
        # (as the cascade's first stage, if the live version is a cascade); later cascade stages are kept as they are.
        later = set(((rep.get("cascade") or {}).get("stages") and [s["cand"] for s in rep["cascade"]["stages"][1:]]) or [])
        tier = TIER.get(runs[winner_id]["family"])
        others = sorted([r for r in runs.values() if r["cand"] != winner_id and r["cand"] not in later
                         and r["status"] == "done" and TIER.get(r["family"]) == tier and r.get("val_score") is not None
                         and r["round_reached"] == runs[winner_id]["round_reached"]],
                        key=lambda r: -r["val_score"])
        picks = [CandidateRun.model_validate(runs[winner_id])] + [CandidateRun.model_validate(r) for r in others[:1]]
        trainer = Trainer(card, self.dir, paths.train, paths.val, labels, self.emit, self.spend, self.budget,
                          llm=self.llm)
        self.emit("Trainer", "train", f"Trainer: retraining {' and '.join(p.cand for p in picks)} on the corrected "
                  "training set", kind="round", data={"round": 1, "n_rounds": 1, "data_frac": 1.0, "n": len(picks),
                                                      "cands": [p.cand for p in picks]})
        results = trainer.retrain(picks, tag="improve")
        scored = []
        for p, res in zip(picks, results):
            if res["status"] != "done":
                self.emit("Trainer", "train", f"Trainer: {p.cand} failed to retrain ({(res.get('error') or res['status'])[:120]})",
                          kind="candidate", data={"cand": p.cand, "family": p.family, "status": "failed"})
                continue
            m = json.loads(Path(res["metrics_path"]).read_text())
            scored.append((p, res, m))
            self.emit("Trainer", "train", "", kind="candidate",
                      data={"cand": p.cand, "family": p.family, "round": 1, "data_frac": 1.0, "val": res["primary"],
                            "cost_per_1m_usd": m["cost_per_1m_usd"], "p50_ms": m["p50_ms"], "status": "done"})
            self.emit("Evaluator", "validate", f"Evaluator: {p.cand} {card.optimization_metric} on validation "
                      f"{p.val_score:.3f} before, {res['primary']:.3f} with the corrections")
        if not scored:
            raise RuntimeError("no configuration retrained successfully")
        best_p, best_res, best_m = max(scored, key=lambda s: s[1]["primary"])
        for p, _, _ in scored:
            if p is not best_p:
                self.emit("Evaluator", "validate", "", kind="candidate", data={
                    "cand": p.cand, "family": p.family, "status": "eliminated", "round": 1,
                    "reason": f"{card.optimization_metric} lower on validation than {best_p.cand}"})
        self.emit("Evaluator", "validate", f"Evaluator: {best_p.cand} is better on validation "
                  f"({best_res['primary']:.3f}); it gets the final exam")

        # Evaluator: calibration, threshold, and the same cascade wrapper as the live version.
        wdir = Path(best_res["metrics_path"]).parent
        model = Candidate.load(wdir, llm=self.llm)
        P, ids = ev.load_val_proba(wdir)
        val = load_split(paths.val)
        by_id = {r["id"]: r for r in val}
        yv = np.array([labels.index(by_id[i]["label"]) for i in ids])
        calibrator, cal = ev.calibration_report(P, yv)
        threshold = None
        if card.positive_definition:
            yl = [by_id[i]["label"] for i in ids]
            _, threshold = M.recall_at_fpr(np.array([y == card.positive_definition for y in yl]),
                                           calibrator.apply(P)[:, labels.index(card.positive_definition)],
                                           card.fpr_target or 0.01)
        chosen, chosen_id, stage_costs = model, best_p.cand, [best_m["cost_per_1m_usd"]]
        live_model = Candidate.load(registry.ensure_bundle(self.v.specialist_id, live.version), llm=self.llm)
        if isinstance(live_model, CascadeH):
            chosen = CascadeH([model] + live_model.stages[1:], live_model.taus,
                              [calibrator] + list(live_model.calibrators[1:]),
                              names=[best_p.cand] + live_model.names[1:])
            chosen_id = f"H({'→'.join(chosen.names)})"
            pts = {p["cand"]: p for p in rep["pareto_points"]}
            stage_costs += [pts.get(n, {}).get("cost_per_1m_usd") for n in live_model.names[1:]]
            self.emit("Evaluator", "validate", f"Evaluator: keeping the live cascade's later stages and thresholds: "
                      f"{chosen_id}")

        # Final exam on the fixed benchmark, then the version gate against the live version.
        self._check_budget()
        final = ev.final_exam(card, self.dir, self.bench, chosen, labels, calibrator, threshold, self.emit)
        passed, reason = ev.version_gate(card, final, live.sealed_metrics)
        self.emit("Evaluator", "gate", f"Version gate: {'pass' if passed else 'fail'}: {reason}",
                  kind="pareto", data={"gate": {"passed": passed, "reason": reason, "new": final["primary"],
                                                "live": live.sealed_metrics.get("primary"), "live_version": live.version}})
        cost = self._cost(final, stage_costs, chosen)
        self._deploy(chosen, chosen_id, labels, calibrator, threshold, final, passed, reason, cost, best_m)
        self._report(final, passed, reason, chosen_id, best_p, best_res, scored, cost, len(variants))

    def _check_budget(self):
        if self.spend() >= self.budget:
            raise BudgetExceeded(f"LLM spend reached the budget of ${self.budget:.2f}")

    def _variants(self, labels: list[str]) -> list[dict]:
        """A few targeted variants per correction, written by the teacher in the same style (training set only)."""
        if not self.corrections:
            return []
        items = "\n".join(f"- \"{c['input'][:300]}\" is {c['corrected_label']}" for c in self.corrections)
        prompt = (f"Task: {self.card.description}\nA user corrected these predictions:\n{items}\n"
                  f"For each, write {VARIANTS_PER_CORRECTION} new realistic inputs of the same category, in exactly the "
                  "same style, casing and length, that a model could otherwise confuse the same way. "
                  'Return JSON: {"variants": [{"text": "...", "label": "<the corrected category>"}]}')
        try:
            res = self.llm.chat("main_chat_planner_teacher_baseline", [{"role": "user", "content": prompt}],
                                agent="Data", purpose="improve_variants", max_tokens=2500, temperature=0.7,
                                thinking=False, response_format={"type": "json_object"})
            out = [v for v in res.json().get("variants", []) if isinstance(v, dict)
                   and isinstance(v.get("text"), str) and v.get("label") in labels and v["text"].strip()]
        except BudgetExceeded:
            raise
        except Exception as exc:     # variants are optional; the corrections alone still train
            self.emit("Data", "data", f"Couldn't write variants ({type(exc).__name__}); training on the corrections only")
            return []
        out = out[:len(self.corrections) * VARIANTS_PER_CORRECTION]
        return [{"id": f"corr-var-{i}", "text": v["text"].strip(), "label": v["label"], "synthetic": True}
                for i, v in enumerate(out)]

    @staticmethod
    def _cost(final: dict, stage_costs: list, chosen) -> float | None:
        """Cost per 1M predictions: each stage's measured cost weighted by its share on the sealed test set."""
        if not isinstance(chosen, CascadeH):
            return stage_costs[0]
        shares = list((final.get("stage_shares") or {}).values())
        if len(shares) != len(stage_costs) or any(c is None for c in stage_costs):
            return None
        reach = [sum(shares[k:]) for k in range(len(shares))]
        return float(sum(r * c for r, c in zip(reach, stage_costs)))

    def _deploy(self, model, cand_id, labels, calibrator, threshold, final, passed, reason, cost, metrics):
        bundle = self.dir / "bundle"
        if bundle.exists():
            shutil.rmtree(bundle)
        model.save(bundle)
        meta = registry.bundle_meta(self.v.specialist_id, self.live.version)
        meta.update({"candidate": cand_id, "family": model.family, "run_id": self.run_id, "threshold": threshold,
                     "calibrator_T": None if isinstance(model, CascadeH) else calibrator.T,
                     "uses_cloud": bool(model.uses_cloud), "cost_per_1m_usd": cost,
                     # p50 is the new first stage's measured latency (it answers most items); a cascade's p99 is set
                     # by its later stages, which are unchanged, so it carries over from the live version
                     "p50_ms": metrics.get("p50_ms"),
                     "p99_ms": metrics.get("p99_ms") if not isinstance(model, CascadeH) else meta.get("p99_ms"),
                     "improved_from": self.live.version, "corrections": len(self.corrections)})
        (bundle / "bundle.json").write_text(json.dumps(meta, indent=2))
        summary = {k: final.get(k) for k in ("primary", "primary_metric", "macro_f1", "accuracy", "pr_auc",
                                              "recall_at_fpr", "per_class", "at_val_threshold", "escalation_rate",
                                              "stage_shares", "n")}
        v = registry.load(self.v.specialist_id)
        rec = registry.add_version(v, self.run_id, bundle, summary, passed, reason, cand_id)
        self.result = {"specialist_id": v.specialist_id, "version": rec.version, "deployed": passed, "reason": reason,
                       "previous_live": self.live.version}
        self.emit("Deploy", "deploy", f"Deployed v{rec.version}; v{self.live.version} stays available for rollback"
                  if passed else f"v{rec.version} not deployed: {reason}. v{self.live.version} stays live.",
                  kind="handoff", data=self.result, data_ref="improve_report.json")

    def _report(self, final, passed, reason, chosen_id, best_p, best_res, scored, cost, n_variants):
        live = self.live
        rep = {
            "run_id": self.run_id, "kind": "improve", "specialist_id": self.v.specialist_id,
            "base_run_id": live.run_id, "benchmark_run_id": self.bench.name, "live_version_before": live.version,
            "new_version": self.result["version"], "corrections": len(self.corrections), "variants": n_variants,
            "chosen": chosen_id, "winner": best_p.cand,
            "retrained": [{"cand": p.cand, "family": p.family, "val_before": p.val_score, "val_after": r["primary"]}
                          for p, r, _ in scored],
            "sealed_benchmark": f"the sealed test set of run {self.bench.name} (the one v{live.version} was scored on)",
            "final": final, "live_final": live.sealed_metrics, "cost_per_1m_usd": cost,
            "gate": {"passed": passed, "reason": reason, "target": self.card.thresholds.model_dump()},
        }
        (self.dir / "improve_report.json").write_text(json.dumps(rep, indent=2, default=float))
        base_rc = self.base / "report_card.json"
        rc = json.loads(base_rc.read_text()) if base_rc.exists() else {}
        rc.update({"run_id": self.run_id, "sealed": final, "improve": rep, "cost_per_1m_usd": cost,
                   "decision": {"passes_thresholds": passed, "reason": reason, "target": self.card.thresholds.model_dump()}})
        rc.setdefault("winner", {})["candidate"] = chosen_id
        rc["pareto_points"] = [{k: v for k, v in pt.items() if k != "metrics_path"}     # paths on the base machine
                               for pt in rc.get("pareto_points", [])]
        if rc.get("monthly_volume") and rc.get("baseline", {}).get("cost_per_1m_usd") and cost is not None:
            yearly = rc["monthly_volume"] * 12 / 1e6
            rc["projection"] = {**rc.get("projection", {}), "specialist_yearly_usd": cost * yearly}
        (self.dir / "report_card.json").write_text(json.dumps(rc, indent=2, default=float))
        (self.dir / "report_card.md").write_text(improve_markdown(rep, self.card, self.v.display_name))
        self.emit("Evaluator", "report", "Report card ready", data_ref="report_card.json", kind="handoff")


def improve_markdown(rep: dict, card: TaskCard, name: str) -> str:
    f, lf, metric = rep["final"], rep["live_final"] or {}, card.optimization_metric
    g = rep["gate"]
    lines = [f"# {name} v{rep['new_version']}: improve run", "",
             f"**Gate: {'passed, deployed' if g['passed'] else 'failed, not deployed'}.** {g['reason']}.", "",
             f"- Corrections added to the training set only: {rep['corrections']:,}"
             + (f" (plus {rep['variants']} targeted variants written by Nemotron Ultra)" if rep["variants"] else ""),
             f"- Retrained: " + ", ".join(f"{r['cand']} (validation {r['val_before']:.3f} → {r['val_after']:.3f})"
                                          for r in rep["retrained"]),
             f"- Shipped as: {rep['chosen']}",
             f"- Fixed benchmark: {rep['sealed_benchmark']}; corrections never enter it.", "",
             "## Sealed test set", "",
             f"| | v{rep['live_version_before']} (live before) | v{rep['new_version']} (this run) |", "|---|---|---|",
             f"| {metric} | {lf.get('primary', float('nan')):.3f} | {f['primary']:.3f} |",
             f"| records | {lf.get('n', 'n/a')} | {f.get('n', 'n/a')} |"]
    if f.get("stage_shares"):
        lines.append("| answered by | " + " / ".join(f"{k} {v:.0%}" for k, v in (lf.get("stage_shares") or {}).items())
                     + " | " + " / ".join(f"{k} {v:.0%}" for k, v in f["stage_shares"].items()) + " |")
    if rep.get("cost_per_1m_usd") is not None:
        lines.append(f"| cost per 1M predictions | | ${rep['cost_per_1m_usd']:.4f} |")
    lines += ["", "## Per class (this run, sealed test set)", "", "| class | precision | recall | n |", "|---|---|---|---|"]
    for k, m in (f.get("per_class") or {}).items():
        lines.append(f"| {k} | {m['precision']:.2f} | {m['recall']:.2f} | {int(m.get('support', 0))} |")
    return "\n".join(lines) + "\n"


def recorded_improve(task_id: str) -> str | None:
    """A recorded improve run for replay mode (run folder with replay.ok)."""
    for p in sorted(config.runs_dir().glob("*/run_state.json")):
        try:
            s = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if s.get("kind") == "improve" and s.get("task_id") == task_id and s.get("status") == "done" \
                and (p.parent / "replay.ok").exists():
            return p.parent.name
    return None
