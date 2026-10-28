"""Default task cards for the showcase tasks. Intake (clarifying questions) edits these in the UI.

Thresholds here are the user's quality bar, set before any run; they are not results.
"""
from __future__ import annotations

from backend import config
from backend.schemas import Label, TaskCard, Thresholds, WindowSpec

PROCUREMENT_SAMPLES = [
    "PURCHASE OF LAPTOP COMPUTERS AND DOCKING STATIONS",
    "JANITORIAL SERVICES FOR FEDERAL BUILDING",
    "ROOF REPLACEMENT AT BUILDING 12",
    "OFFICE SUPPLIES - TONER CARTRIDGES",
    "PHARMACEUTICALS FOR VA MEDICAL CENTER",
]


def procurement_card(**overrides) -> TaskCard:
    psc = config.psc_categories()
    defs = psc["category_definitions"]
    card = TaskCard(
        task_id="procurement", task_name="Procurement Categorizer",
        description="Sort federal purchase records into spending categories from their short description.",
        input_type="text", output_type="multiclass",
        labels=[Label(name=c, definition=defs.get(c, "")) for c in psc["categories"]],
        error_preference="balanced", optimization_metric="macro_f1",
        thresholds=Thresholds(primary_min=0.60), needs_reason=True, monthly_volume=2_000_000,
        latency_budget_ms=50, deployment="cloud_ok", build_budget_usd=config.credit_budget_usd(),
        build_budget_minutes=30, sample_inputs=PROCUREMENT_SAMPLES, dataset_key="usaspending_contracts")
    return card.model_copy(update=overrides)


def logs_card(**overrides) -> TaskCard:
    card = TaskCard(
        task_id="hdfs_logs", task_name="Log Anomaly Detector",
        description="Flag anomalous sessions in Hadoop file-system (HDFS) logs. Each input is one block's log window.",
        input_type="log_window", output_type="binary",
        labels=[Label(name="anomaly", definition="The block's session shows a failure or abnormal behavior"),
                Label(name="normal", definition="The block's session completed normally")],
        positive_definition="anomaly", error_preference="recall_first", optimization_metric="recall_at_fpr",
        fpr_target=0.01, thresholds=Thresholds(primary_min=0.90), needs_reason=True, monthly_volume=5_000_000,
        latency_budget_ms=20, deployment="cloud_ok", build_budget_usd=config.credit_budget_usd(),
        build_budget_minutes=30, window_spec=WindowSpec(group_by="block_id"), dataset_key="loghub_hdfs_v1",
        sample_inputs=[])
    return card.model_copy(update=overrides)


DEMO_TASKS = {"procurement": procurement_card, "hdfs_logs": logs_card}
