import { useEffect, useRef, useState } from "react";
import type { Msg } from "../lib/types";
import { Markdown } from "./Markdown";

export const EXAMPLES = [
  { label: "Sort purchase records into spending categories", task: "procurement" },
  { label: "Flag anomalies in system logs", task: "hdfs_logs" },
  { label: "Route support tickets to the right team", task: null },
];

type Props = {
  messages: Msg[]; streaming: boolean; onSend: (text: string, file?: File) => void; onStop: () => void;
  onRetry: () => void; renderSpecial: (m: Msg) => React.ReactNode; onExample: (label: string) => void;
};

export function MainChat(p: Props) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [p.messages]);

  const send = () => {
    if (!text.trim() || p.streaming) return;
    p.onSend(text.trim(), file ?? undefined);
    setText(""); setFile(null);
  };

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col"
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) setFile(f); }}>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[720px] px-4 py-6">
          {p.messages.length === 0 && (
            <div className="mt-[18vh] text-center">
              <h1 className="text-xl font-semibold">Describe a repetitive task</h1>
              <p className="mx-auto mt-2 max-w-md text-ink-2">
                Synapse builds a small specialist for it, tests it against Nemotron, and ships the cheapest one that meets your bar.
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {EXAMPLES.map((e) => (
                  <button key={e.label} className="btn" onClick={() => p.onExample(e.label)}>{e.label}</button>
                ))}
              </div>
            </div>
          )}
          {p.messages.map((m, i) => (
            <div key={m.id} className={`group mb-5 ${m.role === "user" ? "flex justify-end" : ""}`}>
              {m.role === "user" ? (
                <div className="max-w-[85%] rounded bg-surface-2 px-3 py-2">
                  {m.attachment && <div className="chip mb-1">{m.attachment.name} · {m.attachment.rows.toLocaleString()} rows</div>}
                  <div className="whitespace-pre-wrap">{m.content}</div>
                </div>
              ) : m.kind && m.kind !== "text" && m.kind !== "error" ? p.renderSpecial(m) : (
                <div>
                  {m.kind === "error" ? <p className="text-danger">{m.content}</p> : <Markdown text={m.content || "…"} />}
                  {!p.streaming && m.content && (
                    <div className="mt-1 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      <button className="btn-ghost text-xs" onClick={() => navigator.clipboard.writeText(m.content)}>Copy</button>
                      {i === p.messages.length - 1 && <button className="btn-ghost text-xs" onClick={p.onRetry}>Retry</button>}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          <div ref={end} />
        </div>
      </div>
      <div className="mx-auto w-full max-w-[720px] px-4 pb-4">
        {drag && <div className="mb-2 rounded border border-dashed border-border p-3 text-center text-sm text-ink-2">Drop a CSV, JSONL or log file</div>}
        <div className="card flex flex-col gap-2 p-2">
          {file && (
            <div className="flex items-center gap-2 px-1">
              <span className="chip">{file.name} · {(file.size / 1024).toFixed(0)} KB</span>
              <button className="btn-ghost text-xs" onClick={() => setFile(null)}>Remove</button>
            </div>
          )}
          <textarea className="min-h-[44px] w-full resize-none bg-transparent px-2 py-1 outline-none placeholder:text-ink-3"
            rows={Math.min(8, Math.max(1, text.split("\n").length))} placeholder="Message Synapse (Ctrl+Enter to send)"
            value={text} onChange={(e) => setText(e.target.value)} aria-label="Message"
            onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); send(); } }} />
          <div className="flex items-center justify-between">
            <button className="btn-ghost" onClick={() => fileInput.current?.click()}>Attach</button>
            <input ref={fileInput} type="file" accept=".csv,.jsonl,.txt,.log" className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            {p.streaming ? <button className="btn" onClick={p.onStop}>Stop</button>
              : <button className="btn-primary" onClick={send} disabled={!text.trim()}>Send</button>}
          </div>
        </div>
      </div>
    </div>
  );
}
