"""H: cascade wrapper. Stages run from cheapest to most expensive; each answers the items it is confident about
and passes the rest on. The last stage (usually a prompted LLM) answers whatever is left.

Typical chains: TF-IDF → prompted Nano, or TF-IDF → embeddings + MLP → prompted Nano.
"""
from __future__ import annotations

import numpy as np

from backend.candidates.base import Candidate


class CascadeH(Candidate):
    family, rung, uses_cloud = "H", 0, True

    def __init__(self, stages: list[Candidate], taus: list[float], calibrators: list | None = None,
                 names: list[str] | None = None):
        """`taus[k]` is stage k's confidence threshold (one per stage except the last); `calibrators[k]` maps
        stage k's probabilities before the threshold test (None = raw)."""
        assert len(stages) >= 2 and len(taus) == len(stages) - 1
        super().__init__({"taus": list(taus), "stages": [s.family for s in stages]}, stages[0].ctx)
        self.stages, self.taus = list(stages), [float(t) for t in taus]
        self.calibrators = list(calibrators) if calibrators else [None] * (len(stages) - 1)
        self.names = list(names) if names else [s.family for s in stages]
        self.last_escalated, self.last_stage_counts, self.last_stage = 0, [0] * len(stages), np.zeros(0, int)
        self.uses_cloud = any(s.uses_cloud for s in self.stages)

    def __setstate__(self, state):
        # Bundles saved before N-stage cascades stored a single base → fallback pair.
        if "stages" not in state and "base" in state:
            state["stages"] = [state.pop("base"), state.pop("fallback")]
            state["taus"] = [state.pop("tau")]
            state["calibrators"] = [state.pop("calibrator", None)]
            state["names"] = [s.family for s in state["stages"]]
            state.setdefault("last_stage_counts", [0, 0])
            state.setdefault("last_stage", np.zeros(0, int))
        self.__dict__.update(state)

    # Compatibility for code that thinks in base / fallback / tau.
    @property
    def base(self) -> Candidate:
        return self.stages[0]

    @property
    def fallback(self) -> Candidate:
        return self.stages[-1]

    @property
    def tau(self) -> float:
        return self.taus[0]

    def attach(self, llm):
        for s in self.stages:
            s.ctx.llm = llm
            s.attach(llm)

    def _stage_proba(self, k: int, texts):
        P = self.stages[k].predict_proba(texts)
        cal = self.calibrators[k] if k < len(self.calibrators) else None
        return cal.apply(P) if cal else P

    def base_proba(self, texts):
        return self._stage_proba(0, texts)

    def predict_proba(self, texts):
        """Probabilities from whichever stage answered each item; `last_stage[i]` says which one."""
        P = self.base_proba(texts)
        stage = np.zeros(len(texts), int)
        todo = np.where(P.max(axis=1) < self.taus[0])[0]
        for k in range(1, len(self.stages)):
            if not len(todo):
                break
            Pk = self._stage_proba(k, [texts[i] for i in todo])
            P[todo], stage[todo] = Pk, k
            if k < len(self.stages) - 1:
                todo = todo[Pk.max(axis=1) < self.taus[k]]
        self.last_stage = stage
        self.last_stage_counts = [int((stage == k).sum()) for k in range(len(self.stages))]
        self.last_escalated = int((stage > 0).sum())
        return P

    def escalated(self, proba_row) -> bool:
        return float(np.max(proba_row)) < self.taus[0]

    def reason(self, text, proba, stage: int | None = None):
        if stage is None:
            self.predict_proba([text])
            stage = int(self.last_stage[0])
        if stage == 0:
            return self.stages[0].reason(text, self.base_proba([text])[0])
        why = f"Escalated: the earlier stage(s) weren't confident enough, so {self.names[stage]} answered."
        try:
            inner = self.stages[stage].reason(text, proba)
        except Exception:
            inner = None
        return f"{why} {inner}" if inner else why
