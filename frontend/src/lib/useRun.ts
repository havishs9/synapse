import { useEffect, useMemo, useRef, useState } from "react";
import { subscribe } from "./api";
import type { RunEvent } from "./types";

export type CandPoint = {
  cand: string; family: string; val?: number; cost?: number; p50?: number; round?: number;
  status: string; reason?: string; history: number[]; rounds: number[];
};

const RUNG: Record<string, number> = { J: 1, A: 1, E: 1, F: 1, I: 2, B: 2, C: 2, D: 2, K: 3, L: 3, H: 0 };
export const rungOf = (family: string) => RUNG[family] ?? 1;

/** Collect a run's events from SSE (live tail or timed replay) and derive the training-view state. */
export function useRun(runId: string, replay: boolean, speed = 1) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [done, setDone] = useState(false);
  const [watched, setWatched] = useState(false);     // the run finished while this view was open (not a finished run reopened)
  const opened = useRef(0);
  useEffect(() => {
    setEvents([]); setDone(false); setWatched(false);
    opened.current = Date.now();
    const url = `/api/runs/${runId}/events${replay ? `?replay=true&speed=${speed}` : ""}`;
    return subscribe(url, (e) => {
      setEvents((prev) => [...prev, e]);
      if (e.kind === "done" && Date.now() - opened.current > 2500) setWatched(true);
    }, () => setDone(true));
  }, [runId, replay, speed]);

  return useMemo(() => {
    const cands = new Map<string, CandPoint>();
    let baseline: any = null, rounds: any[] = [], frontier: any[] = [], cascade: any = null, sealed: any = null;
    let result: any = null, gate: any = null;
    for (const e of events) {
      const d = e.data;
      if (e.kind === "candidate" && d?.cand) {
        const c: CandPoint = cands.get(d.cand) ?? { cand: d.cand, family: d.family, status: "queued", history: [], rounds: [] };
        if (d.round != null && !c.rounds.includes(d.round)) c.rounds = [...c.rounds, d.round];
        if (d.status === "done") {
          Object.assign(c, { val: d.val, cost: d.cost_per_1m_usd, p50: d.p50_ms, round: d.round, status: "done" });
          c.history = [...c.history, d.val];
        } else if (d.status === "eliminated") { c.status = "eliminated"; c.reason = d.reason; }
        else if (d.status === "validating") c.status = "running";
        else if (d.status) c.status = d.status;
        cands.set(d.cand, c);
      }
      if (e.kind === "round") rounds = [...rounds, d];
      if (e.kind === "pareto" && d?.baseline) baseline = d.baseline;
      if (e.kind === "pareto" && d?.frontier) frontier = d.frontier;
      if (e.kind === "pareto" && d?.point) cascade = d.point;
      if (e.kind === "pareto" && d?.sealed) sealed = d.sealed;
      if (e.kind === "pareto" && d?.gate) gate = d.gate;
      if (e.kind === "done") result = d;
    }
    const last = events[events.length - 1];
    return { events, cands: [...cands.values()], baseline, rounds, frontier, cascade, sealed, result, gate, done,
             live: watched, replaying: events.some((e) => e.replay),
             spend: last?.spend_usd ?? 0, t0: events[0]?.ts ?? 0, stage: last?.stage ?? "starting" };
  }, [events, done, watched]);
}
