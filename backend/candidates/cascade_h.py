"""H: cascade wrapper. The cheap model answers confident cases; uncertain ones escalate to a prompted LLM."""
from __future__ import annotations

import numpy as np

from backend.candidates.base import Candidate


class CascadeH(Candidate):
    family, rung, uses_cloud = "H", 0, True

    def __init__(self, base: Candidate, fallback: Candidate, tau: float, calibrator=None):
        super().__init__({"tau": tau, "base": base.family, "fallback": fallback.family}, base.ctx)
        self.base, self.fallback, self.tau, self.calibrator = base, fallback, tau, calibrator
        self.last_escalated = 0

    def attach(self, llm):
        self.base.ctx.llm = llm
        self.fallback.ctx.llm = llm
        self.base.attach(llm)
        self.fallback.attach(llm)

    def base_proba(self, texts):
        P = self.base.predict_proba(texts)
        return self.calibrator.apply(P) if self.calibrator else P

    def predict_proba(self, texts):
        P = self.base_proba(texts)
        esc = np.where(P.max(axis=1) < self.tau)[0]
        self.last_escalated = len(esc)
        if len(esc):
            P[esc] = self.fallback.predict_proba([texts[i] for i in esc])
        return P

    def escalated(self, proba_row) -> bool:
        return float(np.max(proba_row)) < self.tau

    def reason(self, text, proba):
        P = self.base_proba([text])[0]
        if P.max() < self.tau:
            return f"Escalated: the fast model was only {P.max():.0%} sure, so {self.fallback.family} answered."
        return self.base.reason(text, P)
