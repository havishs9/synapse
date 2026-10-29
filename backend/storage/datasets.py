"""Registry datasets in Object Storage, for build workers that don't have the laptop's data/ folder.

`make upload-datasets` copies the files below from DATA_DIR to the private bucket under datasets/ (raw HDFS log
lines included: the bucket is private, the team rule is only about the repo). A worker calls `ensure(key)`
before its build and downloads whatever is missing.
"""
from __future__ import annotations

from backend import config
from backend.storage import objects

PREFIX = "datasets"
FILES = {   # dataset_key (config/datasets.yaml) -> paths under DATA_DIR that its loader and trainer read
    "usaspending_contracts": ["raw/usaspending/awards.jsonl"],
    "loghub_hdfs_v1": ["prepared/hdfs_windows.jsonl", "prepared/hdfs_windows_stats.json",
                       "raw/hdfs_v1/preprocessed/HDFS.log_templates.csv"],
    "banking77": ["raw/banking77/train.csv", "raw/banking77/test.csv"],
}


def upload(keys: list[str] | None = None) -> list[str]:
    done = []
    for key in keys or list(FILES):
        for rel in FILES[key]:
            src = config.data_dir() / rel
            if not src.is_file():
                raise FileNotFoundError(f"{src} is missing; run `make demo-data` first")
            objects.put_file(src, f"{PREFIX}/{rel}")
            done.append(rel)
    return done


def ensure(key: str | None) -> list[str]:
    """Download the files of dataset `key` that aren't in DATA_DIR yet; returns the ones fetched."""
    fetched = []
    for rel in FILES.get(key or "", []):
        dest = config.data_dir() / rel
        if dest.is_file():
            continue
        if not objects.enabled():
            raise objects.StorageError(f"{rel} isn't in DATA_DIR and Object Storage isn't set up")
        tmp = dest.with_name(dest.name + ".part")
        objects.get_file(f"{PREFIX}/{rel}", tmp)
        tmp.replace(dest)
        fetched.append(rel)
    return fetched
