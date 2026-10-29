/** API origin: empty = same origin (local dev, `make replay`); on Vercel the Nebius endpoint URL. */
export const API_BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "").replace(/\/$/, "");
export const apiUrl = (path: string) => (path.startsWith("http") ? path : `${API_BASE}${path}`);

/** Supabase access token for `Authorization: Bearer`, set by lib/auth.ts once a user signs in. */
let tokenGetter: () => Promise<string | null> = async () => null;
export const setTokenGetter = (fn: () => Promise<string | null>) => { tokenGetter = fn; };

async function authHeaders(extra?: Record<string, string>): Promise<Record<string, string>> {
  const t = await tokenGetter();
  return { ...(extra ?? {}), ...(t ? { Authorization: `Bearer ${t}` } : {}) };
}

export async function getJSON<T = any>(url: string): Promise<T> {
  const r = await fetch(apiUrl(url), { headers: await authHeaders() });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function postJSON<T = any>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(apiUrl(url), { method: "POST", headers: await authHeaders({ "Content-Type": "application/json" }),
                                       body: JSON.stringify(body ?? {}) });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function deleteJSON<T = any>(url: string): Promise<T> {
  const r = await fetch(apiUrl(url), { method: "DELETE", headers: await authHeaders() });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function postForm<T = any>(url: string, form: FormData): Promise<T> {
  const r = await fetch(apiUrl(url), { method: "POST", body: form, headers: await authHeaders() });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

/** Fetch a text file (run files, report Markdown); null when it isn't there. */
export async function getText(url: string): Promise<string | null> {
  const r = await fetch(apiUrl(url), { headers: await authHeaders() });
  return r.ok ? r.text() : null;
}

/** Download a file through fetch, so the auth header goes along. */
export async function download(url: string, filename: string) {
  const r = await fetch(apiUrl(url), { headers: await authHeaders() });
  if (!r.ok) throw new Error(await errorText(r));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function errorText(r: Response) {
  try {
    const j = await r.json();
    return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
  } catch {
    return r.status === 401 ? "Sign in to use this." : `Request failed (${r.status})`;
  }
}

/** Subscribe to a run's server-sent events; returns a close function. EventSource can't send headers, so the
 * token goes in `?access_token=`. On a dropped connection it reconnects with `?after=<events seen>` (the stream
 * replays from the first event otherwise). */
export function subscribe(url: string, onEvent: (data: any) => void, onDone?: () => void): () => void {
  let seen = 0, closed = false, es: EventSource | null = null, retry: number | undefined;
  const open = async () => {
    const t = await tokenGetter();
    if (closed) return;
    const u = new URL(apiUrl(url), window.location.href);
    if (seen) u.searchParams.set("after", String(seen));
    if (t) u.searchParams.set("access_token", t);
    es = new EventSource(u.toString());
    es.onmessage = (m) => {
      const data = JSON.parse(m.data);
      seen += 1;
      onEvent(data);
      if (data.kind === "done") { closed = true; es?.close(); onDone?.(); }
    };
    es.onerror = () => {
      es?.close();
      if (!closed) retry = window.setTimeout(open, 1500);
    };
  };
  open();
  return () => { closed = true; window.clearTimeout(retry); es?.close(); };
}

/** POST a chat and read the SSE response token by token. */
export async function streamChat(messages: { role: string; content: string }[], onDelta: (t: string) => void,
                                 signal: AbortSignal): Promise<{ error?: string }> {
  const r = await fetch(apiUrl("/api/chat"), { method: "POST", headers: await authHeaders({ "Content-Type": "application/json" }),
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

/** Dollars: "$19,362.77", "$0.0009", "$2.3e-10" never; tiny amounts as "$0.00000023". */
export const fmtUsd = (x: number | null | undefined, digits = 2) => {
  if (x == null || Number.isNaN(x)) return "n/a";
  if (x === 0) return "$0";
  if (Math.abs(x) >= 0.01) return `$${x.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
  const sig = x.toPrecision(2);
  return `$${Number(sig).toFixed(Math.min(12, Math.max(2, -Math.floor(Math.log10(Math.abs(x))) + 1)))}`;
};
export const fmtMs = (x: number | null | undefined) => (x == null ? "n/a" : x < 1 ? `${x.toFixed(2)} ms` : x < 100 ? `${x.toFixed(1)} ms` : x < 10000 ? `${Math.round(x)} ms` : `${(x / 1000).toFixed(1)} s`);
export const fmtInt = (n: number | null | undefined) => (n == null ? "n/a" : n >= 1e6 ? `${+(n / 1e6).toFixed(1)} million` : n.toLocaleString());
export const uid = () => Math.random().toString(36).slice(2, 10);
