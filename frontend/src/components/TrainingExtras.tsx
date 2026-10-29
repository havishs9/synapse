import type { RunEvent } from "../lib/types";
import type { CandPoint } from "../lib/useRun";
import { rungOf } from "../lib/useRun";
import { fmtUsd } from "../lib/api";

const AGENTS = ["Data", "Planner", "Trainer", "Evaluator", "Deploy"] as const;
const RUNG_VAR: Record<number, string> = { 0: "var(--rung-h)", 1: "var(--rung-1)", 2: "var(--rung-2)", 3: "var(--rung-3)" };

/** Agent lanes: one lane per agent with its latest line, and the JSON files handed between them (spec 01 §2.3). */
export function AgentLanes({ events, done }: { events: RunEvent[]; done?: boolean }) {
  const latest: Record<string, RunEvent | undefined> = {};
  const counts: Record<string, number> = {};
  for (const e of events) {
    if (!e.message) continue;
    latest[e.agent] = e;
    counts[e.agent] = (counts[e.agent] ?? 0) + 1;
  }
  const handoffs = events.filter((e) => e.kind === "handoff" && e.data_ref);
  const active = [...events].reverse().find((e) => e.message && e.kind !== "done")?.agent;
  return (
    <section aria-label="Agent lanes">
      <h3 className="mb-1 text-sm font-medium">Agents</h3>
      <ol className="flex flex-wrap items-center gap-1 text-xs" aria-label="Handoffs">
        {handoffs.map((h, i) => (
          <li key={i} className="flex items-center gap-1">
            {i > 0 && <span className="text-ink-3" aria-hidden>→</span>}
            <span className="rounded border border-border px-1.5 py-0.5"><span className="text-ink-3">{h.agent}</span> <span className="mono">{h.data_ref}</span></span>
          </li>
        ))}
      </ol>
      <div className="mt-2 divide-y divide-border rounded border border-border">
        {AGENTS.map((a) => {
          const e = latest[a];
          return (
            <div key={a} className="grid grid-cols-[76px_1fr_auto] items-baseline gap-2 px-2 py-1.5 text-sm">
              <span className={`flex items-center gap-1.5 ${a === active ? "text-ink" : "text-ink-3"}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${a === active ? "bg-focus" : e ? "bg-ink-3" : "bg-border"}`} aria-hidden />{a}
              </span>
              <span className={`min-w-0 truncate ${e ? "" : "text-ink-3"}`} title={e?.message}>{e?.message.replace(new RegExp(`^${a}: `), "") ?? (done ? "Not used in this run" : "Waiting")}</span>
              <span className="text-xs tabular-nums text-ink-3">{counts[a] ?? 0}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return null;
  const w = 48, h = 14, lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - lo) / span) * h}`).join(" ");
  return <svg width={w} height={h} aria-hidden className="shrink-0"><polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} /></svg>;
}

/** Tournament bracket: rounds as columns; each candidate a card with its validation sparkline; eliminated cards
 * gray out with a one-line reason. */
export function Bracket({ rounds, cands, metric }: { rounds: any[]; cands: CandPoint[]; metric: string }) {
  if (!rounds.length) return null;
  const byCand = new Map(cands.map((c) => [c.cand, c]));
  const n = rounds.length;
  return (
    <section aria-label="Tournament bracket">
      <h3 className="mb-1 text-sm font-medium">Rounds</h3>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {rounds.map((r, i) => {
          const list: string[] = r.cands ?? [];
          const next = new Set<string>(rounds[i + 1]?.cands ?? []);
          return (
            <div key={i} className="w-[188px] shrink-0">
              <div className="mb-1 text-xs text-ink-3">Round {r.round}{r.data_frac ? ` · ${Math.round(r.data_frac * 100)}% of data` : ""} · {list.length}</div>
              <ul className="max-h-[260px] space-y-1 overflow-y-auto pr-1">
                {list.map((id) => {
                  const c = byCand.get(id);
                  const out = i < n - 1 ? !next.has(id) : c?.status === "eliminated";
                  const color = RUNG_VAR[rungOf(c?.family ?? id[0])];
                  return (
                    <li key={id} className={`rounded border border-border px-1.5 py-1 text-xs ${out ? "opacity-45" : ""}`} title={out ? c?.reason : undefined}>
                      <div className="flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} aria-hidden />
                        <span className="mono">{id}</span>
                        <span className="ml-auto tabular-nums text-ink-2">{c?.history[Math.min(i, c.history.length - 1)]?.toFixed(3) ?? ""}</span>
                        <Sparkline values={(c?.history ?? []).slice(0, i + 1)} color={color} />
                      </div>
                      {out && c?.reason && <div className="mt-0.5 truncate text-ink-3">{c.reason}</div>}
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
      <p className="mt-1 text-xs text-ink-3">Values are validation {metric}; the sealed test set is used once, at the end.</p>
    </section>
  );
}

/** Credits and minutes spent against the task card's budget. */
export function BudgetMeter({ spend, budget, minutes, budgetMinutes }: { spend: number; budget?: number | null; minutes: number; budgetMinutes?: number | null }) {
  const bar = (v: number, max: number | null | undefined, label: string, text: string) => {
    const pct = max ? Math.min(100, (v / max) * 100) : 0;
    return (
      <div>
        <div className="flex justify-between text-xs"><span className="text-ink-2">{label}</span><span className="tabular-nums text-ink-3">{text}</span></div>
        <div className="mt-1 h-1.5 rounded-full bg-surface-2" role="progressbar" aria-label={label} aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
          <div className={`h-full rounded-full ${pct >= 90 ? "bg-danger" : "bg-ink-2"}`} style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  };
  return (
    <section aria-label="Budget" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {bar(spend, budget, "Model calls", budget ? `${fmtUsd(spend, 3)} of ${fmtUsd(budget)}` : fmtUsd(spend, 3))}
      {bar(minutes, budgetMinutes, "Time", budgetMinutes ? `${minutes.toFixed(1)} of ${budgetMinutes} min` : `${minutes.toFixed(1)} min`)}
    </section>
  );
}
