"""Calibration, cascade threshold choice and the search's cost frontier."""
import numpy as np

from backend.agents import evaluator_agent as ev
from backend.agents.trainer_agent import cost_frontier
from backend.schemas import Label, TaskCard, Thresholds


def card():
    return TaskCard(task_id="t", task_name="T", description="d", input_type="text", output_type="multiclass",
                    labels=[Label(name="a"), Label(name="b")], thresholds=Thresholds(primary_min=0.5))


def test_calibration_fixes_overconfidence():
    rng = np.random.default_rng(0)
    n, y = 2000, rng.integers(0, 3, 2000)
    right = rng.random(n) < 0.6                       # 60% accurate but always 95% confident
    pred = np.where(right, y, (y + 1) % 3)
    P = np.full((n, 3), 0.025)
    P[np.arange(n), pred] = 0.95
    cal, rep = ev.calibration_report(P, y)
    assert not rep.get("skipped") and cal.T > 1
    assert rep["ece_after_crossfit"] < rep["ece_before"]


def test_calibration_skipped_when_it_does_not_help():
    y = np.arange(300) % 3
    P = np.zeros((300, 3))
    P[np.arange(300), y] = 1.0                        # already perfectly calibrated: ECE 0
    cal, rep = ev.calibration_report(P, y)
    assert rep["skipped"] and cal.T == 1.0
    assert np.allclose(cal.apply(P), P)


def test_cascade_takes_least_escalation_within_tolerance():
    labels, n = ["a", "b"], 300
    y = [labels[i % 2] for i in range(n)]
    val = [{"id": f"r{i}", "label": y[i]} for i in range(n)]
    ids = [r["id"] for r in val]
    base = np.zeros((n, 2))
    for i in range(n):
        t = i % 2
        if i < 250:                                   # confident, one mistake
            base[i, 1 - t if i == 0 else t], base[i, t if i == 0 else 1 - t] = 0.9, 0.1
        else:                                         # unsure
            base[i] = 0.5
    llm = np.zeros((n, 2))
    llm[np.arange(n), [i % 2 for i in range(n)]] = 0.99
    llm[:, :] += 0.005
    res = ev.fit_cascade(card(), labels, val, base, ids, llm, ids, ev.TemperatureCalibrator(1.0))
    # Escalating everything (tau 0.95) fixes the one confident mistake, but only gains ~0.003: not worth
    # paying for 100% escalation. The cheapest threshold within tolerance escalates just the unsure sixth.
    assert res["best_primary_any_tau"] - res["primary"] <= ev.CASCADE_TOLERANCE
    assert res["escalation_rate"] == 50 / 300


def test_cost_frontier_keeps_cheap_nearly_as_good():
    scored = [("I-06", 0.651, 0.46), ("I-04", 0.641, 0.46), ("A-05", 0.63, 0.0009), ("J-01", 0.40, 0.0001),
              ("C-02", 0.456, 0.07), ("K-03", 0.60, 30.0)]
    assert cost_frontier(scored) == {"I-06", "A-05", "J-01"}


def test_search_carries_cheap_candidate_to_final_round(tmp_env):
    """Round ranking alone would cut A (cheap, slightly lower score) before the final cheapest-passing choice."""
    import json
    from backend.agents.trainer_agent import Trainer
    from backend.schemas import CandidatePlan, CandidateSpec

    scores = {"I-01": (0.65, 0.46), "I-02": (0.64, 0.46), "K-01": (0.62, 30.0), "K-02": (0.61, 30.0),
              "A-01": (0.60, 0.0009), "C-01": (0.45, 0.07)}
    run_dir = tmp_env / "runs" / "r"
    run_dir.mkdir()

    class FakeLauncher:
        def run(self, jobs, on_event):
            out = []
            for j in jobs:
                score, cost = scores[j["cand"]]
                m = run_dir / j["cand"] / f"r{j['round']}" / "metrics.json"
                m.parent.mkdir(parents=True, exist_ok=True)
                m.write_text(json.dumps({"cost_per_1m_usd": cost}))
                out.append({"cand": j["cand"], "status": "done", "primary": score, "secondary": score,
                            "metrics_path": str(m)})
            return out

    t = Trainer(card(), run_dir, run_dir / "train.jsonl", run_dir / "val.jsonl", ["a", "b"],
                lambda *a, **k: None, lambda: 0.0, 5.0)
    t.launcher = FakeLauncher()
    plan = CandidatePlan(candidates=[CandidateSpec(id=c, family=c[0], rung=1, params={}) for c in scores],
                         excluded={}, summary="", planner_source="deterministic_fallback")
    final = {r.cand for r in t.search(plan, [0.1, 0.4, 1.0])}
    assert {"I-01", "A-01"} <= final and "C-01" not in final
    assert "cheaper candidate" in t.runs["C-01"].elimination_reason
