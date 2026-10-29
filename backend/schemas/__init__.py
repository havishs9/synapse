"""Pydantic models for every JSON handoff file (spec 02 section 5)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

M = TypeVar("M", bound=BaseModel)


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(self.model_dump_json(indent=2))
        tmp.replace(path)
        return path

    @classmethod
    def read(cls: type[M], path: Path) -> M:
        return cls.model_validate(json.loads(Path(path).read_text()))


# ---- 5.1 task_card.json ------------------------------------------------
class Label(Schema):
    name: str
    definition: str = ""


class Thresholds(Schema):
    primary_min: float
    per_class_floor: Optional[float] = None   # min recall for every class (multiclass)


class WindowSpec(Schema):
    group_by: str = "block_id"
    window_minutes: Optional[int] = None


class TaskCard(Schema):
    task_id: str
    task_name: str
    description: str
    input_type: Literal["text", "log_window", "tabular", "text_pair"]
    output_type: Literal["binary", "multiclass", "multilabel", "spans", "structured_json", "number"]
    labels: list[Label]
    positive_definition: Optional[str] = None
    error_preference: Literal["recall_first", "precision_first", "balanced"] = "balanced"
    per_class_error_costs: Optional[dict[str, float]] = None
    optimization_metric: Literal["macro_f1", "recall_at_fpr", "pr_auc", "accuracy"] = "macro_f1"
    fpr_target: Optional[float] = None
    thresholds: Thresholds
    needs_reason: bool = False
    monthly_volume: Optional[int] = None
    latency_budget_ms: Optional[float] = None
    deployment: Literal["offline", "cloud_ok"] = "cloud_ok"
    build_budget_usd: Optional[float] = None
    build_budget_minutes: Optional[float] = None
    sample_inputs: list[str] = Field(default_factory=list)
    window_spec: Optional[WindowSpec] = None
    dataset_key: Optional[str] = None          # registry key in config/datasets.yaml when public data is used
    plan_changes: list[str] = Field(default_factory=list)   # "plan change" lines shown at intake


# ---- 5.2 dataset_manifest.json -----------------------------------------
class SourceInfo(Schema):
    name: str
    url: str
    license: str
    license_ok: bool
    rows_used: int
    is_synthetic: bool = False
    citation: list[str] = Field(default_factory=list)


class SplitInfo(Schema):
    rows: int
    class_counts: dict[str, int]


class DatasetManifest(Schema):
    sources: list[SourceInfo]
    label_mapping: dict[str, Any]
    format_match: dict[str, Any]
    splits: dict[str, SplitInfo]
    processing: list[str]
    sampling: dict[str, Any]


# ---- 5.3 dataset_stats.json --------------------------------------------
class DatasetStats(Schema):
    rows: int
    label_counts: dict[str, int]
    n_classes: int
    imbalance_ratio: float
    smallest_class: int
    avg_input_chars: float
    keyword_density: float
    structured: bool
    input_type: str


# ---- 5.4 candidate_plan.json -------------------------------------------
class CandidateSpec(Schema):
    id: str                       # e.g. "A-03"
    family: str                   # A..L or H
    rung: int
    params: dict[str, Any]
    search_space: dict[str, list[Any]] = Field(default_factory=dict)
    strategy: Literal["real_only", "real_plus_teacher", "real_plus_synthetic"] = "real_only"
    reason: str = ""


class CandidatePlan(Schema):
    candidates: list[CandidateSpec]
    excluded: dict[str, str]
    summary: str
    planner_source: Literal["llm", "deterministic_fallback"]


# ---- 5.5 runs.json -----------------------------------------------------
RunStatus = Literal["queued", "running", "done", "failed", "timeout", "eliminated"]


class CandidateRun(Schema):
    cand: str
    family: str
    config: dict[str, Any]
    seed: int = 0
    status: RunStatus = "queued"
    round_reached: int = 0
    data_frac: float = 0.0
    error_log: Optional[str] = None
    fix_attempts: int = 0
    metrics_path: Optional[str] = None
    elimination_reason: Optional[str] = None
    val_score: Optional[float] = None
    val_secondary: Optional[float] = None     # tie-breaker: PR-AUC (binary) or macro-F1 (multiclass)
    history: list[dict[str, Any]] = Field(default_factory=list)


class Runs(Schema):
    runs: list[CandidateRun]


# ---- 5.6 metrics.json --------------------------------------------------
class Metrics(Schema):
    primary_metric: str
    primary: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    accuracy: float
    per_class: dict[str, dict[str, float]]      # label -> {precision, recall, f1, support}
    pr_auc: Optional[float] = None
    recall_at_fpr: Optional[float] = None
    fpr_target: Optional[float] = None
    calibration_error: Optional[float] = None
    p50_ms: float
    p99_ms: float
    throughput_per_s: float
    model_size_mb: float
    cost_per_1m_usd: float
    cost_formula: dict[str, Any]
    n: int
    split: str


# ---- 5.7 eval_report.json ----------------------------------------------
class FrontierEntry(Schema):
    cand: str
    family: str
    role: Literal["recommended", "most_accurate", "cheapest", "alternative"]
    val_primary: float
    cost_per_1m_usd: float
    p50_ms: float


class EvalReport(Schema):
    task_id: str
    primary_metric: str
    validation_rounds: list[dict[str, Any]]
    frontier: list[FrontierEntry]
    pareto_points: list[dict[str, Any]]
    calibration: dict[str, Any]
    cascade: Optional[dict[str, Any]] = None
    final: Optional[dict[str, Any]] = None              # sealed-test metrics of the chosen model
    final_sample: Optional[dict[str, Any]] = None       # chosen model on the baseline's sealed sample
    seeds: dict[str, dict[str, Any]] = Field(default_factory=dict)
    val_vs_sealed: Optional[dict[str, float]] = None
    teacher_agreement: Optional[dict[str, Any]] = None
    baseline: Optional[dict[str, Any]] = None
    real_vs_synthetic: Optional[dict[str, Any]] = None
    more_data_curve: list[dict[str, float]] = Field(default_factory=list)
    decision: dict[str, Any] = Field(default_factory=dict)
    repair_rounds: list[dict[str, Any]] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    data_sources: list[dict[str, Any]] = Field(default_factory=list)
    winner: Optional[str] = None          # best single candidate
    chosen: Optional[str] = None          # what ships (the winner, or a cascade around it)
    winner_reason: str = ""


# ---- 5.8 error_patterns.json -------------------------------------------
class ErrorPattern(Schema):
    pattern: str
    count: int
    example_ids: list[str]
    suggested_data_fix: str
    true_label: Optional[str] = None
    predicted_label: Optional[str] = None


class ErrorPatterns(Schema):
    patterns: list[ErrorPattern]
    source: Literal["llm", "confusion_fallback"] = "llm"


# ---- 5.9 versions.json -------------------------------------------------
class ApiKeyRecord(Schema):
    key_id: str
    hash: str
    created: float
    revoked: Optional[float] = None
    user_id: Optional[str] = None        # who created it (Supabase user); None = local dev / no login


class VersionRecord(Schema):
    version: int
    run_id: str
    sealed_metrics: dict[str, Any]
    gate_result: Literal["deployed", "rejected", "rolled_back"]
    reason: str
    artifact_uri: str
    created: float
    live: bool = False
    candidate: Optional[str] = None
    artifact_files: Optional[dict[str, str]] = None     # file name -> SHA-256, written with the bundle


class Versions(Schema):
    specialist_id: str
    display_name: str
    monogram: str
    color: str
    task_id: str
    api_route: str
    user_id: Optional[str] = None        # owner (Supabase user); None = public demo specialist / local dev
    api_keys: list[ApiKeyRecord] = Field(default_factory=list)
    versions: list[VersionRecord] = Field(default_factory=list)


# ---- 5.10 corrections.json ---------------------------------------------
class Correction(Schema):
    input: str
    predicted_label: str
    corrected_label: str
    timestamp: float
    source: str = "user"


class Corrections(Schema):
    corrections: list[Correction]


# ---- 5.11 run_state.json -----------------------------------------------
class RunState(Schema):
    run_id: str
    task_id: str
    stage: str
    repair_round: int = 0
    spend_usd: float = 0.0
    budget_usd: float
    started: float
    updated: float
    finished: Optional[float] = None
    status: Literal["running", "done", "failed", "stopped_budget"] = "running"
    message: str = ""
    kind: Literal["build", "improve"] = "build"


# ---- 5.12 events.jsonl entries -----------------------------------------
class Event(Schema):
    ts: float
    agent: Literal["Orchestrator", "Data", "Planner", "Trainer", "Evaluator", "Deploy"]
    stage: str
    message: str
    data_ref: Optional[str] = None
    spend_usd: float = 0.0
    kind: str = "narration"      # narration | candidate | round | pareto | handoff | done | error
    data: Optional[dict[str, Any]] = None
