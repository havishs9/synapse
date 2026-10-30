import { useEffect, useState } from "react";
import { deleteJSON, getJSON, postJSON } from "../lib/api";
import { cascadeSplit } from "./SpecialistPanel";

type Correction = { input: string; predicted_label: string; corrected_label: string; timestamp: number; source: string };

/** Corrections, the validated v1 → v2 update, and version history with rollback (spec 01 §2.9). */
export function PanelExtras({ spec, sid, onChanged, lastResult, lastInput, onImproveStarted }: {
  spec: any; sid: string; onChanged: () => void; lastResult: any; lastInput: string;
  onImproveStarted: (runId: string, replay: boolean) => void;
}) {
  const labels: string[] = spec.live?.bundle?.labels ?? [];
  const [rows, setRows] = useState<Correction[]>([]);
  const [fix, setFix] = useState("");
  const [held, setHeld] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState<any>(null);

  useEffect(() => {
    getJSON(`/api/specialists/${sid}/corrections`).then((r) => setRows(r.corrections)).catch(() => {});
    getJSON(`/api/specialists/${sid}/improve`).then(setInfo).catch(() => {});
  }, [sid]);
  const replayMode = info?.mode === "replay";
  useEffect(() => { setFix(""); }, [lastResult]);

  const act = async (what: string, fn: () => Promise<void>) => {
    setBusy(what); setError("");
    try { await fn(); } catch (e: any) { setError(e.message); }
    setBusy("");
  };
  const addOne = () => act("add", async () => {
    const r = await postJSON(`/api/specialists/${sid}/corrections`, { corrections: [{ input: lastInput, predicted_label: lastResult.label, corrected_label: fix }] });
    setRows(r.corrections); setFix("");
  });
  const loadHeld = () => act("held", async () => setHeld(await getJSON(`/api/specialists/${sid}/holdback?limit=2000`)));
  const addHeld = () => act("addheld", async () => {
    const r = await postJSON(`/api/specialists/${sid}/corrections`, { corrections: held.wrong.map((w: any) => ({
      input: w.input, predicted_label: w.predicted_label, corrected_label: w.corrected_label, source: "holdback" })) });
    setRows(r.corrections);
  });
  const remove = (i?: number) => act("remove", async () => setRows((await deleteJSON(`/api/specialists/${sid}/corrections${i == null ? "" : `?index=${i}`}`)).corrections));
  const improve = () => act("improve", async () => {
    const r = await postJSON(`/api/specialists/${sid}/improve`);
    setRows([]); onImproveStarted(r.run_id, !!r.replay);
  });
  const rollback = () => act("rollback", async () => { await postJSON(`/api/specialists/${sid}/rollback`); onChanged(); });

  const live = spec.live;
  const fromHeld = rows.filter((r) => r.source === "holdback").length;
  const canRollback = live && spec.versions.some((v: any) => v.version < live.version && v.gate_result !== "rejected");

  return (
    <>
      <section className="mt-6" aria-label="Corrections">
        <h3 className="text-sm font-medium">Improve</h3>
        <p className="mt-1 text-xs text-ink-3">
          Corrections go into the training set only. The new version takes one final exam on the same sealed test set v{live?.version} was scored on,
          and goes live only if it beats v{live?.version} and passes every threshold.
        </p>
        {replayMode && (
          <div className="mt-2 rounded border border-border p-3 text-sm">
            {info.recorded_run ? <>
              <p>This server plays recordings. The recorded improve run took v{info.recorded?.live_version_before} with {info.recorded?.corrections} corrections
                to v{info.recorded?.new_version}: {info.recorded?.gate?.passed ? "the gate passed and it deployed" : "the gate rejected it"} ({info.recorded?.gate?.reason}).</p>
              <button className="btn mt-2" onClick={improve} disabled={!!busy}>Replay the improve run</button>
            </> : <p className="text-ink-2">This server plays recordings, and there's no recorded improve run for this specialist. Run the app in live mode to build a new version.</p>}
          </div>
        )}
        {lastResult && labels.length > 0 && !replayMode && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-ink-2">Wrong label for the last input?</span>
            <select className="input w-auto max-w-[240px] py-1 text-sm" value={fix} onChange={(e) => setFix(e.target.value)} aria-label="Correct label">
              <option value="">Pick the right one</option>
              {labels.filter((l) => l !== lastResult.label).map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
            <button className="btn" disabled={!fix || !!busy} onClick={addOne}>Add correction</button>
          </div>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {!held && <button className="btn" onClick={loadHeld} disabled={!!busy || !live}>{busy === "held" ? "Checking held-back records…" : "Check held-back records"}</button>}
          {held && (
            <span className="text-sm text-ink-2">
              v{live?.version} gets {held.n_wrong} of {held.scored.toLocaleString()} held-back records wrong.{" "}
              {held.n_wrong > 0 && !replayMode && <button className="btn ml-1" onClick={addHeld} disabled={!!busy}>Add all {held.n_wrong} as corrections</button>}
            </span>
          )}
        </div>
        {held && <p className="mt-1 text-xs text-ink-3">Source: {held.source}. These stand in for corrections a user would make.</p>}
        {rows.length > 0 && (
          <div className="mt-3">
            <div className="mb-1 flex items-center justify-between text-sm">
              <span>{rows.length.toLocaleString()} correction{rows.length === 1 ? "" : "s"}{fromHeld ? ` (${fromHeld} from held-back records)` : ""}</span>
              <button className="btn-ghost text-xs" onClick={() => remove()} disabled={!!busy}>Clear all</button>
            </div>
            <div className="max-h-48 overflow-auto rounded border border-border">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface-2 text-left text-xs text-ink-2"><tr><th className="px-2 py-1">Input</th><th className="px-2 py-1">Was</th><th className="px-2 py-1">Should be</th><th /></tr></thead>
                <tbody>{rows.slice(0, 300).map((r, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="mono max-w-[220px] truncate px-2 py-1 text-xs" title={r.input}>{r.input}</td>
                    <td className="px-2 py-1 text-xs text-ink-3">{r.predicted_label}</td>
                    <td className="px-2 py-1 text-xs">{r.corrected_label}</td>
                    <td className="px-1"><button className="btn-ghost px-1 text-xs" onClick={() => remove(i)} aria-label="Remove correction">Remove</button></td>
                  </tr>))}</tbody>
              </table>
            </div>
            {!replayMode && <button className="btn-primary mt-2" onClick={improve} disabled={!!busy}>{busy === "improve" ? "Starting…" : `Build v${Math.max(...spec.versions.map((v: any) => v.version)) + 1}`}</button>}
          </div>
        )}
        {error && <p className="mt-2 text-sm text-danger" role="alert">{error}</p>}
      </section>

      <section className="mt-6" aria-label="Version history">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-medium">Version history</h3>
          {canRollback && <button className="btn" onClick={rollback} disabled={!!busy}>{busy === "rollback" ? "Rolling back…" : "Roll back"}</button>}
        </div>
        <ol className="divide-y divide-border rounded border border-border">
          {spec.versions.map((v: any) => {
            const split = cascadeSplit(v);
            return (
              <li key={v.version} className="px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">v{v.version}</span>
                  {v.live && <span className="rounded-full px-2 text-xs text-white" style={{ background: spec.color }}>live</span>}
                  <span className={`text-xs ${v.gate_result === "rejected" ? "text-danger" : "text-ink-3"}`}>
                    {v.gate_result === "deployed" ? (v.live ? "deployed" : "deployed earlier") : v.gate_result === "rejected" ? "rejected by the gate" : "rolled back"}
                  </span>
                  <span className="ml-auto tabular-nums text-ink-2">{v.sealed_metrics?.primary_metric ?? "score"} {v.sealed_metrics?.primary?.toFixed(3)}</span>
                </div>
                <div className="mt-0.5 text-xs text-ink-3">
                  {new Date(v.created * 1000).toLocaleString()} · {split ? `${split} · ` : ""}<span className="mono">{v.candidate}</span>
                </div>
                <div className="mt-0.5 text-xs text-ink-2">{v.reason}</div>
              </li>
            );
          })}
        </ol>
      </section>
    </>
  );
}
