import { useEffect, useState } from "react";
import { fmtMs, fmtUsd, getJSON, postForm, postJSON } from "../lib/api";
import { ReportDrawer } from "./ReportDrawer";
import { PanelExtras } from "./PanelExtras";

export type SpecialistDetail = any;

export function SpecialistPanel({ sid, onChanged }: { sid: string; onChanged: () => void }) {
  const [spec, setSpec] = useState<SpecialistDetail | null>(null);
  const [input, setInput] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState<any[] | null>(null);
  const [overlay, setOverlay] = useState<"report" | "compare" | "use" | null>(null);

  const load = () => getJSON(`/api/specialists/${sid}`).then(setSpec).catch((e) => setError(e.message));
  useEffect(() => { load(); setResult(null); setBatch(null); setInput(""); }, [sid]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOverlay(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  if (!spec) return <div className="p-4 text-ink-3">{error || "Loading…"}</div>;

  const live = spec.live;
  const meta = live?.bundle ?? spec.versions[0]?.bundle;
  const isLog = meta?.input_type === "log_window";
  const color = spec.color;

  const run = async () => {
    setBusy(true); setError(""); setResult(null);
    try { setResult(await postJSON(`/api/specialists/${sid}/predict`, { input })); }
    catch (e: any) { setError(e.message); }
    setBusy(false);
  };
  const upload = async (f: File) => {
    setBusy(true); setError(""); setBatch(null);
    const form = new FormData(); form.append("file", f);
    try { setBatch((await postForm(`/api/specialists/${sid}/predict_batch`, form)).rows); }
    catch (e: any) { setError(e.message); }
    setBusy(false);
  };
  const downloadCsv = () => {
    if (!batch) return;
    const esc = (s: any) => `"${String(s ?? "").replace(/"/g, '""')}"`;
    const csv = ["input,label,confidence,escalated", ...batch.map((r) => [esc(r.input), esc(r.label), r.confidence, r.escalated].join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `${sid}-predictions.csv`; a.click();
  };

  return (
    <div className="relative flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border px-4 py-3">
        <span className="flex h-8 w-8 items-center justify-center rounded text-sm font-semibold text-white" style={{ background: color }}>{spec.monogram}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-md font-semibold">{spec.display_name} {live ? `v${live.version}` : ""}</div>
          <div className="text-xs text-ink-3">{live ? `${live.bundle.candidate} · live` : "No live version"}</div>
        </div>
        <button className="btn" onClick={() => setOverlay("compare")} disabled={!live}>Compare</button>
        <button className="btn" onClick={() => setOverlay("report")}>Report</button>
        <button className="btn" onClick={() => setOverlay("use")} disabled={!live}>Use</button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {!live && <p className="mb-3 rounded border border-border p-3 text-sm text-ink-2">
          No version passed the gate yet: {spec.versions[0]?.reason}. Open Report for details.</p>}
        <label className="mb-1 block text-sm font-medium" htmlFor="spec-input">{meta?.expected_format ?? "Input"}</label>
        <textarea id="spec-input" className="input mono min-h-[96px] text-sm" value={input} onChange={(e) => setInput(e.target.value)}
          rows={isLog ? 10 : 3} placeholder={isLog ? "Paste all log lines for one block" : "e.g. PURCHASE OF LAPTOP COMPUTERS"}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") run(); }} />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button className="btn-primary" onClick={run} disabled={!input.trim() || busy || !live}>{busy ? "Running…" : "Run"}</button>
          {meta?.example_input && <button className="btn" onClick={() => setInput(meta.example_input)}>Try an example</button>}
          <label className="btn cursor-pointer">Upload batch
            <input type="file" className="hidden" accept=".csv,.txt,.jsonl,.log" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </label>
        </div>
        {error && <p className="mt-3 text-sm text-danger" role="alert">{error}</p>}
        {result && (
          <div className="card mt-3 p-3">
            <div className="flex items-center gap-2">
              <span className="rounded px-2 py-0.5 text-sm font-medium" style={{ background: `${color}1f`, color: "var(--ink)", borderLeft: `3px solid ${color}` }}>{result.label}</span>
              <span className="text-sm text-ink-2">{(result.confidence * 100).toFixed(0)}% confidence</span>
              <span className="ml-auto text-xs text-ink-3">{fmtMs(result.latency_ms)} model time</span>
            </div>
            {result.reason && <p className="mt-2 text-sm text-ink-2">{result.reason}</p>}
            {result.escalated && <p className="mt-1 text-xs text-ink-3">Escalated to the prompted LLM because the fast model wasn't confident.</p>}
          </div>
        )}
        {batch && (
          <div className="mt-3">
            <div className="mb-1 flex items-center justify-between text-sm">
              <span>{batch.length.toLocaleString()} records scored</span>
              <button className="btn" onClick={downloadCsv}>Download CSV</button>
            </div>
            <div className="max-h-64 overflow-auto rounded border border-border">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface-2 text-left text-xs text-ink-2"><tr><th className="px-2 py-1">Input</th><th className="px-2 py-1">Label</th><th className="px-2 py-1">Conf.</th></tr></thead>
                <tbody>{batch.slice(0, 500).map((r, i) => (
                  <tr key={i} className="border-t border-border"><td className="mono max-w-[280px] truncate px-2 py-1 text-xs">{r.input}</td>
                    <td className="px-2 py-1">{r.label}</td><td className="px-2 py-1 tabular-nums">{(r.confidence * 100).toFixed(0)}%</td></tr>))}</tbody>
              </table>
            </div>
          </div>
        )}
        <Dashboard spec={spec} />
        <PanelExtras spec={spec} sid={sid} onChanged={() => { load(); onChanged(); }} lastResult={result} lastInput={input} />
      </div>
      {overlay === "report" && <ReportDrawer spec={spec} onClose={() => setOverlay(null)} />}
      <PanelOverlays which={overlay} spec={spec} sid={sid} onClose={() => setOverlay(null)} onChanged={load} />
    </div>
  );
}

import { PanelOverlays } from "./PanelOverlays";

function Dashboard({ spec }: { spec: SpecialistDetail }) {
  const v = spec.live ?? spec.versions[0];
  if (!v) return null;
  const rc = v.report, s = v.sealed_metrics ?? {};
  const pc = s.per_class ?? {};
  const base = rc?.baseline, fs = rc?.specialist_on_baseline_sample;
  return (
    <section className="mt-6">
      <h3 className="mb-2 text-sm font-medium">Dashboard · v{v.version}</h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label={`Sealed ${s.primary_metric ?? "score"}`} value={s.primary?.toFixed(3)} />
        <Stat label="Cost per record" value={rc?.cost_per_1m_usd != null ? fmtUsd(rc.cost_per_1m_usd / 1e6, 6) : "n/a"} />
        <Stat label="Latency p50 / p99" value={`${fmtMs(rc?.latency?.p50_ms)} / ${fmtMs(rc?.latency?.p99_ms)}`} />
        <Stat label="Nemotron Ultra, same rows" value={base ? `${base.metrics.primary.toFixed(3)} vs ${fs?.metrics?.primary?.toFixed(3)}` : "n/a"} />
      </div>
      <div className="mt-3 max-h-56 overflow-auto rounded border border-border">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface-2 text-left text-xs text-ink-2"><tr><th className="px-2 py-1">Class</th><th className="px-2 py-1">Precision</th><th className="px-2 py-1">Recall</th><th className="px-2 py-1">n</th></tr></thead>
          <tbody>{Object.entries(pc).map(([k, m]: any) => (
            <tr key={k} className="border-t border-border"><td className="px-2 py-1">{k}</td><td className="px-2 py-1 tabular-nums">{m.precision.toFixed(2)}</td>
              <td className="px-2 py-1 tabular-nums">{m.recall.toFixed(2)}</td><td className="px-2 py-1 tabular-nums text-ink-3">{m.support}</td></tr>))}</tbody>
        </table>
      </div>
    </section>
  );
}

export function Stat({ label, value }: { label: string; value?: string }) {
  return (
    <div className="rounded border border-border p-2">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="mt-0.5 text-md font-medium tabular-nums">{value ?? "n/a"}</div>
    </div>
  );
}
