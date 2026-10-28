import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis, ZAxis, Line, ComposedChart } from "recharts";
import type { CandPoint } from "../lib/useRun";
import { rungOf } from "../lib/useRun";
import { fmtMs, fmtUsd } from "../lib/api";

const RUNG_VAR: Record<number, string> = { 0: "var(--rung-h)", 1: "var(--rung-1)", 2: "var(--rung-2)", 3: "var(--rung-3)" };
export const RUNG_NAME: Record<number, string> = { 1: "Rules + classic ML", 2: "Embeddings", 3: "Prompted LLMs", 0: "Cascade" };

type P = { cand: string; family: string; x: number; y: number; eliminated: boolean; p50?: number; star?: boolean };

function frontierOf(points: P[]) {
  const live = points.filter((p) => !p.eliminated && !p.star).sort((a, b) => a.x - b.x);
  const out: P[] = [];
  let best = -1;
  for (const p of live) if (p.y > best) { out.push(p); best = p.y; }
  return out;
}

export function ParetoLive({ cands, baseline, cascade, target, metric, winner }: {
  cands: CandPoint[]; baseline: any; cascade: any; target?: number; metric: string; winner?: string;
}) {
  const pts: P[] = cands.filter((c) => c.val != null && c.cost != null && c.cost > 0)
    .map((c) => ({ cand: c.cand, family: c.family, x: c.cost!, y: c.val!, eliminated: c.status === "eliminated", p50: c.p50 }));
  if (cascade) pts.push({ cand: cascade.cand, family: "H", x: cascade.cost_per_1m_usd, y: cascade.val_primary, eliminated: false, p50: cascade.p50_ms });
  const star = baseline ? [{ cand: "Nemotron Ultra (zero-shot)", family: "baseline", x: baseline.cost_per_1m_usd, y: baseline.val, eliminated: false, star: true, p50: baseline.p50_ms }] : [];
  const front = frontierOf(pts);
  const xs = [...pts, ...star].map((p) => p.x);
  const domain = xs.length ? [Math.min(...xs) / 3, Math.max(...xs) * 3] : [1e-4, 1e3];

  const Dot = (props: any) => {
    const { cx, cy, payload } = props;
    if (payload.star) {
      const r = 8, pts = Array.from({ length: 10 }, (_, i) => {
        const a = (Math.PI / 5) * i - Math.PI / 2, rr = i % 2 ? r / 2.3 : r;
        return `${cx + rr * Math.cos(a)},${cy + rr * Math.sin(a)}`;
      }).join(" ");
      return <polygon points={pts} fill="var(--star)" />;
    }
    const color = RUNG_VAR[rungOf(payload.family)];
    const isWinner = payload.cand === winner;
    return (
      <g>
        <circle cx={cx} cy={cy} r={isWinner ? 7 : 5} fill={color} fillOpacity={payload.eliminated ? 0.2 : 0.9}
          stroke={isWinner ? "var(--ink)" : "none"} strokeWidth={1.5} className={isWinner ? "pulse-once" : ""} />
      </g>
    );
  };

  return (
    <div>
      <div className="h-[260px] w-full" role="img" aria-label={`Pareto scatter of ${metric} against cost per million predictions`}>
        <ResponsiveContainer>
          <ComposedChart margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="x" type="number" scale="log" domain={domain as any} allowDataOverflow
              tickFormatter={(v) => (v >= 1 ? `$${v.toFixed(0)}` : `$${v.toPrecision(1)}`)} tick={{ fontSize: 11, fill: "var(--ink-3)" }}
              label={{ value: "Cost per 1M predictions (log)", position: "insideBottom", offset: -10, fontSize: 11, fill: "var(--ink-3)" }} />
            <YAxis dataKey="y" type="number" domain={[0, 1]} tick={{ fontSize: 11, fill: "var(--ink-3)" }} width={36} />
            <ZAxis range={[60, 60]} />
            {target != null && <ReferenceLine y={target} stroke="var(--ink-3)" strokeDasharray="4 4"
              label={{ value: `target ${target}`, position: "insideTopRight", fontSize: 11, fill: "var(--ink-3)" }} />}
            <Line data={front} dataKey="y" stroke="var(--ink-2)" strokeWidth={1} dot={false} isAnimationActive={false} type="stepAfter" />
            <Scatter data={pts} shape={<Dot />} isAnimationActive={false} />
            <Scatter data={star} shape={<Dot />} isAnimationActive={false} />
            <Tooltip cursor={false} content={({ payload }) => {
              const d: any = payload?.[0]?.payload;
              if (!d) return null;
              return (
                <div className="card px-2 py-1 text-xs">
                  <div className="font-medium">{d.cand}</div>
                  <div>{metric} {d.y.toFixed(3)} · {fmtUsd(d.x, 4)} / 1M · p50 {fmtMs(d.p50)}</div>
                  {d.eliminated && <div className="text-ink-3">eliminated</div>}
                </div>
              );
            }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 flex flex-wrap gap-3 text-xs text-ink-2">
        {[1, 2, 3, 0].map((r) => (
          <span key={r} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: RUNG_VAR[r] }} />{RUNG_NAME[r]}</span>
        ))}
        <span className="flex items-center gap-1"><span style={{ color: "var(--star)" }}>★</span>Nemotron Ultra</span>
      </div>
    </div>
  );
}
