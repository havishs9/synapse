"""Rung G (spec file 03): a LoRA-fine-tuned small LLM, built outside the agent tournament for one task where the
output is structured text, not a label: voice-assistant command -> {"intent", "slots"} JSON (Amazon MASSIVE en-US,
CC-BY-4.0). Fine-tuned on Nebius Token Factory (managed GPUs), adapter downloaded and served on our CPU endpoint.

  .venv/bin/python scripts/build_lora_g.py prep               # data, splits, sealed sample -> runs/<run>/
  .venv/bin/python scripts/build_lora_g.py launch [model ...]  # upload files, start the fine-tuning job(s)
  .venv/bin/python scripts/build_lora_g.py status              # job state and events
  .venv/bin/python scripts/build_lora_g.py download            # latest checkpoint of each finished job
Every number shown anywhere comes from the files this writes in runs/<run>/.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402

RAW = ROOT / "data" / "raw" / "massive" / "1.1" / "data" / "en-US.jsonl"
RUN_ID = "g-massive-a"
SYSTEM = ("Parse the voice-assistant command into JSON: {\"intent\": <intent>, \"slots\": {<slot type>: <exact words "
          "from the command>}}. Use only the intent and slot names of this assistant. No other text.")
# Attempt 1 (packing on, lr 2e-4) diverged: packing turned 11k short examples into 18 steps of 16 x 8,192 tokens,
# warmup rounded to 0 steps, final train loss 6.0 (0.6B) / 6.9 (1.7B), output was noise. Attempt 2: one example
# per sequence (~1,430 steps), longer warmup, two learning rates.
HP = {"n_epochs": 2, "batch_size": 16, "learning_rate": 1e-4, "warmup_ratio": 0.05, "packing": False, "lora": True,
      "lora_r": 16, "lora_alpha": 32, "lora_dropout": 0.05}
SEALED_SAMPLE = 300


def run_dir() -> Path:
    d = Path(config.env("RUNS_DIR", str(ROOT / "runs"))) / RUN_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def target(annot: str) -> dict:
    """'wake me up at [time : nine am] on [date : friday]' -> {"time": "nine am", "date": "friday"}; a slot type
    that occurs twice keeps both values as a list."""
    slots: dict = {}
    for k, v in re.findall(r"\[(\w+) : ([^\]]+)\]", annot):
        v = v.strip()
        slots[k] = [*slots[k], v] if isinstance(slots.get(k), list) else [slots[k], v] if k in slots else v
    return slots


def answer(r: dict) -> str:
    return json.dumps({"intent": r["intent"], "slots": target(r["annot_utt"])}, ensure_ascii=False)


def chat(r: dict, with_answer: bool = True) -> dict:
    m = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": r["utt"]}]
    return {"messages": m + ([{"role": "assistant", "content": answer(r)}] if with_answer else [])}


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower()).strip()


def prep() -> None:
    d = run_dir()
    rows = [json.loads(l) for l in RAW.open()]
    part = {p: [r for r in rows if r["partition"] == p] for p in ("train", "dev", "test")}
    held = {norm(r["utt"]) for r in part["dev"] + part["test"]}
    seen, train = set(), []
    for r in part["train"]:
        k = norm(r["utt"])
        if k not in held and k not in seen:
            seen.add(k)
            train.append(r)
    sealed = part["test"]
    rng = random.Random(42)
    sample = sorted(rng.sample(range(len(sealed)), SEALED_SAMPLE))
    (d / "sealed").mkdir(exist_ok=True)
    for name, rs in (("train.jsonl", train), ("val.jsonl", part["dev"])):
        (d / name).write_text("".join(json.dumps(chat(r), ensure_ascii=False) + "\n" for r in rs))
    (d / "sealed" / "test.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in sealed))
    (d / "sealed" / "sample_idx.json").write_text(json.dumps(sample))
    intents = sorted({r["intent"] for r in train})
    slot_types = sorted({k for r in train for k in target(r["annot_utt"])})
    manifest = {
        "run_id": RUN_ID, "task": "Voice command parser (intent + slots as JSON)", "rung": "G",
        "dataset": "Amazon MASSIVE 1.1, en-US", "license": "CC-BY-4.0",
        "url": "https://amazon-massive-nlu-dataset.s3.amazonaws.com/amazon-massive-dataset-1.1.tar.gz",
        "citation": "FitzGerald et al. MASSIVE: A 1M-Example Multilingual Natural Language Understanding Dataset "
                    "with 51 Typologically-Diverse Languages. 2022. https://arxiv.org/abs/2204.08582",
        "splits": {"train": len(train), "val": len(part["dev"]), "sealed": len(sealed),
                   "sealed_sample": SEALED_SAMPLE,
                   "train_removed_overlap_or_duplicate": len(part["train"]) - len(train)},
        "split_rule": "MASSIVE's own train/dev/test partitions; training commands that also occur in dev or test "
                      "(case- and space-insensitive) or twice in train are removed",
        "intents": intents, "slot_types": slot_types, "system_prompt": SYSTEM,
        "sha256": {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in ("train.jsonl", "val.jsonl")},
        "created": time.time(),
    }
    (d / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest["splits"]), f"{len(intents)} intents, {len(slot_types)} slot types ->", d)


def api(method: str, path: str, **kw):
    url = config.env("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/").rstrip("/") + path
    r = requests.request(method, url, headers={"Authorization": f"Bearer {config.env('NEBIUS_API_KEY')}"},
                         timeout=300, **kw)
    if r.status_code >= 400:
        raise SystemExit(f"{method} {path}: {r.status_code} {r.text[:500]}")
    return r


def upload(p: Path) -> str:
    with p.open("rb") as f:
        return api("POST", "/files", files={"file": (p.name, f)}, data={"purpose": "fine-tune"}).json()["id"]


def launch(specs: list[str]) -> None:
    """specs: '<model>' or '<model>@<learning rate>'; each job is recorded under that string."""
    d = run_dir()
    jobs_p = d / "ft_jobs.json"
    jobs = json.loads(jobs_p.read_text()) if jobs_p.exists() else {}
    tr, va = upload(d / "train.jsonl"), upload(d / "val.jsonl")
    for spec in specs:
        m, _, lr = spec.partition("@")
        hp = {**HP, **({"learning_rate": float(lr)} if lr else {})}
        body = {"model": m, "training_file": tr, "validation_file": va, "hyperparameters": hp, "seed": 42,
                "suffix": f"synapse-{RUN_ID}"}
        j = api("POST", "/fine_tuning/jobs", json=body).json()
        if spec in jobs:
            jobs.setdefault("_superseded", []).append({spec: jobs.pop(spec)})
        jobs[spec] = {"job_id": j["id"], "status": j.get("status"), "request": body, "created": time.time()}
        print(spec, "->", j["id"], j.get("status"))
    jobs_p.write_text(json.dumps(jobs, indent=2))


def status() -> None:
    d = run_dir()
    jobs = json.loads((d / "ft_jobs.json").read_text())
    for m, j in jobs.items():
        if m.startswith("_"):
            continue
        info = api("GET", f"/fine_tuning/jobs/{j['job_id']}").json()
        ev = api("GET", f"/fine_tuning/jobs/{j['job_id']}/events").json().get("data", [])
        j.update(status=info.get("status"), info=info, events=ev)
        last = ev[0] if ev else {}
        print(f"{m}: {info.get('status')} | trained_tokens={info.get('trained_tokens')} | "
              f"{last.get('message', '')[:160]}")
    (d / "ft_jobs.json").write_text(json.dumps(jobs, indent=2))


def download() -> None:
    d = run_dir()
    jobs = json.loads((d / "ft_jobs.json").read_text())
    for m, j in jobs.items():
        if m.startswith("_"):
            continue
        cps = api("GET", f"/fine_tuning/jobs/{j['job_id']}/checkpoints").json().get("data", [])
        if not cps:
            print(m, "no checkpoints yet")
            continue
        cp = max(cps, key=lambda c: c.get("step_number", c.get("created_at", 0)))
        out = d / "adapters" / m.split("/")[-1].replace("@", "_lr")
        out.mkdir(parents=True, exist_ok=True)
        for fid in cp.get("result_files", []):
            meta = api("GET", f"/files/{fid}").json()
            name = Path(meta.get("filename", fid)).name
            (out / name).write_bytes(api("GET", f"/files/{fid}/content").content)
            print(m, "->", out / name, meta.get("bytes"))
        j["checkpoint"] = cp
    (d / "ft_jobs.json").write_text(json.dumps(jobs, indent=2))


if __name__ == "__main__":
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else "status"), sys.argv[2:]
    {"prep": lambda: prep(), "launch": lambda: launch(args or ["Qwen/Qwen3-0.6B", "Qwen/Qwen3-1.7B"]),
     "status": lambda: status(), "download": lambda: download()}[cmd]()
