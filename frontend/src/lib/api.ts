export async function getJSON<T = any>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function postJSON<T = any>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function postForm<T = any>(url: string, form: FormData): Promise<T> {
  const r = await fetch(url, { method: "POST", body: form });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

async function errorText(r: Response) {
  try {
    const j = await r.json();
    return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
  } catch {
    return `Request failed (${r.status})`;
  }
}

/** Subscribe to a server-sent event stream; returns a close function. */
export function subscribe(url: string, onEvent: (data: any) => void, onDone?: () => void): () => void {
  const es = new EventSource(url);
  es.onmessage = (m) => {
    const data = JSON.parse(m.data);
    onEvent(data);
    if (data.kind === "done") { es.close(); onDone?.(); }
  };
  es.onerror = () => { if (es.readyState === EventSource.CLOSED) onDone?.(); };
  return () => es.close();
}

/** POST a chat and read the SSE response token by token. */
export async function streamChat(messages: { role: string; content: string }[], onDelta: (t: string) => void,
                                 signal: AbortSignal): Promise<{ error?: string }> {
  const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
                                       body: JSON.stringify({ messages }), signal });
  if (!r.ok || !r.body) return { error: await errorText(r) };
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split(/\r?\n\r?\n/);
    buf = parts.pop() ?? "";
    for (const p of parts) {
      const line = p.split(/\r?\n/).find((l) => l.startsWith("data:"));
      if (!line) continue;
      const d = JSON.parse(line.slice(5).trim());
      if (d.error) return { error: d.error };
      if (d.delta) onDelta(d.delta);
    }
  }
  return {};
}

export const fmtUsd = (x: number | null | undefined, digits = 2) =>
  x == null ? "n/a" : x < 0.01 && x > 0 ? `$${x.toPrecision(2)}` : `$${x.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
export const fmtMs = (x: number | null | undefined) => (x == null ? "n/a" : x < 1 ? `${x.toFixed(2)} ms` : x < 100 ? `${x.toFixed(1)} ms` : `${Math.round(x)} ms`);
export const uid = () => Math.random().toString(36).slice(2, 10);
