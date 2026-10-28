"""J: learned keyword rules. A token (or log event) votes for a class when that class is its majority
in training with enough support and precision. Unmatched inputs fall back to class priors (low confidence)."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import numpy as np

from backend.candidates.base import Candidate, prep_text

STOP = set("the a an of and or for to in on at by with from as is are be this that it its per no non "
           "other services service support".split())


def tokens(text: str, input_type: str, parser=None) -> set[str]:
    if input_type == "log_window" and parser is not None:
        from backend.features.logs import parse_line
        out = set()
        for line in text.splitlines():
            p = parse_line(line)
            out.add(parser.event_id(p["content"] if p else line))
        return out
    words = [w for w in re.findall(r"[a-z][a-z0-9\-]+", text.lower()) if w not in STOP and len(w) > 2]
    return set(words) | {f"{a} {b}" for a, b in zip(words, words[1:])}


class RulesJ(Candidate):
    family, rung = "J", 1

    def _parser(self):
        if self.ctx.input_type == "log_window" and self.ctx.log_templates:
            from backend.features.logs import TemplateParser
            if not hasattr(self, "_p"):
                self._p = TemplateParser(self.ctx.log_templates)
            return self._p
        return None

    def __getstate__(self):
        state = super().__getstate__()
        state.pop("_p", None)
        return state

    def fit(self, texts, y, progress=None):
        min_support = int(self.params.get("min_support", 10))
        min_precision = float(self.params.get("min_precision", 0.8))
        parser = self._parser()
        counts: dict[str, Counter] = defaultdict(Counter)
        for t, label in zip(texts, y):
            for tok in tokens(prep_text(t, self.ctx.input_type), self.ctx.input_type, parser):
                counts[tok][label] += 1
        self.rules = {}
        for tok, c in counts.items():
            n = sum(c.values())
            label, k = c.most_common(1)[0]
            if n >= min_support and k / n >= min_precision:
                self.rules[tok] = (label, k / n, n)
        prior = Counter(y)
        self.prior = np.array([prior.get(l, 0) for l in self.labels], float)
        self.prior /= self.prior.sum()
        if progress:
            progress({"step": 1, "rules": len(self.rules)})

    def _match(self, text):
        best = None
        for tok in tokens(prep_text(text, self.ctx.input_type), self.ctx.input_type, self._parser()):
            r = self.rules.get(tok)
            if r and (best is None or (r[1], r[2]) > (best[1][1], best[1][2])):
                best = (tok, r)
        return best

    def predict_proba(self, texts):
        idx = {l: i for i, l in enumerate(self.labels)}
        out = np.tile(self.prior, (len(texts), 1))
        for i, t in enumerate(texts):
            m = self._match(t)
            if m:
                label, prec, _ = m[1]
                row = np.full(len(self.labels), (1 - prec) / max(len(self.labels) - 1, 1))
                row[idx[label]] = prec
                out[i] = row
        return out

    def reason(self, text, proba):
        m = self._match(text)
        if not m:
            return "No rule matched; answered with the most common category."
        tok, (label, prec, n) = m
        if self.ctx.input_type == "log_window":
            return f"Contains event {tok}; {prec:.0%} of {n} training windows with it were {label}."
        return f"Matched keyword \"{tok}\": {prec:.0%} of {n} training records with it are {label}."
