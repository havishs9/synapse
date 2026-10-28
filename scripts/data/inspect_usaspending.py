"""Phase 0: PSC-mapping coverage, category counts and description boilerplate on the fetched awards.

Writes runs/verify/usaspending_inspection.json.
"""
import json
import os
import re
from collections import Counter
from pathlib import Path

import yaml

data_dir = Path(os.environ.get("DATA_DIR", "./data"))
rows = [json.loads(l) for l in (data_dir / "raw/usaspending/awards.jsonl").open()]
psc = yaml.safe_load(open("config/psc_categories.yaml"))


def category(code):
    if not code:
        return None
    return (psc["psc_to_category"].get(code) or psc["prefix3_to_category"].get(code[:3])
            or psc["prefix2_to_category"].get(code[:2]))


codes = [(r.get("PSC") or {}).get("code") for r in rows]
cats = [category(c) for c in codes]
descs = [(r.get("Description") or "").strip() for r in rows]
ids = {r["generated_internal_id"] for r in rows}
boiler = Counter()
for d in descs:
    boiler.update("<digits>!" if t[0].isdigit() else t for t in re.findall(r"IGF::\w+::IGF|^\d{6,}!", d))
report = {
    "rows": len(rows),
    "unique_awards": len(ids),
    "missing_psc": sum(c is None for c in codes),
    "unmapped_psc": sum(1 for c, k in zip(codes, cats) if c and k is None),
    "unmapped_examples": Counter(c for c, k in zip(codes, cats) if c and k is None).most_common(10),
    "empty_description": sum(not d for d in descs),
    "duplicate_descriptions": len(descs) - len(set(descs)),
    "median_description_chars": sorted(map(len, descs))[len(descs) // 2],
    "boilerplate_tokens": dict(boiler),
    "category_counts": Counter(k for k in cats if k).most_common(),
}
out = Path(os.environ.get("RUNS_DIR", "./runs")) / "verify" / "usaspending_inspection.json"
out.write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
