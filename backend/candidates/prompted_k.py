"""K and L: prompted Nemotron with retrieved labeled examples and constrained JSON output.

No fine-tuning. "Training" builds the retrieval pool; search varies instruction wording and the number
of retrieved examples (0, 5, 10). Reasoning is turned off for these calls (VERIFICATION.md).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from backend import config
from backend.candidates.base import Candidate, prep_text

INSTRUCTIONS = [
    "Classify the input into exactly one category.",
    "You are an expert analyst. Read the input carefully and choose the single best-fitting category. "
    "When it is ambiguous, prefer the category whose definition matches the main item or activity described.",
]


class RateLimiter:
    """Spaces calls to stay under a model's requests-per-minute limit (from config/models.yaml)."""
    _locks: dict[str, threading.Lock] = {}
    _next: dict[str, float] = {}

    @classmethod
    def wait(cls, model: str, rpm: int):
        lock = cls._locks.setdefault(model, threading.Lock())
        with lock:
            now = time.monotonic()
            t = max(now, cls._next.get(model, 0.0))
            cls._next[model] = t + 60.0 / (rpm * 0.9)
        if t > now:
            time.sleep(t - now)


def clip_window(text: str, head: int = 40, tail: int = 15) -> str:
    lines = text.splitlines()
    if len(lines) <= head + tail:
        return text
    return "\n".join(lines[:head] + [f"... ({len(lines) - head - tail} lines omitted) ..."] + lines[-tail:])


class PromptedK(Candidate):
    family, rung, uses_cloud = "K", 3, True
    default_role = "ladder_K_primary"

    def __init__(self, params, ctx):
        super().__init__(params, ctx)
        self.role = params.get("role", self.default_role)
        self.calls: list[dict] = []
        self._calls_lock = threading.Lock()

    def __getstate__(self):
        state = super().__getstate__()
        state.pop("_calls_lock", None)
        return state

    def attach(self, llm):
        self._calls_lock = threading.Lock()

    def fit(self, texts, y, progress=None):
        self.pool_texts = list(texts)
        self.pool_y = list(y)
        self.k = int(self.params.get("n_examples", 5))
        if self.k:
            self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1, max_features=50000)
            self.P = self.vec.fit_transform([prep_text(t, self.ctx.input_type) for t in texts])
        if progress:
            progress({"step": 1, "pool": len(texts)})

    def _show(self, text):
        return clip_window(text) if self.ctx.input_type == "log_window" else text

    def _messages(self, text):
        defs = "\n".join(f"- {l}: {self.ctx.label_definitions.get(l, '')}".rstrip(": ") for l in self.labels)
        instr = INSTRUCTIONS[int(self.params.get("instruction", 0)) % len(INSTRUCTIONS)]
        system = (f"Task: {self.ctx.task_description}\n{instr}\nCategories:\n{defs}\n"
                  "Respond only with JSON matching the schema. confidence is your probability (0 to 1) that the label is right.")
        user = ""
        if self.k:
            q = self.vec.transform([prep_text(text, self.ctx.input_type)])
            sims = (self.P @ q.T).toarray().ravel()
            for j in np.argsort(-sims)[:self.k][::-1]:
                user += f"Example input:\n{self._show(self.pool_texts[j])}\nLabel: {self.pool_y[j]}\n\n"
        user += f"Input:\n{self._show(text)}"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _schema(self):
        props = {"label": {"type": "string", "enum": self.labels}, "confidence": {"type": "number"}}
        req = ["label", "confidence"]
        if self.ctx.needs_reason:
            props["reason"] = {"type": "string"}
            req.append("reason")
        return {"type": "json_schema", "json_schema": {"name": "prediction", "strict": True, "schema": {
            "type": "object", "properties": props, "required": req, "additionalProperties": False}}}

    def predict_one(self, text):
        rpm = int(config.models()[self.role].get("rate_limit", {}).get("requests_per_minute", 100))
        api_id = config.model_id(self.role)
        res = None
        for attempt in range(2):
            try:
                res = self.ctx.llm.chat(self.role, self._messages(text), agent="Trainer", purpose=f"rung_{self.family}",
                                        max_tokens=200, temperature=0.0, thinking=False,
                                        response_format=self._schema())
                if not res.cached:
                    RateLimiter.wait(api_id, rpm)
                out = res.json()
                break
            except Exception as exc:
                out = {"label": None, "confidence": 0.0, "error": str(exc)[:200]}
        with self._calls_lock:
            self.calls.append({"prompt_tokens": res.prompt_tokens if res else 0,
                               "completion_tokens": res.completion_tokens if res else 0,
                               "latency_ms": res.latency_ms if res else None,
                               "list_cost_usd": res.list_cost_usd if res else 0.0, "ok": out.get("label") is not None})
        return out

    def predict_full(self, texts):
        with ThreadPoolExecutor(max_workers=int(self.params.get("concurrency", 8))) as ex:
            return list(ex.map(self.predict_one, texts))

    def predict_proba(self, texts):
        outs = self.predict_full(texts)
        self._last = outs
        idx = {l: i for i, l in enumerate(self.labels)}
        P = np.full((len(texts), len(self.labels)), 0.0)
        for i, o in enumerate(outs):
            lab = o.get("label")
            if lab not in idx:
                P[i] = 1.0 / len(self.labels)
                continue
            c = float(np.clip(o.get("confidence", 0.5) or 0.5, 0.01, 0.999))
            P[i] = (1 - c) / max(len(self.labels) - 1, 1)
            P[i, idx[lab]] = c
        return P

    def reason(self, text, proba):
        if self.ctx.needs_reason:
            return self.predict_one(text).get("reason")
        return None

    def usage_stats(self):
        ok = [c for c in self.calls if c["latency_ms"] is not None]
        if not ok:
            return None
        lat = np.array([c["latency_ms"] for c in ok])
        return {"role": self.role, "mean_prompt_tokens": float(np.mean([c["prompt_tokens"] for c in ok])),
                "mean_completion_tokens": float(np.mean([c["completion_tokens"] for c in ok])),
                "p50_ms": float(np.percentile(lat, 50)), "p99_ms": float(np.percentile(lat, 99)),
                "n_calls": len(ok), "failed": sum(not c["ok"] for c in self.calls)}


class PromptedL(PromptedK):
    family = "L"
    default_role = "ladder_L"
