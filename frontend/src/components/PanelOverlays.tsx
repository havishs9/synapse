import { useEffect, useRef, useState } from "react";
import { API_BASE, fmtInt, fmtMs, fmtUsd, postJSON } from "../lib/api";
import { stageName } from "./SpecialistPanel";

function Dialog({ label, onClose, wide, children }: { label: string; onClose: () => void; wide?: boolean; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.querySelector<HTMLElement>("textarea, button")?.focus(); }, []);
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/30 px-4 py-[6vh]" onClick={onClose}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={label} onClick={(e) => e.stopPropagation()}
        className={`card w-full ${wide ? "max-w-[880px]" : "max-w-[640px]"} p-5`}>
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">{label}</h2>
          <button className="btn-ghost" onClick={onClose}>Close</button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Compare mode (spec 01 §2.6): the same input to Nemotron Ultra zero-shot and the specialist, side by side. */
export function CompareDialog({ spec, sid, initial, onClose }: { spec: any; sid: string; initial: string; onClose: () => void }) {
  const [input, setInput] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [res, setRes] = useState<any>(null);
  const isLog = spec.live?.bundle?.input_type === "log_window";
  const go = async () => {
    setBusy(true); setError(""); setRes(null);
    try { setRes(await postJSON(`/api/specialists/${sid}/compare`, { input })); } catch (e: any) { setError(e.message); }
    setBusy(false);
  };
  const s = res?.specialist, n = res?.nemotron, p = res?.projection;
  const speed = s && n?.latency_ms && s.latency_ms ? n.latency_ms / s.latency_ms : null;
  return (
    <Dialog label="Compare with Nemotron" onClose={onClose} wide>
      <label className="mb-1 block text-sm font-medium" htmlFor="cmp-input">Same input to both</label>
      <textarea id="cmp-input" className="input mono text-sm" rows={isLog ? 8 : 2} value={input} onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") go(); }} />
      <div className="mt-2 flex items-center gap-3">
        <button className="btn-primary" onClick={go} disabled={!input.trim() || busy}>{busy ? "Asking both…" : "Compare"}</button>
        <span className="text-xs text-ink-3">Both calls run at the same time; latency and cost are measured on this call.</span>
      </div>
      {error && <p className="mt-3 text-sm text-danger" role="alert">{error}</p>}
      {res && (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <Side title={`${n.model ?? "Nemotron Ultra"} (zero-shot)`} accent="var(--ink-3)" r={n}
              note={n.cached ? "Cached answer: Nemotron didn't respond just now; this is its earlier answer to the same prompt" : undefined}
              costNote={n.cost_method} />
            <Side title={s.name} accent={spec.color} r={s}
              note={s.answered_by ? `Answered by ${stageName(s.answered_by)} (${s.answered_by})${s.escalated ? " after the cheaper stage escalated" : ""}${s.escalation_unavailable ? "; the escalation stage didn't answer in time" : ""}` : undefined}
              costNote={s.cost_method} />
          </div>
          <p className="mt-3 text-sm text-ink-2">
            {res.agree ? "Same label." : "Different labels."}
            {speed && speed > 1 ? ` The specialist answered ${speed >= 10 ? Math.round(speed).toLocaleString() : speed.toFixed(1)}× faster on this call.` : ""}
          </p>
          {p && (
            <div className="mt-3 rounded border border-border p-3" title={p.method}>
              <div className="text-sm">
                At {fmtInt(p.monthly_volume)} records a month: <span className="font-medium">Nemotron {fmtUsd(p.nemotron_yearly_usd, 0)}/year</span> vs{" "}
                <span className="font-medium" style={{ borderBottom: `2px solid ${spec.color}` }}>specialist {fmtUsd(p.specialist_yearly_usd, p.specialist_yearly_usd < 10 ? 2 : 0)}/year</span>
              </div>
              <details className="mt-1 text-xs text-ink-3">
                <summary className="cursor-pointer">How this is calculated</summary>
                <p className="mt-1">{p.method}</p>
                <p className="mt-1">Per 1M predictions: Nemotron {fmtUsd(p.nemotron_per_1m_usd)}, specialist {fmtUsd(p.specialist_per_1m_usd)}. Volume from the {p.volume_source}.</p>
              </details>
            </div>
          )}
        </>
      )}
    </Dialog>
  );
}

/** Per-call costs span ten orders of magnitude; below a hundredth of a cent, show the cost per 1M calls instead. */
const callCost = (x: number | null | undefined) =>
  x == null ? "n/a" : x >= 0.0001 ? fmtUsd(x, 4) : `${fmtUsd(x * 1e6)} per 1M calls`;

function Side({ title, accent, r, note, costNote }: { title: string; accent: string; r: any; note?: string; costNote?: string }) {
  if (r?.error) return <div className="rounded border border-border p-3 text-sm text-danger" style={{ borderTop: `3px solid ${accent}` }}>{r.error}</div>;
  return (
    <div className="rounded border border-border p-3" style={{ borderTop: `3px solid ${accent}` }}>
      <div className="text-xs text-ink-3">{title}</div>
      <div className="mt-1 text-md font-semibold">{r.label ?? "No answer"}</div>
      {r.confidence != null && <div className="text-xs text-ink-3">{Math.round(r.confidence * 100)}% confidence</div>}
      {r.reason && <p className="mt-2 text-sm text-ink-2">{r.reason}</p>}
      <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
        <div><dt className="text-xs text-ink-3">Latency</dt><dd className="tabular-nums">{fmtMs(r.latency_ms)}{r.cached ? " (cached call)" : ""}</dd></div>
        <div title={costNote}><dt className="text-xs text-ink-3">Cost of this call</dt><dd className="tabular-nums">{callCost(r.cost_usd)}</dd></div>
      </dl>
      {note && <p className="mt-2 text-xs text-ink-3">{note}</p>}
    </div>
  );
}

/** "Use via API" (spec 01 §2.8): the specialist's own URL, a reveal-once key, and copy-paste snippets. */
export function UseDialog({ spec, sid, onClose, onChanged }: { spec: any; sid: string; onClose: () => void; onChanged: () => void }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lang, setLang] = useState<"curl" | "python">("curl");
  const base = (spec.api_base || API_BASE || window.location.origin).replace(/\/$/, "");
  const live = spec.live?.version;
  const url = `${base}/v1/specialists/${sid}/predict`;
  const pinned = `${base}/v1/specialists/${sid}/v${live}/predict`;
  const sample = spec.live?.bundle?.example_input ?? (spec.live?.bundle?.input_type === "log_window" ? "<all log lines for one block>" : "PURCHASE OF LAPTOP COMPUTERS");
  const shown = key || "$SYNAPSE_KEY";
  const json = JSON.stringify({ input: sample });
  const snippets = {
    curl: `curl -s ${url} \\\n  -H "Authorization: Bearer ${shown}" \\\n  -H "Content-Type: application/json" \\\n  -d '${json.replace(/'/g, "'\\''")}'`,
    python: `import requests\n\nr = requests.post(\n    "${url}",\n    headers={"Authorization": "Bearer ${key || "<your key>"}"},\n    json=${json},\n    timeout=30,\n)\nprint(r.json())  # {"label": ..., "confidence": ..., "reason": ..., "version": ${live}}`,
  };
  const regenerate = async () => {
    setBusy(true); setError("");
    try { setKey((await postJSON(`/api/specialists/${sid}/keys`)).api_key); onChanged(); } catch (e: any) { setError(e.message); }
    setBusy(false);
  };
  const activeKeys = (spec.keys ?? []).filter((k: any) => !k.revoked);
  return (
    <Dialog label={`Use ${spec.display_name}`} onClose={onClose}>
      <p className="text-sm text-ink-2">This specialist has its own API. The live route always serves the live version; the pinned route locks v{live}. Model files stay on the platform.</p>
      <CopyRow label="Live route" value={url} />
      <CopyRow label={`Pinned to v${live}`} value={pinned} />
      <div className="mt-4">
        <div className="text-sm font-medium">API key</div>
        {key ? (
          <>
            <CopyRow label="Your key: copy it now, it won't be shown again" value={key} mono />
          </>
        ) : (
          <p className="mt-1 text-sm text-ink-2">
            {activeKeys.length ? `You have an active key (created ${new Date(activeKeys[0].created * 1000).toLocaleDateString()}). Keys are stored hashed, so it can't be shown again.` : "You don't have a key for this specialist yet."}
          </p>
        )}
        <button className="btn mt-2" onClick={regenerate} disabled={busy}>
          {busy ? "Creating…" : activeKeys.length || key ? "Regenerate key" : "Create API key"}
        </button>
        {(activeKeys.length > 0 || key) && <span className="ml-2 text-xs text-ink-3">Regenerating revokes your earlier key for this specialist.</span>}
        {error && <p className="mt-2 text-sm text-danger" role="alert">{error}</p>}
      </div>
      <div className="mt-4">
        <div className="mb-1 flex gap-1" role="tablist">
          {(["curl", "python"] as const).map((l) => (
            <button key={l} role="tab" aria-selected={lang === l} className={lang === l ? "btn" : "btn-ghost"} onClick={() => setLang(l)}>{l === "curl" ? "curl" : "Python"}</button>
          ))}
        </div>
        <Snippet text={snippets[lang]} />
        <p className="mt-2 text-xs text-ink-3">A key works only for this specialist; another specialist's key gets 403.</p>
      </div>
    </Dialog>
  );
}

function useCopy() {
  const [copied, setCopied] = useState(false);
  return { copied, copy: (t: string) => { navigator.clipboard.writeText(t); setCopied(true); window.setTimeout(() => setCopied(false), 1200); } };
}

function CopyRow({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  const { copied, copy } = useCopy();
  return (
    <div className="mt-3">
      <div className="mb-1 text-xs text-ink-3">{label}</div>
      <div className="flex items-center gap-2 rounded border border-border bg-surface-2 px-2 py-1.5">
        <code className={`${mono ? "mono" : ""} min-w-0 flex-1 break-all text-xs`}>{value}</code>
        <button className="btn-ghost shrink-0 text-xs" onClick={() => copy(value)}>{copied ? "Copied" : label.startsWith("Your key") ? "Copy API key" : "Copy"}</button>
      </div>
    </div>
  );
}

function Snippet({ text }: { text: string }) {
  const { copied, copy } = useCopy();
  return (
    <div className="relative">
      <pre className="mono overflow-x-auto rounded border border-border bg-surface-2 p-3 pr-16 text-xs">{text}</pre>
      <button className="btn-ghost absolute right-1 top-1 text-xs" onClick={() => copy(text)}>{copied ? "Copied" : "Copy"}</button>
    </div>
  );
}
