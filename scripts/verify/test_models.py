"""Phase 0: one plain, one tool-calling and one JSON-schema call per chat model, plus one embedding call.

Writes runs/verify/model_tests.json with tokens, latency and cost (prices from the verbose model listing).
"""
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env")
client = OpenAI(api_key=os.environ["NEBIUS_API_KEY"], base_url=os.environ["NEBIUS_BASE_URL"], timeout=120)
out_dir = Path(os.environ.get("RUNS_DIR", "./runs")) / "verify"
listing = {m["id"]: m for m in json.loads((out_dir / "models_list_verbose.json").read_text())["data"]}

CHAT_MODELS = [
    "nvidia/Nemotron-3-Ultra-550b-a55b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/Nemotron-3_5-Lightning",
]
EMBED_MODEL = "Qwen/Qwen3-Embedding-8B"

RECORD = "Purchase of 40 Dell Latitude laptops and docking stations for field office"
LABELS = ["IT equipment", "Office supplies", "Construction", "Medical"]
TOOLS = [{
    "type": "function",
    "function": {
        "name": "set_category",
        "description": "Record the spending category for a procurement record.",
        "parameters": {
            "type": "object",
            "properties": {"category": {"type": "string", "enum": LABELS}},
            "required": ["category"],
        },
    },
}]
SCHEMA = {
    "name": "classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": LABELS},
            "confidence": {"type": "number"},
        },
        "required": ["category", "confidence"],
        "additionalProperties": False,
    },
}


def cost(model, usage):
    p = listing[model]["pricing"]
    return usage.prompt_tokens * float(p["prompt"]) + (usage.completion_tokens or 0) * float(p["completion"])


def run(model, kind, **kw):
    t0 = time.perf_counter()
    try:
        r = client.chat.completions.create(model=model, max_tokens=1024, temperature=0, **kw)
    except Exception as e:  # record the failure, keep going
        return {"model": model, "test": kind, "ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    ms = (time.perf_counter() - t0) * 1000
    msg = r.choices[0].message
    res = {
        "model": model, "test": kind, "latency_ms": round(ms), "finish_reason": r.choices[0].finish_reason,
        "prompt_tokens": r.usage.prompt_tokens, "completion_tokens": r.usage.completion_tokens,
        "cost_usd": cost(model, r.usage), "content": (msg.content or "")[:300],
    }
    if kind == "tools":
        calls = msg.tool_calls or []
        res["tool_calls"] = [{"name": c.function.name, "arguments": c.function.arguments} for c in calls]
        res["ok"] = bool(calls) and json.loads(calls[0].function.arguments).get("category") in LABELS
    elif kind == "json_schema":
        try:
            parsed = json.loads(msg.content)
            res["ok"] = parsed.get("category") in LABELS and isinstance(parsed.get("confidence"), (int, float))
        except Exception:
            res["ok"] = False
    else:
        res["ok"] = bool(msg.content)
    return res


results = []
for m in CHAT_MODELS:
    results.append(run(m, "plain", messages=[{"role": "user", "content": "Reply with exactly: ok"}]))
    results.append(run(m, "tools", tools=TOOLS, tool_choice="auto", messages=[
        {"role": "user", "content": f"Categorize this record using the set_category tool: {RECORD}"}]))
    results.append(run(m, "json_schema", response_format={"type": "json_schema", "json_schema": SCHEMA}, messages=[
        {"role": "user", "content": f"Classify into one of {LABELS} and give a confidence 0-1. Record: {RECORD}"}]))
    for r in results[-3:]:
        print(json.dumps({k: r.get(k) for k in ("model", "test", "ok", "latency_ms", "completion_tokens", "finish_reason", "error")}))

t0 = time.perf_counter()
try:
    e = client.embeddings.create(model=EMBED_MODEL, input=[RECORD, "Box of printer paper"])
    results.append({"model": EMBED_MODEL, "test": "embeddings", "ok": len(e.data) == 2,
                    "dim": len(e.data[0].embedding), "latency_ms": round((time.perf_counter() - t0) * 1000),
                    "prompt_tokens": e.usage.prompt_tokens,
                    "cost_usd": e.usage.prompt_tokens * float(listing[EMBED_MODEL]["pricing"]["prompt"])})
except Exception as ex:
    results.append({"model": EMBED_MODEL, "test": "embeddings", "ok": False, "error": str(ex)[:300]})
print(json.dumps(results[-1]))

(out_dir / "model_tests.json").write_text(json.dumps(results, indent=2))
print(f"total cost ${sum(r.get('cost_usd', 0) for r in results):.5f}")
