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


def _banking77_intents() -> list[str]:
    """Intent names from the downloaded CSV (empty until `make demo-data` has fetched Banking77)."""
    import csv
    path = config.data_dir() / "raw" / "banking77" / "train.csv"
    if not path.exists():
        return []
    with path.open() as f:
        return sorted({r["category"] for r in csv.DictReader(f)})


def support_card(**overrides) -> TaskCard:
    card = TaskCard(
        task_id="support_tickets", task_name="Support Ticket Router",
        description="Route a bank customer's support message to the right intent so it reaches the right team.",
        input_type="text", output_type="multiclass",
        labels=[Label(name=n, definition=n.replace("_", " ").capitalize()) for n in _banking77_intents()],
        error_preference="balanced", optimization_metric="macro_f1",
        thresholds=Thresholds(primary_min=0.85), needs_reason=False, monthly_volume=500_000,
        latency_budget_ms=500, deployment="cloud_ok", build_budget_usd=config.credit_budget_usd(),
        build_budget_minutes=30, sample_inputs=SUPPORT_SAMPLES, dataset_key="banking77")
    return card.model_copy(update=overrides)


SUPPORT_SAMPLES = [
    "I am still waiting on my card?",
    "Why was I charged a fee for taking out cash?",
    "My top up didn't go through",
    "How do I change my PIN?",
    "I think someone else is using my card",
]

DEMO_TASKS = {"procurement": procurement_card, "hdfs_logs": logs_card, "support_tickets": support_card}

# What one input looks like, for API docs and input errors.
INPUT_HINTS = {"procurement": "One purchase record description", "support_tickets": "One customer support message",
               "hdfs_logs": "One HDFS block's log lines (one window), e.g. lines containing blk_…"}


def input_hint(task_id: str, input_type: str) -> str:
    return INPUT_HINTS.get(task_id) or ("One log window" if input_type == "log_window" else "One text record")
