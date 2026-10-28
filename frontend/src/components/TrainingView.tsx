import { useEffect, useState } from "react";
import { useRun } from "../lib/useRun";
import { NarrationFeed } from "./NarrationFeed";
import { ParetoLive } from "./ParetoLive";
import { fmtUsd } from "../lib/api";
import { Extras } from "./TrainingExtras";

export function TrainingView({ runId, replay, onFinished, card }: {
  runId: string; replay: boolean; onFinished: (r: any) => void; card?: any;
}) {
  const run = useRun(runId, replay, replay ? 8 : 1);
  const [winner, setWinner] = useState<string>();
  useEffect(() => {
    if (!run.result) return;
    fetch(`/api/runs/${runId}/files/eval_report.json`).then((r) => r.ok ? r.json() : null).then((rep) => {
      if (rep?.chosen) setWinner(rep.chosen);
      setTimeout(() => onFinished(run.result), 1400);
    });
  }, [run.result]);  // eslint-disable-line

  const status = run.result?.status;
  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="flex items-baseline justify-between border-b border-border px-4 py-3">
        <div>
          <div className="text-md font-semibold">Building {card?.task_name ?? "specialist"}</div>
          <div className="text-xs text-ink-3">{replay ? "Replay of a recorded run, sped up" : "Live run"} · stage {run.stage}</div>
        </div>
        <div className="text-right text-xs text-ink-2">
          <div>LLM spend {fmtUsd(run.spend, 3)}</div>
          <div>{run.t0 ? `${Math.round((run.events[run.events.length - 1]?.ts ?? run.t0) - run.t0)}s elapsed` : ""}</div>
        </div>
      </div>
      <div className="space-y-4 p-4">
        {status && status !== "done" && <div className="rounded border border-danger px-3 py-2 text-sm text-danger">{[...run.events].reverse().find((e) => e.kind === "error")?.message ?? "Run stopped."}</div>}
        <section>
          <h3 className="mb-1 text-sm font-medium">Candidates</h3>
          <ParetoLive cands={run.cands} baseline={run.baseline} cascade={run.cascade} target={card?.thresholds?.primary_min}
            metric={card?.optimization_metric ?? "score"} winner={winner} />
        </section>
        <Extras run={run} card={card} />
        <section>
          <h3 className="mb-1 text-sm font-medium">What's happening</h3>
          <NarrationFeed runId={runId} events={run.events} t0={run.t0} />
        </section>
      </div>
    </div>
  );
}
