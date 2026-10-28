"""make demo-data: download and prepare the showcase datasets into DATA_DIR. Skips steps already done.

Task 1: USAspending FY2025 contract awards (public API) + PSC manual workbook -> config/psc_categories.yaml
Task 2: LogHub HDFS_v1 (Zenodo) -> one window per block (data/prepared/hdfs_windows.jsonl)
Task 3: Banking77 CSVs (skip with --no-banking77). Licenses are recorded in config/datasets.yaml.
"""
from __future__ import annotations

import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import config  # noqa: E402

D = config.data_dir()
PSC_URL = "https://www.acquisition.gov/sites/default/files/manual/PSC%20April%202025.xlsx"
HDFS_URL = "https://zenodo.org/records/8196385/files/HDFS_v1.zip?download=1"
B77 = "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/{}.csv"


def fetch(url: str, dest: Path):
    if dest.exists():
        print(f"have {dest.relative_to(ROOT) if dest.is_relative_to(ROOT) else dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)


def main(banking77: bool = "--no-banking77" not in sys.argv):
    py = sys.executable
    if not (D / "raw/usaspending/awards.jsonl").exists() or sum(1 for _ in (D / "raw/usaspending/awards.jsonl").open()) < 42000:
        subprocess.run([py, str(ROOT / "scripts/data/fetch_usaspending.py"), "3500"], check=True, cwd=ROOT)
    fetch(PSC_URL, D / "raw/psc/PSC_April_2025.xlsx")
    if not (ROOT / "config/psc_categories.yaml").exists():
        subprocess.run([py, str(ROOT / "scripts/data/build_psc_categories.py")], check=True, cwd=ROOT)
    hdfs = D / "raw/hdfs_v1"
    fetch(HDFS_URL, hdfs / "HDFS_v1.zip")
    if not (hdfs / "HDFS.log").exists():
        with zipfile.ZipFile(hdfs / "HDFS_v1.zip") as z:
            z.extractall(hdfs)
    if not (D / "prepared/hdfs_windows.jsonl").exists():
        from backend.features.logs import build_hdfs_windows
        print(build_hdfs_windows(hdfs, D / "prepared/hdfs_windows.jsonl", n_blocks=15000))
    if banking77:
        for split in ("train", "test"):
            fetch(B77.format(split), D / f"raw/banking77/{split}.csv")
    print("demo data ready")


if __name__ == "__main__":
    main()
