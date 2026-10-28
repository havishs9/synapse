"""Log windowing, template parsing and window features (task 2, spec 03 section 1.4).

Log lines are never classified one at a time: lines are grouped into windows by block ID, and each
window is one input. Templates come from the Loghub HDFS template file, compiled to regexes.
"""
from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BLOCK_RE = re.compile(r"blk_-?\d+")
# "081109 203518 143 INFO dfs.DataNode$DataXceiver: Receiving block ..."
LINE_RE = re.compile(r"^(?P<date>\d{6}) (?P<time>\d{6}) (?P<pid>\d+) (?P<level>[A-Z]+) (?P<component>[^:]+): (?P<content>.*)$")
LEVELS = ("INFO", "WARN", "ERROR", "FATAL")


class TemplateParser:
    """Regex parser built from '[*]' templates (Loghub format). Unknown lines map to 'E0'."""

    def __init__(self, templates: list[tuple[str, str]]):
        self.templates = templates
        self.compiled = [(eid, re.compile(self._to_regex(t))) for eid, t in templates]

    @staticmethod
    def _to_regex(template: str) -> str:
        parts = [re.escape(p) for p in template.split("[*]")]
        return ".*?".join(parts)

    @classmethod
    def from_csv(cls, path: Path) -> "TemplateParser":
        with open(path) as f:
            return cls([(r["EventId"], r["EventTemplate"]) for r in csv.DictReader(f)])

    def event_id(self, content: str) -> str:
        for eid, rx in self.compiled:
            if rx.search(content):
                return eid
        return "E0"

    @property
    def event_ids(self) -> list[str]:
        return [eid for eid, _ in self.templates] + ["E0"]


def parse_line(line: str) -> dict | None:
    m = LINE_RE.match(line.strip())
    return m.groupdict() if m else None


def window_features(window: str, parser: TemplateParser) -> dict[str, float]:
    """Engineered features for candidate E: template counts, level counts, duration, sequence stats."""
    counts: Counter = Counter()
    levels: Counter = Counter()
    times: list[datetime] = []
    seq: list[str] = []
    n_unparsed = 0
    for line in window.splitlines():
        if not line.strip():
            continue
        p = parse_line(line)
        if p is None:
            n_unparsed += 1
            eid = parser.event_id(line)
        else:
            levels[p["level"]] += 1
            eid = parser.event_id(p["content"])
            try:
                times.append(datetime.strptime(p["date"] + p["time"], "%y%m%d%H%M%S"))
            except ValueError:
                pass
        counts[eid] += 1
        seq.append(eid)
    n = len(seq)
    feats = {f"count_{eid}": float(counts.get(eid, 0)) for eid in parser.event_ids}
    feats.update({f"level_{lv}": float(levels.get(lv, 0)) for lv in LEVELS})
    duration = (max(times) - min(times)).total_seconds() if len(times) > 1 else 0.0
    transitions = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    longest = run = 1 if seq else 0
    for a, b in zip(seq, seq[1:]):
        run = run + 1 if a == b else 1
        longest = max(longest, run)
    feats.update({
        "n_lines": float(n), "n_unique_events": float(len(counts)), "n_unparsed": float(n_unparsed),
        "duration_s": duration, "lines_per_s": n / duration if duration > 0 else float(n),
        "transitions": float(transitions), "longest_run": float(longest),
        "frac_unknown": counts.get("E0", 0) / n if n else 0.0,
        "warn_or_worse": float(levels.get("WARN", 0) + levels.get("ERROR", 0) + levels.get("FATAL", 0)),
    })
    return feats


def feature_reason(feats: dict[str, float], importances: dict[str, float], parser: TemplateParser,
                   baseline: dict[str, float], top: int = 3) -> str:
    """Plain-English reason from the most important features that deviate from the normal-window average."""
    names = dict(parser.templates)
    scored = []
    for k, imp in importances.items():
        dev = feats.get(k, 0.0) - baseline.get(k, 0.0)
        if imp > 0 and abs(dev) > 1e-9:
            scored.append((imp * abs(dev) / (abs(baseline.get(k, 0.0)) + 1.0), k, dev))
    parts = []
    for _, k, dev in sorted(scored, reverse=True)[:top]:
        val = feats.get(k, 0.0)
        if k.startswith("count_E"):
            eid = k[len("count_"):]
            label = names.get(eid, "unrecognized line")
            label = label.replace("[*]", "…").strip(" …")
            parts.append(f"{int(val)}× \"{label}\" (normal windows average {baseline.get(k, 0.0):.1f})")
        else:
            parts.append(f"{k.replace('_', ' ')} = {val:.1f} (normal average {baseline.get(k, 0.0):.1f})")
    return "; ".join(parts) if parts else "No feature stands out from normal windows."


def build_hdfs_windows(raw_dir: Path, out_path: Path, n_blocks: int = 15000, seed: int = 7,
                       max_lines: int = 300) -> dict:
    """Sample blocks at the natural anomaly ratio and group their log lines into one window per block."""
    labels: dict[str, str] = {}
    with open(raw_dir / "preprocessed" / "anomaly_label.csv") as f:
        for r in csv.DictReader(f):
            labels[r["BlockId"]] = "anomaly" if r["Label"] == "Anomaly" else "normal"
    rng = random.Random(seed)
    by_label = defaultdict(list)
    for b, lab in labels.items():
        by_label[lab].append(b)
    total = len(labels)
    chosen: set[str] = set()
    for lab, blocks in sorted(by_label.items()):
        k = round(n_blocks * len(blocks) / total)
        chosen.update(rng.sample(sorted(blocks), k))
    lines: dict[str, list[str]] = defaultdict(list)
    with open(raw_dir / "HDFS.log", errors="replace") as f:
        for line in f:
            for b in set(BLOCK_RE.findall(line)):
                if b in chosen and len(lines[b]) < max_lines:
                    lines[b].append(line.rstrip("\n"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_written = Counter()
    with out_path.open("w") as f:
        for b in sorted(chosen):
            if not lines.get(b):
                continue
            f.write(json.dumps({"id": b, "text": "\n".join(lines[b]), "label": labels[b]}) + "\n")
            n_written[labels[b]] += 1
    stats = {"blocks_total": total, "blocks_sampled": sum(n_written.values()), "label_counts": dict(n_written),
             "anomaly_rate_source": len(by_label["anomaly"]) / total, "seed": seed, "max_lines": max_lines}
    (out_path.parent / (out_path.stem + "_stats.json")).write_text(json.dumps(stats, indent=2))
    return stats
