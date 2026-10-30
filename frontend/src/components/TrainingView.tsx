import { useEffect, useState } from "react";
import { useRun } from "../lib/useRun";
import { NarrationFeed } from "./NarrationFeed";
import { ParetoLive } from "./ParetoLive";
import { fmtUsd, getJSON } from "../lib/api";
import { AgentLanes, Bracket, BudgetMeter } from "./TrainingExtras";

export function TrainingView({ runId, replay, onFinished, card: cardIn, title, improveOf, onClose }: {
  runId: string; replay: boolean; onFinished: (r: any) => void; card?: any; title?: string; improveOf?: string; onClose: () => void;
}) {
  const run = useRun(runId, replay, replay ? 8 : 1);
  const [winner, setWinner] = useState<string>();
  const [card, setCard] = useState<any>(cardIn);
  const [state, setState] = useState<any>(null);
  useEffect(() => {
    if (!cardIn) getJSON(`/api/runs/${runId}/files/task_card.json`).then(setCard).catch(() => {});
    getJSON(`/api/runs/${runId}/state`).then(setState).catch(() => {});
  }, [runId]);  // eslint-disable-line
  useEffect(() => {
    if (!run.result) return;
    getJSON(`/api/runs/${runId}/state`).then(setState).catch(() => {});
    if (run.result.kind === "improve" || run.result.status !== "done") return;
    getJSON(`/api/runs/${runId}/files/eval_report.json`).then((rep) => rep?.chosen && setWinner(rep.chosen)).catch(() => {})
      .finally(() => { if (run.result?.specialist_id && run.live) window.setTimeout(() => onFinished(run.result), 1400); });
  }, [run.result]);  // eslint-disable-line

  const isImprove = !!improveOf || state?.kind === "improve" || run.result?.kind === "improve";
  const status = run.result?.status;
  const name = card?.task_name ?? title ?? "specialist";
  const elapsed = run.t0 ? Math.round((run.events[run.events.length - 1]?.ts ?? run.t0) - run.t0) : 0;
  const gate = run.gate;
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="truncate text-md font-semibold">{isImprove ? `Improving ${name}` : `Building ${name}`}</div>
          <div className="text-xs text-ink-3">{run.replaying ? "Replay of a recorded run, sped up" : run.live ? "Live run" : "Recorded run"} · {run.done ? "finished" : `stage ${run.stage}`}</div>
        </div>
        <div className="flex shrink-0 items-start gap-3">
          <div className="text-right text-xs tabular-nums text-ink-2">
            <div>LLM spend {fmtUsd(run.spend, 3)}</div>
            <div>{elapsed ? `${elapsed}s elapsed` : ""}</div>
          </div>
          <button className="btn-ghost text-xs" onClick={onClose} aria-label="Close pane">Close</button>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
        {status && status !== "done" && <div className="rounded border border-danger px-3 py-2 text-sm text-danger" role="alert">
          {[...run.events].reverse().find((e) => e.kind === "error")?.message ?? "Run stopped."}</div>}
        {isImprove && gate && (
          <div className={`rounded border px-3 py-2 text-sm ${gate.passed ? "border-ok" : "border-border"}`} role="status">
            <div className="font-medium">{gate.passed ? `Version gate passed: v${run.result?.version ?? "new"} is live` : "Version gate failed: the live version stays"}</div>
            <div className="text-ink-2">{gate.reason}</div>
            {run.result?.specialist_id && <button className="btn mt-2" onClick={() => onFinished(run.result)}>Open specialist</button>}
          </div>
        )}
        {!isImprove && run.result?.status === "done" && run.result?.specialist_id && (
          <div className="flex items-center justify-between rounded border border-border px-3 py-2 text-sm">
            <span>{run.result.deployed ? `Deployed v${run.result.version}` : `v${run.result.version} not deployed: ${run.result.reason}`}</span>
            <button className="btn" onClick={() => onFinished(run.result)}>Open specialist</button>
          </div>
        )}
        <section>
          <h3 className="mb-1 text-sm font-medium">{isImprove ? "Retrained candidates" : "Candidates"}</h3>
          <ParetoLive cands={run.cands} baseline={run.baseline} cascade={run.cascade} target={card?.thresholds?.primary_min}
            metric={card?.optimization_metric ?? "score"} winner={winner} />
        </section>
        <BudgetMeter spend={run.spend} budget={state?.budget_usd ?? card?.build_budget_usd} minutes={elapsed / 60}
          budgetMinutes={card?.build_budget_minutes} />
        <AgentLanes events={run.events} done={run.done} />
        <Bracket rounds={run.rounds} cands={run.cands} metric={card?.optimization_metric ?? "score"} />
        <section>
          <h3 className="mb-1 text-sm font-medium">What's happening</h3>
          <NarrationFeed runId={runId} events={run.events} t0={run.t0} />
        </section>
      </div>
    </div>
  );
}
