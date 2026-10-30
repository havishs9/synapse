"""Sealed-test evaluation for rung G (scripts/build_lora_g.py): the same 300 sealed commands for every model.

  .venv/bin/python scripts/eval_lora_g.py baseline            # Nemotron Ultra zero-shot (intent and slot names given)
  .venv/bin/python scripts/eval_lora_g.py lora Qwen3-0.6B     # the downloaded adapter on its local base model
  .venv/bin/python scripts/eval_lora_g.py base Qwen3-0.6B     # the same base model without the adapter
Writes runs/g-massive-a/eval_<name>.json (metrics) and preds_<name>.jsonl (every output). Only this script and
the Evaluator read the sealed directory.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "scripts"))
from build_lora_g import SYSTEM, run_dir, target  # noqa: E402


def sealed_sample() -> list[dict]:
    d = run_dir() / "sealed"
    rows = [json.loads(l) for l in (d / "test.jsonl").open()]
    return [rows[i] for i in json.loads((d / "sample_idx.json").read_text())]


def parse(text: str) -> dict | None:
    t = text.strip()
    if "</think>" in t:
        t = t.split("</think>", 1)[1].strip()
    t = t.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        out = json.loads(t[t.index("{"): t.rindex("}") + 1])
        return out if isinstance(out, dict) else None
    except ValueError:
        return None


def pairs(slots) -> set[tuple[str, str]]:
    out = set()
    for k, v in (slots or {}).items() if isinstance(slots, dict) else []:
        for x in v if isinstance(v, list) else [v]:
            out.add((str(k).strip().lower(), " ".join(str(x).lower().split())))
    return out


def score(rows: list[dict], outputs: list[str]) -> dict:
    n, valid, intent_ok, exact, tp, fp, fn = len(rows), 0, 0, 0, 0, 0, 0
    for r, o in zip(rows, outputs):
        gold_slots = pairs(target(r["annot_utt"]))
        p = parse(o)
        pred_slots = pairs(p.get("slots")) if p else set()
        valid += p is not None
        i_ok = bool(p) and str(p.get("intent", "")).strip() == r["intent"]
        intent_ok += i_ok
        exact += i_ok and pred_slots == gold_slots
        tp, fp, fn = tp + len(pred_slots & gold_slots), fp + len(pred_slots - gold_slots), fn + len(gold_slots - pred_slots)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"n": n, "exact_match": exact / n, "intent_accuracy": intent_ok / n,
            "slot_precision": prec, "slot_recall": rec, "slot_f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
            "valid_json": valid / n}


def write(name: str, rows: list[dict], outputs: list[str], extra: dict) -> None:
    d = run_dir()
    m = {"model": name, "metrics": score(rows, outputs), **extra, "sealed_sample": len(rows), "created": time.time()}
    (d / f"eval_{name}.json").write_text(json.dumps(m, indent=2))
    with (d / f"preds_{name}.jsonl").open("w") as f:
        for r, o in zip(rows, outputs):
            f.write(json.dumps({"id": r["id"], "utt": r["utt"], "gold": {"intent": r["intent"], "slots": target(r["annot_utt"])},
                                "output": o}, ensure_ascii=False) + "\n")
    print(json.dumps(m["metrics"]), {k: v for k, v in extra.items() if k != "settings"})


def baseline() -> None:
    from backend.llm_client import LLMClient
    man = json.loads((run_dir() / "dataset_manifest.json").read_text())
    rows = sealed_sample()
    sys_prompt = (SYSTEM + "\n\nIntents: " + ", ".join(man["intents"]) + "\n\nSlot types: " + ", ".join(man["slot_types"])
                  + "\n\nOmit slots that aren't in the command; slot values are the exact words from the command.")
    llm = LLMClient(run_dir=run_dir(), budget_usd=float("inf"))

    def one(r):
        res = llm.chat("main_chat_planner_teacher_baseline", [{"role": "system", "content": sys_prompt},
                                                               {"role": "user", "content": r["utt"]}],
                       agent="Evaluator", purpose="g_baseline", max_tokens=300, temperature=0.0, thinking=False,
                       response_format={"type": "json_object"})
        return res
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, rows))
    lat = [r.latency_ms for r in res]
    write("ultra_zero_shot", rows, [r.content for r in res], {
        "display_name": "Nemotron Ultra, zero-shot (intent and slot names in the prompt)",
        "list_cost_usd": sum(r.list_cost_usd for r in res),
        "cost_per_1m_usd": sum(r.list_cost_usd for r in res) / len(res) * 1e6,
        "p50_ms": statistics.median(lat), "latency_note": "API round trip from the laptop"})


def local(name: str, with_adapter: bool, device: str = "mps", batch: int = 16) -> None:
    """name: the base model folder ('Qwen3-0.6B') or an adapter folder ('Qwen3-0.6B_lr1e-4')."""
    base = name.split("_lr")[0]
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    bdir = ROOT / "data" / "models" / base
    tok = AutoTokenizer.from_pretrained(bdir)
    tok.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(bdir, dtype=torch.bfloat16 if device == "mps" else torch.float32)
    if with_adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(adapter_dir(name)))
        model = model.merge_and_unload()
    model.to(device).eval()
    rows = sealed_sample()
    prompts = [tok.apply_chat_template([{"role": "system", "content": SYSTEM}, {"role": "user", "content": r["utt"]}],
                                       tokenize=False, add_generation_prompt=True, enable_thinking=False) for r in rows]
    outs, t0 = [], time.time()
    for i in range(0, len(prompts), batch):
        enc = tok(prompts[i:i + batch], return_tensors="pt", padding=True).to(device)
        with torch.no_grad():
            g = model.generate(**enc, max_new_tokens=96, do_sample=False, pad_token_id=tok.pad_token_id)
        outs += tok.batch_decode(g[:, enc.input_ids.shape[1]:], skip_special_tokens=True)
        print(f"{i + len(enc.input_ids)}/{len(rows)}", flush=True)
    out_name = f"{'lora' if with_adapter else 'base'}_{name}"
    write(out_name, rows, outs, {"display_name": f"{name}{' + LoRA (Token Factory fine-tune)' if with_adapter else ', no fine-tune'}",
                             "eval_device": device, "eval_seconds": time.time() - t0,
                             "latency_note": "batched evaluation on the laptop; serving latency is measured on the endpoint"})


def adapter_dir(base: str) -> Path:
    d = run_dir() / "adapters" / base
    cfg = next(d.rglob("adapter_config.json"), None)
    if cfg is None:
        raise SystemExit(f"no adapter_config.json under {d}")
    return cfg.parent


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "baseline":
        baseline()
    else:
        local(sys.argv[2], with_adapter=cmd == "lora", device=sys.argv[3] if len(sys.argv) > 3 else "mps")
