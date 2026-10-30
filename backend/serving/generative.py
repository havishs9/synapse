"""Serve a rung-G bundle: a small LLM with its LoRA adapter merged in, generating JSON on the endpoint's CPU.

Same response shape as the classifiers (label, confidence, reason, latency_ms) plus `output`, the parsed JSON.
`confidence` is the model's own probability of the sequence it generated (geometric mean over its tokens), not a
calibrated probability; `reason` lists the extracted slots.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from backend.serving.predictor import InputError, validate


def parse_json(text: str) -> dict | None:
    t = text.strip()
    if "</think>" in t:
        t = t.split("</think>", 1)[1].strip()
    try:
        out = json.loads(t[t.index("{"): t.rindex("}") + 1])
        return out if isinstance(out, dict) else None
    except ValueError:
        return None


class GenerativePredictor:
    def __init__(self, bundle_dir: Path, llm=None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.dir = Path(bundle_dir)
        self.meta = json.loads((self.dir / "bundle.json").read_text())
        self.labels = self.meta.get("labels", [])
        self.tok = AutoTokenizer.from_pretrained(self.dir / "model")
        self.tok.padding_side = "left"
        torch.set_num_threads(max(1, int(self.meta.get("threads", 0)) or torch.get_num_threads()))
        dtype = getattr(torch, self.meta.get("dtype", "float32"))
        self.model = AutoModelForCausalLM.from_pretrained(self.dir / "model", dtype=dtype).eval()
        self._lock = threading.Lock()     # one generation at a time on a 2-vCPU server
        self._torch = torch

    def _prompt(self, text: str) -> str:
        return self.tok.apply_chat_template([{"role": "system", "content": self.meta["system_prompt"]},
                                             {"role": "user", "content": text}],
                                            tokenize=False, add_generation_prompt=True, enable_thinking=False)

    def predict(self, texts: list[str], with_reason: bool | None = None, explain: bool = False) -> list[dict]:
        texts = [validate(t, "text", self.meta.get("expected_format") or "One command") for t in texts]
        if len(texts) > int(self.meta.get("max_batch", 50)):
            raise InputError(f"At most {self.meta.get('max_batch', 50)} commands per call for this specialist.")
        torch = self._torch
        out = []
        with self._lock:
            for t in texts:
                t0 = time.perf_counter()
                enc = self.tok(self._prompt(t), return_tensors="pt")
                with torch.no_grad():
                    g = self.model.generate(**enc, max_new_tokens=int(self.meta.get("max_new_tokens", 96)),
                                            do_sample=False, output_scores=True, return_dict_in_generate=True,
                                            pad_token_id=self.tok.pad_token_id)
                new = g.sequences[0, enc.input_ids.shape[1]:]
                lp = self.model.compute_transition_scores(g.sequences, g.scores, normalize_logits=True)[0]
                conf = float(torch.exp(lp[: len(new)].mean())) if len(new) else 0.0
                raw = self.tok.decode(new, skip_special_tokens=True)
                parsed = parse_json(raw)
                slots = (parsed or {}).get("slots") or {}
                out.append({
                    "label": str((parsed or {}).get("intent", "unparsed")), "confidence": round(conf, 4),
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "escalated": False,
                    "answered_by": self.meta.get("model_name", "LoRA model"),
                    "output": parsed, "raw_output": None if parsed else raw,
                    "reason": ("Slots: " + "; ".join(f"{k} = {v}" for k, v in slots.items())) if slots else "No slots",
                })
        return out
