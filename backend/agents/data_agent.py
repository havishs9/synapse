"""Data agent: gather data, label, dedupe, split (sealed test at intake), rebalance train only.

Reads task_card.json (and error_patterns.json / corrections.json during repair and improve).
Writes dataset_manifest.json, dataset_stats.json, train.jsonl, val.jsonl, holdback.jsonl, and the sealed
test split through `sealed.write_sealed`. It never gets a path to the sealed split back.
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend import config
from backend.sealed import load_split, write_sealed, write_split
from backend.schemas import (DatasetManifest, DatasetStats, ErrorPatterns, SourceInfo, SplitInfo, TaskCard)

Emit = Callable[..., None]
BOILERPLATE = [re.compile(r"^\s*\d{6,}!\s*"), re.compile(r"\s*IGF::\w+::IGF\s*")]


@dataclass
class DataPaths:
    train: Path
    val: Path
    holdback: Path | None
    manifest: Path
    stats: Path


# ---- sources -----------------------------------------------------------
def psc_to_category(code: str | None) -> str | None:
    if not code:
        return None
    psc = config.psc_categories()
    return (psc["psc_to_category"].get(code) or psc["prefix3_to_category"].get(code[:3])
            or psc["prefix2_to_category"].get(code[:2]))


def clean_description(text: str) -> str:
    for rx in BOILERPLATE:
        text = rx.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_procurement() -> tuple[list[dict], dict]:
    path = config.data_dir() / "raw" / "usaspending" / "awards.jsonl"
    rows, dropped = [], Counter()
    for line in path.open():
        r = json.loads(line)
        text = clean_description(r.get("Description") or "")
        label = psc_to_category((r.get("PSC") or {}).get("code"))
        if not text:
            dropped["empty_description"] += 1
            continue
        if label is None:
            dropped["unmapped_psc"] += 1
            continue
        # Recipient name is deliberately not used (team decision; possible D&B-derived data).
        rows.append({"id": r["generated_internal_id"], "text": text, "label": label,
                     "psc": r["PSC"]["code"]})
    info = {"raw_rows": sum(dropped.values()) + len(rows), "dropped": dict(dropped)}
    return rows, info


def load_logs() -> tuple[list[dict], dict]:
    path = config.data_dir() / "prepared" / "hdfs_windows.jsonl"
    rows = [json.loads(line) for line in path.open()]
    stats_path = path.parent / "hdfs_windows_stats.json"
    info = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    return rows, info


def load_banking77() -> tuple[list[dict], dict]:
    import csv
    d = config.data_dir() / "raw" / "banking77"
    rows = []
    for split in ("train", "test"):
        with open(d / f"{split}.csv") as f:
            for i, r in enumerate(csv.DictReader(f)):
                rows.append({"id": f"{split}-{i}", "text": r["text"], "label": r["category"]})
    return rows, {"raw_rows": len(rows)}


LOADERS = {"usaspending_contracts": load_procurement, "loghub_hdfs_v1": load_logs, "banking77": load_banking77}


# ---- generic steps ------------------------------------------------------
def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def dedupe(rows: list[dict]) -> tuple[list[dict], dict]:
    """Drop exact duplicates of normalized text, keeping the majority label for each text."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[normalize(r["text"])].append(r)
    out, conflicts = [], 0
    for key, rs in groups.items():
        labels = Counter(r["label"] for r in rs)
        if len(labels) > 1:
            conflicts += 1
        top = labels.most_common(1)[0][0]
        out.append(next(r for r in rs if r["label"] == top))
    return out, {"before": len(rows), "after": len(out), "duplicate_texts_with_conflicting_labels": conflicts}


def stratified_split(rows: list[dict], fracs: dict[str, float], seed: int) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    by = defaultdict(list)
    for r in rows:
        by[r["label"]].append(r)
    out = {k: [] for k in fracs}
    names = list(fracs)
    for label in sorted(by):
        rs = by[label][:]
        rng.shuffle(rs)
        n = len(rs)
        cuts, acc = [], 0.0
        for k in names[:-1]:
            acc += fracs[k]
            cuts.append(round(n * acc))
        bounds = [0] + cuts + [n]
        for k, a, b in zip(names, bounds, bounds[1:]):
            out[k].extend(rs[a:b])
    for k in out:
        rng.shuffle(out[k])
    return out


def cap_per_class(rows: list[dict], cap: int, min_count: int, seed: int) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    by = defaultdict(list)
    for r in rows:
        by[r["label"]].append(r)
    out, dropped_classes, capped = [], {}, {}
    for label, rs in sorted(by.items()):
        if len(rs) < min_count:
            dropped_classes[label] = len(rs)
            continue
        if len(rs) > cap:
            capped[label] = len(rs)
            rs = rng.sample(rs, cap)
        out.extend(rs)
    return out, {"cap_per_class": cap, "min_count": min_count, "capped_from": capped,
                 "dropped_classes_below_min": dropped_classes}


def rebalance_train(train: list[dict], min_per_class: int, seed: int) -> tuple[list[dict], dict]:
    """Oversample (with replacement) classes below min_per_class. Applied to the training set only."""
    rng = random.Random(seed)
    by = defaultdict(list)
    for r in train:
        by[r["label"]].append(r)
    out, added = list(train), {}
    for label, rs in by.items():
        need = min_per_class - len(rs)
        if need > 0:
            extra = [dict(rng.choice(rs), id=f"{rng.choice(rs)['id']}#os{i}") for i in range(need)]
            out.extend(extra)
            added[label] = need
    rng.shuffle(out)
    return out, {"min_per_class": min_per_class, "oversampled": added}


def class_counts(rows: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(r["label"] for r in rows).items()))


def compute_stats(rows: list[dict], input_type: str) -> DatasetStats:
    counts = class_counts(rows)
    texts = [r["text"] for r in rows]
    tokens = [t for x in texts[:5000] for t in normalize(x).split()]
    vocab = len(set(tokens))
    return DatasetStats(
        rows=len(rows), label_counts=counts, n_classes=len(counts),
        imbalance_ratio=max(counts.values()) / max(min(counts.values()), 1),
        smallest_class=min(counts.values()),
        avg_input_chars=sum(map(len, texts)) / max(len(texts), 1),
        keyword_density=vocab / max(len(tokens), 1),
        structured=input_type in ("log_window", "tabular"), input_type=input_type)


def format_match(samples: list[str], rows: list[dict]) -> dict:
    """Crude format check between the user's pasted rows and the source data: length and character mix."""
    if not samples:
        return {"score": None, "explanation": "No sample inputs were provided."}

    def profile(texts):
        texts = texts[:2000]
        joined = "".join(texts) or " "
        return {"avg_len": sum(map(len, texts)) / len(texts),
                "upper": sum(c.isupper() for c in joined) / len(joined),
                "digit": sum(c.isdigit() for c in joined) / len(joined),
                "lines": sum(t.count("\n") + 1 for t in texts) / len(texts)}
    a, b = profile(samples), profile([r["text"] for r in rows])
    len_ratio = min(a["avg_len"], b["avg_len"]) / max(a["avg_len"], b["avg_len"], 1e-9)
    case_sim = 1 - min(abs(a["upper"] - b["upper"]) * 2, 1)
    digit_sim = 1 - min(abs(a["digit"] - b["digit"]) * 4, 1)
    line_sim = min(a["lines"], b["lines"]) / max(a["lines"], b["lines"], 1e-9)
    score = round(0.4 * len_ratio + 0.25 * case_sim + 0.15 * digit_sim + 0.2 * line_sim, 3)
    return {"score": score, "sample_profile": a, "source_profile": b,
            "explanation": (f"Your samples average {a['avg_len']:.0f} characters vs {b['avg_len']:.0f} in the source; "
                            f"uppercase share {a['upper']:.0%} vs {b['upper']:.0%}; lines per item "
                            f"{a['lines']:.1f} vs {b['lines']:.1f}.")}


# ---- main entry -----------------------------------------------------------
def run_data_agent(card: TaskCard, run_dir: Path, emit: Emit, *, seed: int = 13,
                   cap: int = 1500, min_count: int = 60, train_min_per_class: int = 150) -> DataPaths:
    if not card.dataset_key:
        raise ValueError("Task card has no dataset_key; user-uploaded data must be saved as a registry entry first.")
    reg = config.datasets()[card.dataset_key]
    if reg.get("license_ok") is not True:
        raise PermissionError(f"Dataset {card.dataset_key} is not license-approved in config/datasets.yaml")
    rows, load_info = LOADERS[card.dataset_key]()
    emit("Data", "data", f"Loaded {len(rows):,} labeled rows from {card.dataset_key} ({reg['license'][:60]})")

    rows, dd = dedupe(rows)
    emit("Data", "data", f"Removed {dd['before'] - dd['after']:,} duplicate texts before splitting")
    processing = {"usaspending_contracts": ["dropped empty descriptions and unmapped PSC codes",
                                            "stripped boilerplate tokens"],
                  "loghub_hdfs_v1": ["loaded prepared windows", "grouped log lines by block ID"],
                  }.get(card.dataset_key, ["merged the source's train and test files"]) + [
                  "deduplicated on normalized text before splitting"]
    if card.input_type == "log_window":
        sampling = {"note": "windows sampled at the natural anomaly ratio", **load_info}
    else:
        rows, sampling = cap_per_class(rows, cap, min_count, seed)
        if sampling["dropped_classes_below_min"]:
            emit("Data", "data", f"{len(sampling['dropped_classes_below_min'])} categories have under {min_count} "
                 "examples after dedupe and were left out")
    allowed = {lab.name for lab in card.labels}
    rows = [r for r in rows if r["label"] in allowed] if allowed else rows

    # Hold back a slice for the v1 -> v2 "user corrections" demo; it never enters train/val/test.
    parts = stratified_split(rows, {"holdback": 0.05, "rest": 0.95}, seed)
    splits = stratified_split(parts["rest"], {"train": 0.6, "val": 0.2, "test": 0.2}, seed + 1)
    write_sealed(run_dir, splits["test"])
    emit("Data", "data", f"Sealed {len(splits['test']):,} rows as the final test set; only the Evaluator can read them")

    small = [k for k, v in class_counts(splits["train"]).items() if v < train_min_per_class]
    if card.input_type == "log_window":
        train, rebalance = splits["train"], {"note": "not rebalanced; class weights used instead"}
    else:
        train, rebalance = rebalance_train(splits["train"], train_min_per_class, seed)
        if small:
            emit("Data", "data", f"{len(small)} categories have under {train_min_per_class} training examples; "
                 "oversampling them in the training set only")
    paths = DataPaths(
        train=write_split(run_dir / "train.jsonl", train),
        val=write_split(run_dir / "val.jsonl", splits["val"]),
        holdback=write_split(run_dir / "holdback.jsonl", parts["holdback"]),
        manifest=run_dir / "dataset_manifest.json", stats=run_dir / "dataset_stats.json")

    psc = config.psc_categories()
    label_mapping = ({"type": "psc_level1", "source": psc["source"],
                      "lookup_order": ["psc_to_category", "prefix3_to_category", "prefix2_to_category"],
                      "legacy_prefix_overrides": psc["legacy_prefix_overrides"]}
                     if card.dataset_key == "usaspending_contracts" else {"type": "native_labels"})
    citation = reg.get("citation", [])
    manifest = DatasetManifest(
        sources=[SourceInfo(name=card.dataset_key, url=reg["source"], license=reg["license"], license_ok=True,
                            rows_used=len(rows), citation=citation if isinstance(citation, list) else [citation])],
        label_mapping=label_mapping, format_match=format_match(card.sample_inputs, rows),
        splits={"train": SplitInfo(rows=len(train), class_counts=class_counts(train)),
                "train_before_rebalance": SplitInfo(rows=len(splits["train"]), class_counts=class_counts(splits["train"])),
                "val": SplitInfo(rows=len(splits["val"]), class_counts=class_counts(splits["val"])),
                "test": SplitInfo(rows=len(splits["test"]), class_counts=class_counts(splits["test"])),
                "holdback": SplitInfo(rows=len(parts["holdback"]), class_counts=class_counts(parts["holdback"]))},
        processing=processing,
        sampling={**sampling, "dedupe": dd, "load": load_info, "rebalance": rebalance, "seed": seed,
                  "split": "holdback 5%, then train/val/test 60/20/20 stratified"})
    manifest.write(paths.manifest)
    compute_stats(splits["train"] + splits["val"], card.input_type).write(paths.stats)
    emit("Data", "data", f"Split into {len(train):,} train / {len(splits['val']):,} validation rows",
         data_ref="dataset_manifest.json", kind="handoff")
    return paths


# ---- repair and improve ------------------------------------------------------
def add_targeted_examples(card: TaskCard, run_dir: Path, patterns: ErrorPatterns, llm, emit: Emit,
                          round_no: int, per_pattern: int = 25) -> dict:
    """Generate examples in the user's format for the confused classes; append to the training set only."""
    train = load_split(run_dir / "train.jsonl")
    samples = card.sample_inputs[:5] or [r["text"] for r in train[:5]]
    defs = {lab.name: lab.definition for lab in card.labels}
    new, held_out = [], []
    for p in patterns.patterns[:4]:
        label = p.true_label
        if not label:
            continue
        prompt = (
            f"Write {per_pattern + 5} new, realistic, varied examples of inputs for this task: {card.description}\n"
            f"Every example must belong to the category \"{label}\" ({defs.get(label, '')}).\n"
            f"They are currently confused with \"{p.predicted_label}\". Problem: {p.pattern}\n"
            f"Fix to apply: {p.suggested_data_fix}\n"
            f"Match the exact style, casing and length of these real inputs:\n" + "\n".join(f"- {s}" for s in samples) +
            '\nReturn JSON: {"examples": ["...", ...]}')
        try:
            res = llm.chat("main_chat_planner_teacher_baseline", [{"role": "user", "content": prompt}],
                           agent="Data", purpose=f"repair_synthetic_r{round_no}", max_tokens=3000,
                           temperature=0.8, thinking=False, response_format={"type": "json_object"})
            examples = [e for e in res.json().get("examples", []) if isinstance(e, str) and e.strip()]
        except Exception as exc:  # a failed generation is reported, not fatal
            emit("Data", "repair", f"Couldn't generate examples for {label}: {exc}")
            continue
        for i, text in enumerate(examples):
            row = {"id": f"syn-r{round_no}-{label[:12]}-{i}", "text": text.strip(), "label": label, "synthetic": True}
            (held_out if i < 5 else new).append(row)
    write_split(run_dir / "train.jsonl", train + new)
    prev = load_split(run_dir / "synthetic_eval.jsonl") if (run_dir / "synthetic_eval.jsonl").exists() else []
    write_split(run_dir / "synthetic_eval.jsonl", prev + held_out)
    emit("Data", "repair", f"Repair round {round_no}: added {len(new)} targeted synthetic examples to the training set "
         f"(and kept {len(held_out)} aside to score on synthetic data)")
    return {"added": len(new), "held_out_synthetic": len(held_out)}


def add_corrections(run_dir: Path, base_run_dir: Path, corrections: list[dict], emit: Emit,
                    variants: list[dict] | None = None) -> DataPaths:
    """Improve flow: copy the base run's train/val, append corrections (+ variants) to train only."""
    train = load_split(base_run_dir / "train.jsonl")
    val = load_split(base_run_dir / "val.jsonl")
    added = [{"id": f"corr-{i}", "text": c["input"], "label": c["corrected_label"], "correction": True}
             for i, c in enumerate(corrections)] + (variants or [])
    paths = DataPaths(train=write_split(run_dir / "train.jsonl", train + added),
                      val=write_split(run_dir / "val.jsonl", val), holdback=None,
                      manifest=run_dir / "dataset_manifest.json", stats=run_dir / "dataset_stats.json")
    for name in ("dataset_manifest.json", "dataset_stats.json"):
        (run_dir / name).write_text((base_run_dir / name).read_text())
    emit("Data", "data", f"Added {len(corrections)} corrections and {len(variants or [])} variants to the training set only")
    return paths
