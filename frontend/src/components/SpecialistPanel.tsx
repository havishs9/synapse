import { useEffect, useState } from "react";
import { fmtMs, fmtUsd, getJSON, postForm, postJSON } from "../lib/api";
import { ReportDrawer } from "./ReportDrawer";
import { PanelExtras } from "./PanelExtras";
import { CompareDialog, UseDialog } from "./PanelOverlays";

export type SpecialistDetail = any;

const STAGE_NAME: Record<string, string> = {
  J: "Rules", A: "TF-IDF", E: "LightGBM", I: "Embedding kNN", B: "Qwen3 embeddings", C: "Local embeddings",
  K: "Prompted Nemotron", L: "Prompted Nemotron Super",
};
/** "A-07" → "TF-IDF". */
export const stageName = (cand?: string | null) => (cand ? STAGE_NAME[cand[0]] ?? cand : "");

/** Cascade split on the sealed test set, e.g. "TF-IDF 64% / Prompted Nemotron 36%". Takes a version (its stored
 * sealed metrics, else its report card's) or a metrics object. */
export function cascadeSplit(v: any): string | null {
  const shares = (v?.stage_shares ?? v?.sealed_metrics?.stage_shares ?? v?.report?.sealed?.stage_shares) as Record<string, number> | undefined;
  if (!shares || Object.keys(shares).length < 2) return null;
  return Object.entries(shares).map(([k, v]) => `${stageName(k)} ${Math.round(v * 100)}%`).join(" / ");
}

export function SpecialistPanel({ sid, onChanged, onClose, onImproveStarted }: {
  sid: string; onChanged: () => void; onClose: () => void; onImproveStarted: (runId: string, replay: boolean, name: string) => void;
}) {
  const [spec, setSpec] = useState<SpecialistDetail | null>(null);
  const [input, setInput] = useState("");
  const [result, setResult] = useState<any>(null);
  const [resultInput, setResultInput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState<any[] | null>(null);
  const [overlay, setOverlay] = useState<"report" | "compare" | "use" | null>(null);

  const load = () => getJSON(`/api/specialists/${sid}`).then(setSpec).catch((e) => setError(e.message));
  useEffect(() => { load(); setResult(null); setBatch(null); setInput(""); }, [sid]);  // eslint-disable-line
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
  const split = cascadeSplit(live);

  const run = async () => {
    setBusy(true); setError(""); setResult(null);
    try { setResult(await postJSON(`/api/specialists/${sid}/predict`, { input })); setResultInput(input); }
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
    const csv = ["input,label,confidence,answered_by", ...batch.map((r) => [esc(r.input), esc(r.label), r.confidence, esc(r.answered_by ?? "")].join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `${sid}-predictions.csv`; a.click();
  };

  return (
    <div className="relative flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-3">
        <span className="monogram-in flex h-8 w-8 shrink-0 items-center justify-center rounded text-sm font-semibold text-white" style={{ background: color }} aria-hidden>{spec.monogram}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-md font-semibold">{spec.display_name} {live ? `v${live.version}` : ""}</div>
          <div className="truncate text-xs text-ink-3" title={live?.candidate}>{live ? (split ?? stageName(live.bundle.candidate)) + " · live" : "No live version"}</div>
        </div>
        <div className="order-3 flex w-full gap-1.5 sm:order-2 sm:w-auto">
          <button className="btn" onClick={() => setOverlay("compare")} disabled={!live}>Compare</button>
          <button className="btn" onClick={() => setOverlay("report")}>Report</button>
          <button className="btn" onClick={() => setOverlay("use")} disabled={!live}>Use</button>
        </div>
        <button className="btn-ghost order-2 shrink-0 text-xs sm:order-3" onClick={onClose} aria-label="Close pane">Close</button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {!live && <p className="mb-3 rounded border border-border p-3 text-sm text-ink-2">
          No version passed the gate yet: {spec.versions[0]?.reason}. Open Report for details.</p>}
        <label className="mb-1 block text-sm font-medium" htmlFor="spec-input">{meta?.expected_format ?? "Input"}</label>
        <textarea id="spec-input" className="input mono min-h-[96px] text-sm" value={input} onChange={(e) => setInput(e.target.value)}
          rows={isLog ? 10 : 3} placeholder={isLog ? "Paste all log lines for one block (one window)" : "e.g. PURCHASE OF LAPTOP COMPUTERS"}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") run(); }} />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button className="btn-primary" onClick={run} disabled={!input.trim() || busy || !live}>{busy ? "Running…" : "Run"}</button>
          {meta?.example_input && <button className="btn" onClick={() => setInput(meta.example_input)}>Try an example</button>}
          {isLog && !meta?.example_input && <button className="btn" onClick={() => setInput(LOG_TEMPLATE)}
            title="Built from the dataset's event templates; not a real HDFS record">Try a template example</button>}
          <label className="btn cursor-pointer">Upload batch
            <input type="file" className="hidden" accept=".csv,.txt,.jsonl,.log" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </label>
        </div>
        {isLog && !meta?.example_input && !input && <p className="mt-2 text-xs text-ink-3">
          Raw HDFS logs can't be shared here, so the example is built from the dataset's event templates and labeled as such. Paste a real block's lines for a real check.</p>}
        {error && <p className="mt-3 text-sm text-danger" role="alert">{error}</p>}
        {result && (
          <div className="card mt-3 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded px-2 py-0.5 text-sm font-medium" style={{ background: `${color}1f`, color: "var(--ink)", borderLeft: `3px solid ${color}` }}>{result.label}</span>
              <span className="text-sm text-ink-2">{(result.confidence * 100).toFixed(0)}% confidence</span>
              <span className="ml-auto text-xs text-ink-3">{fmtMs(result.latency_ms)} model time</span>
            </div>
            {result.reason && <p className="mt-2 text-sm text-ink-2">{result.reason}</p>}
            {result.answered_by && <p className="mt-1 text-xs text-ink-3">
              Answered by {stageName(result.answered_by)} ({result.answered_by}){result.escalated ? ": the cheaper stage wasn't confident, so it escalated" : ""}.</p>}
            {!result.answered_by && result.escalated && <p className="mt-1 text-xs text-ink-3">Escalated to the prompted LLM because the fast model wasn't confident.</p>}
            {result.escalation_unavailable && <p className="mt-1 text-xs text-ink-3">
              The fast model wasn't confident, but the next stage (a cloud call) didn't answer in time, so this is the fast model's answer. Run it again to retry.</p>}
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
                <thead className="sticky top-0 bg-surface-2 text-left text-xs text-ink-2"><tr><th className="px-2 py-1">Input</th><th className="px-2 py-1">Label</th><th className="px-2 py-1">Conf.</th><th className="px-2 py-1">By</th></tr></thead>
                <tbody>{batch.slice(0, 500).map((r, i) => (
                  <tr key={i} className="border-t border-border"><td className="mono max-w-[260px] truncate px-2 py-1 text-xs">{r.input}</td>
                    <td className="px-2 py-1">{r.label}</td><td className="px-2 py-1 tabular-nums">{(r.confidence * 100).toFixed(0)}%</td>
                    <td className="px-2 py-1 text-xs text-ink-3">{stageName(r.answered_by)}</td></tr>))}</tbody>
              </table>
            </div>
          </div>
        )}
        <Dashboard spec={spec} />
        <PanelExtras spec={spec} sid={sid} onChanged={() => { load(); onChanged(); }} lastResult={result} lastInput={resultInput}
          onImproveStarted={(runId, replay) => onImproveStarted(runId, replay, spec.display_name)} />
      </div>
      {overlay === "report" && <ReportDrawer spec={spec} onClose={() => setOverlay(null)} />}
      {overlay === "compare" && <CompareDialog spec={spec} sid={sid} initial={input || meta?.example_input || (isLog ? LOG_TEMPLATE : "")} onClose={() => setOverlay(null)} />}
      {overlay === "use" && <UseDialog spec={spec} sid={sid} onClose={() => setOverlay(null)} onChanged={load} />}
    </div>
  );
}

/** A normal block's lifecycle written from the dataset's event templates (HDFS.log_templates.csv: E5 receiving, E22
 * allocate, E11 terminating, E9 received, E26 addStoredBlock) with made-up block ID, IPs and sizes. Not a real
 * record: raw HDFS lines can't be committed. */
const LOG_TEMPLATE = [
  "081109 101500 401 INFO dfs.DataNode$DataXceiver: Receiving block blk_4242424242424242424 src: /10.0.0.11:50110 dest: /10.0.0.11:50010",
  "081109 101500 35 INFO dfs.FSNamesystem: BLOCK* NameSystem.allocateBlock: /user/example/part-00001. blk_4242424242424242424",
  "081109 101500 402 INFO dfs.DataNode$DataXceiver: Receiving block blk_4242424242424242424 src: /10.0.0.12:50120 dest: /10.0.0.12:50010",
  "081109 101501 403 INFO dfs.DataNode$PacketResponder: PacketResponder 0 for block blk_4242424242424242424 terminating",
  "081109 101501 403 INFO dfs.DataNode$PacketResponder: Received block blk_4242424242424242424 of size 67108864 from /10.0.0.11",
  "081109 101501 27 INFO dfs.FSNamesystem: BLOCK* NameSystem.addStoredBlock: blockMap updated: 10.0.0.12:50010 is added to blk_4242424242424242424 size 67108864",
].join("\n");

function Dashboard({ spec }: { spec: SpecialistDetail }) {
  const v = spec.live ?? spec.versions[0];
  if (!v) return null;
  const rc = v.report, s = v.sealed_metrics ?? {};
  const pc = s.per_class ?? {};
  const base = rc?.baseline, fs = rc?.specialist_on_baseline_sample;
  const cost = v.bundle?.cost_per_1m_usd ?? rc?.cost_per_1m_usd;
  const split = cascadeSplit(v);
  return (
    <section className="mt-6">
      <h3 className="mb-2 text-sm font-medium">Dashboard · v{v.version}</h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label={`Sealed test ${s.primary_metric ?? "score"}`} value={s.primary?.toFixed(3)} hint={s.n ? `${s.n.toLocaleString()} records` : undefined} />
        <Stat label="Cost per 1M predictions" value={cost != null ? fmtUsd(cost) : "n/a"} />
        <Stat label="Latency p50 / p99" value={`${fmtMs(v.bundle?.p50_ms ?? rc?.latency?.p50_ms)} / ${fmtMs(v.bundle?.p99_ms ?? rc?.latency?.p99_ms)}`} />
        <Stat label="Same sealed records" value={base && fs ? `${fs.metrics.primary.toFixed(3)} vs ${base.metrics.primary.toFixed(3)}` : "n/a"}
          hint={base ? `specialist vs Nemotron Ultra, ${base.n} records` : undefined} />
      </div>
      {split && <p className="mt-2 text-xs text-ink-2">Answered on the sealed test set by {split}.</p>}
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

export function Stat({ label, value, hint }: { label: string; value?: string; hint?: string }) {
  return (
    <div className="rounded border border-border p-2">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="mt-0.5 text-md font-medium tabular-nums">{value ?? "n/a"}</div>
      {hint && <div className="text-xs text-ink-3">{hint}</div>}
    </div>
  );
}
