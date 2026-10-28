"""Fetch contract awards (description, PSC, NAICS, recipient) from the public USAspending search API.

Pulls up to PER_MONTH awards signed in each month of FY2025. Filtering on date_signed keeps months
disjoint (an action_date window returns the same long-running awards every month). Rows are deduped
on generated_internal_id, and re-running resumes: awards already in the file are skipped.
Writes data/raw/usaspending/awards.jsonl. No auth needed.
"""
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
FIELDS = ["Award ID", "Recipient Name", "Description", "PSC", "NAICS", "Award Amount", "Awarding Agency"]
PER_MONTH = int(sys.argv[1]) if len(sys.argv) > 1 else 3500
out = Path(os.environ.get("DATA_DIR", "./data")) / "raw" / "usaspending" / "awards.jsonl"
out.parent.mkdir(parents=True, exist_ok=True)


def months(fy_start=date(2024, 10, 1)):
    """Yield (first_day, last_day) ISO strings for the 12 months of the fiscal year."""
    y, m = fy_start.year, fy_start.month
    for _ in range(12):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield date(y, m, 1).isoformat(), (date(ny, nm, 1) - timedelta(days=1)).isoformat()
        y, m = ny, nm


def post(client, body):
    for attempt in range(8):
        try:
            r = client.post(URL, json=body, timeout=90)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            wait = min(2 ** attempt, 60)
            print(f"  retry {attempt + 1} in {wait}s: {type(e).__name__}", file=sys.stderr, flush=True)
            time.sleep(wait)
    raise RuntimeError("USAspending API kept failing; re-run to resume")


seen, per_month = set(), {}
if out.exists():
    for line in out.open():
        row = json.loads(line)
        seen.add(row["generated_internal_id"])
        per_month[row["_month"]] = per_month.get(row["_month"], 0) + 1

with httpx.Client() as client, out.open("a") as f:
    for start, end in months():
        got, page = per_month.get(start, 0), 1
        while got < PER_MONTH:
            body = {"filters": {"award_type_codes": ["A", "B", "C", "D"],
                                "time_period": [{"start_date": start, "end_date": end, "date_type": "date_signed"}]},
                    "fields": FIELDS, "sort": "Award ID", "order": "desc", "limit": 100, "page": page}
            data = post(client, body)
            for row in data["results"]:
                if row["generated_internal_id"] not in seen:
                    seen.add(row["generated_internal_id"])
                    f.write(json.dumps({**row, "_month": start}) + "\n")
                    got += 1
            f.flush()
            if not data["page_metadata"].get("hasNext"):
                break
            page += 1
            time.sleep(0.3)  # be polite; the API drops connections under sustained load
        print(f"{start}..{end}: {got} awards (total {len(seen)})", flush=True)
print(f"{len(seen)} unique awards -> {out}")
