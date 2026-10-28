import { useEffect, useRef, useState } from "react";
import type { RunEvent } from "../lib/types";
import { fmtUsd } from "../lib/api";

export function NarrationFeed({ runId, events, t0 }: { runId: string; events: RunEvent[]; t0: number }) {
  const [open, setOpen] = useState<number | null>(null);
  const [file, setFile] = useState<string>("");
  const end = useRef<HTMLDivElement>(null);
  const lines = events.map((e, i) => ({ e, i })).filter(({ e }) => e.message);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [lines.length]);

  const toggle = async (i: number, ref?: string | null) => {
    if (open === i) { setOpen(null); return; }
    setOpen(i); setFile("");
    if (ref) {
      const r = await fetch(`/api/runs/${runId}/files/${ref}`);
      const t = await r.text();
      try { setFile(JSON.stringify(JSON.parse(t), null, 2).slice(0, 20000)); } catch { setFile(t.slice(0, 20000)); }
    }
  };

  return (
    <div className="max-h-[320px] overflow-y-auto pr-1" aria-live="polite">
      {lines.map(({ e, i }) => (
        <div key={i} className="border-b border-border last:border-0">
          <button className="flex w-full items-baseline gap-2 py-1.5 text-left text-sm hover:bg-surface-2" onClick={() => toggle(i, e.data_ref)}
            aria-expanded={open === i}>
            <span className="w-[68px] shrink-0 text-xs text-ink-3">{e.agent}</span>
            <span className={`min-w-0 flex-1 ${e.kind === "error" ? "text-danger" : ""}`}>{e.message}</span>
            <span className="shrink-0 text-xs tabular-nums text-ink-3">{Math.round(e.ts - t0)}s · {fmtUsd(e.spend_usd, 3)}</span>
          </button>
          {open === i && (
            <pre className="mono mb-2 max-h-64 overflow-auto rounded bg-surface-2 p-2 text-xs">
              {e.data_ref ? (file || "Loading…") : JSON.stringify(e, null, 2)}
            </pre>
          )}
        </div>
      ))}
      <div ref={end} />
    </div>
  );
}
