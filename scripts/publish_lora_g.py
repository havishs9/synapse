"""Bundle and publish the rung-G specialist (scripts/build_lora_g.py, scripts/eval_lora_g.py).

  .venv/bin/python scripts/publish_lora_g.py bundle Qwen3-0.6B   # merge the adapter -> data/bundles/<sid>/v1
  .venv/bin/python scripts/publish_lora_g.py publish             # upload to Object Storage + register in Postgres
The bundle (~1.2 GB) is too large for git: it lives in Object Storage only. The run's metric files are small and
are copied to artifacts/demo/runs/<run> for the repo.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_lora_g import RUN_ID, SYSTEM, run_dir  # noqa: E402

SID = "voice-command-parser"
OUT = ROOT / "data" / "bundles" / SID / "v1"


def bundle(name: str) -> None:
    """name: the adapter folder, e.g. Qwen3-0.6B_lr1e-4."""
    base = name.split("_lr")[0]
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    sys.path.insert(0, str(ROOT / "scripts"))
    from eval_lora_g import adapter_dir
    d = run_dir()
    ev = json.loads((d / f"eval_lora_{name}.json").read_text())
    ultra = json.loads((d / "eval_ultra_zero_shot.json").read_text())
    man = json.loads((d / "dataset_manifest.json").read_text())
    bdir = ROOT / "data" / "models" / base
    model = AutoModelForCausalLM.from_pretrained(bdir, dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(model, str(adapter_dir(name))).merge_and_unload()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "model").mkdir(parents=True)
    model.save_pretrained(OUT / "model", safe_serialization=True)
    AutoTokenizer.from_pretrained(bdir).save_pretrained(OUT / "model")
    meta = {
        "kind": "generative", "task_name": "Voice Command Parser", "task_id": "voice_commands", "labels": man["intents"],
        "slot_types": man["slot_types"], "input_type": "text", "positive": None, "threshold": None,
        "calibrator_T": None, "needs_reason": True, "candidate": f"G-01 ({base} + LoRA)", "family": "G",
        "uses_cloud": False, "run_id": RUN_ID, "model_name": f"{base} + LoRA", "system_prompt": SYSTEM,
        "example_input": "wake me up at seven thirty tomorrow and turn off the kitchen lights",
        "expected_format": "One voice-assistant command",
        "max_new_tokens": 96, "max_batch": 50,
        "sealed": ev["metrics"], "baseline": {"model": ultra["display_name"], **ultra["metrics"],
                                              "cost_per_1m_usd": ultra["cost_per_1m_usd"], "p50_ms": ultra["p50_ms"]},
        "fine_tune": json.loads((d / "ft_jobs.json").read_text()).get("Qwen/" + name.replace("_lr", "@"), {}).get("request", {}),
    }
    (OUT / "bundle.json").write_text(json.dumps(meta, indent=2))
    print("bundle ->", OUT, sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) // 2**20, "MiB")


def publish() -> None:
    from backend.schemas import Versions, VersionRecord
    from backend.storage import db, objects
    from backend.versions import registry
    if not (db.enabled() and objects.enabled()):
        raise SystemExit("needs SUPABASE_DB_URL and Object Storage settings in .env")
    meta = json.loads((OUT / "bundle.json").read_text())
    m = meta["sealed"]
    prefix = objects.specialist_prefix(None, SID, 1)
    objects.upload_dir(OUT, prefix)
    v = registry.load(SID) if registry.exists(SID) else Versions(
        specialist_id=SID, display_name="Voice Command Parser", monogram="VC", color="#7C3AED",
        task_id="voice_commands", api_route=f"/v1/specialists/{SID}/predict")
    v.versions = [r for r in v.versions if r.version != 1] + [VersionRecord(
        version=1, run_id=RUN_ID, candidate=meta["candidate"], live=True, gate_result="deployed",
        reason=f"first version; sealed exact match {m['exact_match']:.3f} on {m['n']} commands "
               f"(Nemotron Ultra zero-shot {meta['baseline']['exact_match']:.3f} on the same commands)",
        sealed_metrics={"primary": m["exact_match"], "primary_metric": "exact_match", **m},
        artifact_uri=objects.uri(prefix), artifact_files=objects.file_hashes(OUT), created=time.time())]
    registry.save(v)
    keep = [p for p in run_dir().iterdir() if p.is_file() and p.suffix in (".json", ".jsonl", ".md")
            and p.name not in ("train.jsonl", "val.jsonl")]
    dest = ROOT / "artifacts" / "demo" / "runs" / RUN_ID
    dest.mkdir(parents=True, exist_ok=True)
    for p in keep:
        shutil.copy2(p, dest / p.name)
    print(f"{SID} v1 live at {objects.uri(prefix)}; run files -> {dest}")


if __name__ == "__main__":
    {"bundle": lambda: bundle(sys.argv[2]), "publish": publish}[sys.argv[1]]()
