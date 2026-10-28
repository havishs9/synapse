"""Sealed test set: written once by the Data agent at intake, readable only by the Evaluator.

Enforcement (spec 02 section 3, rule 1):
- `write_sealed` is write-only; it returns nothing that points at the file.
- `read_sealed` checks that its direct caller is the Evaluator module and raises otherwise.
- `load_split`, the loader every other module uses, refuses any path inside a sealed directory.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

SEALED_DIRNAME = "sealed"
EVALUATOR_MODULES = {"backend.agents.evaluator_agent"}


class SealedAccessError(PermissionError):
    pass


def _sealed_path(run_dir: Path) -> Path:
    return Path(run_dir) / SEALED_DIRNAME / "test.jsonl"


def is_sealed_path(path: Path) -> bool:
    return SEALED_DIRNAME in Path(path).resolve().parts


def write_sealed(run_dir: Path, rows: list[dict]) -> int:
    path = _sealed_path(run_dir)
    if path.exists():
        raise SealedAccessError(f"sealed test set for {run_dir.name} already exists and can't be rewritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    path.chmod(0o444)
    return len(rows)


def read_sealed(run_dir: Path) -> list[dict]:
    caller = inspect.stack()[1].frame.f_globals.get("__name__", "")
    if caller not in EVALUATOR_MODULES:
        raise SealedAccessError(f"only the Evaluator may read the sealed test set (caller: {caller})")
    return [json.loads(line) for line in _sealed_path(run_dir).open()]


def sealed_exists(run_dir: Path) -> bool:
    return _sealed_path(run_dir).exists()


def load_split(path: Path) -> list[dict]:
    """Read a train/val/holdback JSONL split. Refuses the sealed test set."""
    if is_sealed_path(path):
        raise SealedAccessError(f"{path} is inside the sealed test directory")
    return [json.loads(line) for line in Path(path).open()]


def write_split(path: Path, rows: list[dict]) -> Path:
    if is_sealed_path(path):
        raise SealedAccessError(f"{path} is inside the sealed test directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return path
