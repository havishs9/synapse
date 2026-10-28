"""Load a version bundle and serve predictions: label, confidence, reason, escalation flag."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from backend.candidates import Candidate, CascadeH
from backend.features.logs import BLOCK_RE, parse_line

MAX_TEXT_CHARS = 2000
MAX_WINDOW_LINES = 2000


class InputError(ValueError):
    pass


def validate(text: str, input_type: str, expected: str = "one text record") -> str:
    if not isinstance(text, str) or not text.strip():
        raise InputError("Input is empty. Paste one record (or one log window for log tasks).")
    text = text.strip()
    if input_type == "log_window":
        lines = [l for l in text.splitlines() if l.strip()]
        if len(lines) > MAX_WINDOW_LINES:
            raise InputError(f"Log window has {len(lines)} lines; the limit is {MAX_WINDOW_LINES}. Send one block's lines.")
        parsed = sum(parse_line(l) is not None for l in lines)
        if parsed == 0:
            raise InputError("This doesn't look like HDFS log lines. Expected lines like "
                             "'081109 203518 143 INFO dfs.DataNode$DataXceiver: Receiving block blk_…'.")
        blocks = {b for l in lines for b in BLOCK_RE.findall(l)}
        if not blocks:
            raise InputError("No block ID (blk_…) found. A log window is all lines for one block.")
        return text
    if len(text) > MAX_TEXT_CHARS:
        raise InputError(f"Record is {len(text)} characters; the limit is {MAX_TEXT_CHARS}. Send one record at a time.")
    if sum(parse_line(l) is not None for l in text.splitlines()) >= 2:
        raise InputError(f"This looks like log lines, but this specialist expects {expected[0].lower() + expected[1:]}.")
    if not any(c.isalpha() for c in text):
        raise InputError("Record has no letters. Send the record's text.")
    return text


class Predictor:
    def __init__(self, bundle_dir: Path, llm=None):
        self.dir = Path(bundle_dir)
        self.meta = json.loads((self.dir / "bundle.json").read_text())
        self.model: Candidate = Candidate.load(self.dir, llm=llm)
        self.labels = self.meta["labels"]
        self.T = self.meta.get("calibrator_T")

    def _calibrate(self, P):
        if self.T is None or isinstance(self.model, CascadeH):
            return P
        z = np.log(np.clip(P, 1e-9, 1)) / self.T
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def _label(self, p: np.ndarray) -> tuple[str, float]:
        thr, pos = self.meta.get("threshold"), self.meta.get("positive")
        if thr is not None and pos is not None and len(self.labels) == 2:
            pi = self.labels.index(pos)
            lab = pos if p[pi] > thr else self.labels[1 - pi]
            return lab, float(p[self.labels.index(lab)])
        k = int(np.argmax(p))
        return self.labels[k], float(p[k])

    def explain(self, text: str, pred: dict) -> str | None:
        """Teacher explains a flag: Nemotron Ultra reads the input plus the specialist's feature-based reason.

        This is a cloud call and is labeled as such wherever it's shown.
        """
        llm = self.model.ctx.llm
        if llm is None:
            return None
        from backend.candidates.prompted_k import clip_window
        shown = clip_window(text) if self.meta["input_type"] == "log_window" else text
        prompt = (f"A small specialist model for this task: {self.meta['task_name']} labeled the input below as "
                  f"\"{pred['label']}\" ({pred['confidence']:.0%} confidence). Its feature-based reason: "
                  f"{pred.get('reason') or 'none'}.\n\nInput:\n{shown}\n\nIn at most three sentences, explain to an "
                  "operator what in the input supports or contradicts this label. Quote the specific evidence. "
                  "If the label looks wrong, say so.")
        res = llm.chat("main_chat_planner_teacher_baseline", [{"role": "user", "content": prompt}], agent="Evaluator",
                       purpose="teacher_explains_flag", max_tokens=300, temperature=0.2, thinking=False)
        return res.content.strip()

    def predict(self, texts: list[str], with_reason: bool | None = None, explain: bool = False) -> list[dict]:
        texts = [validate(t, self.meta["input_type"], self.meta.get("expected_format") or "One text record")
                 for t in texts]
        with_reason = self.meta.get("needs_reason", False) if with_reason is None else with_reason
        t0 = time.perf_counter()
        cascade = isinstance(self.model, CascadeH)
        P = self._calibrate(self.model.predict_proba(texts))
        stage = self.model.last_stage if cascade else None
        ms = (time.perf_counter() - t0) * 1000 / max(len(texts), 1)
        out = []
        for i, (t, p) in enumerate(zip(texts, P)):
            label, conf = self._label(p)
            item = {"label": label, "confidence": round(conf, 4), "latency_ms": round(ms, 3),
                    "escalated": bool(cascade and stage[i] > 0)}
            if cascade:
                item["answered_by"] = self.model.names[int(stage[i])]
            if self.meta.get("positive"):
                item["score"] = round(float(p[self.labels.index(self.meta["positive"])]), 4)
            if with_reason:
                try:
                    item["reason"] = (self.model.reason(t, p, stage=int(stage[i])) if cascade
                                      else self.model.reason(t, p))
                except Exception:
                    item["reason"] = None
            flagged = self.meta.get("positive") is None or label == self.meta.get("positive")
            if explain and flagged:
                try:
                    item["teacher_explanation"] = self.explain(t, item)
                    item["teacher_model"] = "Nemotron Ultra (cloud call)"
                except Exception as exc:
                    item["teacher_explanation_error"] = f"Explanation unavailable ({type(exc).__name__})"
            out.append(item)
        return out
