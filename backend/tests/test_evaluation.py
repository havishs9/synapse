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


def _three_stage_case(n=300):
    """Cheap stage sure and right on the first half, embeddings sure and right on the next 30%, LLM always right."""
    labels = ["a", "b"]
    y = [i % 2 for i in range(n)]
    val = [{"id": f"r{i}", "label": labels[y[i]]} for i in range(n)]
    ids = [r["id"] for r in val]
    cheap, mid, llm = np.full((n, 2), 0.5), np.full((n, 2), 0.5), np.full((n, 2), 0.01)
    for i in range(n):
        t = y[i]
        if i < n // 2:
            cheap[i, t], cheap[i, 1 - t] = 0.97, 0.03
        if i < int(n * 0.8):
            mid[i, t], mid[i, 1 - t] = 0.97, 0.03
        llm[i, t] = 0.99
    return labels, val, ids, cheap, mid, llm


def test_three_stage_chain_puts_each_stage_where_it_is_sure():
    labels, val, ids, cheap, mid, llm = _three_stage_case()
    stages = [{"P": cheap, "ids": ids, "cost": 0.001, "calibrator": None},
              {"P": mid, "ids": ids, "cost": 0.5, "calibrator": None},
              {"P": llm, "ids": ids, "cost": 60.0, "calibrator": None}]
    res = ev.fit_cascade_chain(card(), labels, val, stages)
    assert res["primary"] == 1.0
    assert np.allclose(res["shares"], [0.5, 0.3, 0.2])
    # every item pays for stage 0; half reach embeddings; a fifth reach the LLM
    assert abs(res["cost_per_1m_usd"] - (0.001 + 0.5 * 0.5 + 0.2 * 60.0)) < 1e-9


def test_chain_comparison_on_shared_rows():
    labels, val, ids, cheap, mid, llm = _three_stage_case()
    keep = set(ids[::2])
    res = ev.fit_cascade_chain(card(), labels, val, [{"P": cheap, "ids": ids, "cost": 0, "calibrator": None},
                                                      {"P": mid, "ids": ids, "cost": 1, "calibrator": None}],
                               only_ids=keep)
    assert res["n"] == len(keep) and set(res["ids"]) == keep


class _Fixed:
    """Stub stage: returns the stored proba row for each text (texts are row indices as strings)."""
    uses_cloud = False

    def __init__(self, P, family):
        self.P, self.family = P, family
        self.ctx = type("Ctx", (), {"llm": None, "labels": ["a", "b"]})()

    def predict_proba(self, texts):
        return self.P[[int(t) for t in texts]].copy()

    def attach(self, llm):
        pass

    def reason(self, text, proba):
        return f"{self.family} says so"


def test_cascade_h_routes_items_through_stages():
    from backend.candidates.cascade_h import CascadeH
    labels, val, ids, cheap, mid, llm = _three_stage_case(100)
    h = CascadeH([_Fixed(cheap, "A"), _Fixed(mid, "B"), _Fixed(llm, "K")], [0.9, 0.9], names=["A-1", "B-1", "K-1"])
    P = h.predict_proba([str(i) for i in range(100)])
    assert h.last_stage_counts == [50, 30, 20] and h.last_escalated == 50
    assert (P.argmax(1) == np.arange(100) % 2).all()
    assert "K-1 answered" in h.reason("90", P[90], stage=2)


def test_cascade_h_loads_two_stage_bundles():
    from backend.candidates.cascade_h import CascadeH
    labels, val, ids, cheap, mid, llm = _three_stage_case(10)
    old = CascadeH.__new__(CascadeH)
    old.__setstate__({"base": _Fixed(cheap, "A"), "fallback": _Fixed(llm, "K"), "tau": 0.9, "calibrator": None,
                      "params": {}, "labels": labels, "last_escalated": 0})
    old.predict_proba([str(i) for i in range(10)])
    assert old.names == ["A", "K"] and old.last_stage_counts == [5, 5] and old.tau == 0.9
