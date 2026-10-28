import { useState } from "react";
import type { Msg } from "../lib/types";
import type { Intake } from "../lib/useIntake";

export function TaskCardMessage({ msg, onBuild }: { msg: Msg; onBuild: (card: any) => void; intake: Intake }) {
  const [card] = useState(msg.card);
  const [started, setStarted] = useState(false);
  if (!card) return null;
  return (
    <div className="card p-4">
      <div className="text-md font-semibold">{card.task_name}</div>
      <p className="mt-1 text-sm text-ink-2">{card.description}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-ink-3">Metric</dt><dd>{card.optimization_metric}{card.fpr_target ? ` at ${card.fpr_target * 100}% FPR` : ""}</dd>
        <dt className="text-ink-3">Target</dt><dd>{card.thresholds.primary_min}</dd>
        <dt className="text-ink-3">Categories</dt><dd>{card.labels.length}</dd>
        <dt className="text-ink-3">Monthly volume</dt><dd>{card.monthly_volume?.toLocaleString() ?? "not set"}</dd>
        <dt className="text-ink-3">Latency budget</dt><dd>{card.latency_budget_ms} ms</dd>
        <dt className="text-ink-3">Deployment</dt><dd>{card.deployment === "offline" ? "Offline only" : "Cloud calls allowed"}</dd>
      </dl>
      <button className="btn-primary mt-4" disabled={started} onClick={() => { setStarted(true); onBuild(card); }}>
        {started ? "Building…" : "Build specialist"}
      </button>
    </div>
  );
}
