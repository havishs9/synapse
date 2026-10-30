import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, postJSON, streamChat, uid } from "./lib/api";
import type { Build, Chat, Msg, Pane, SpecialistSummary } from "./lib/types";
import { Sidebar } from "./components/Sidebar";
import { EXAMPLES, MainChat } from "./components/MainChat";
import { TrainingView } from "./components/TrainingView";
import { SpecialistPanel } from "./components/SpecialistPanel";
import { AskMessage, DataStepMessage, TaskCardMessage } from "./components/TaskCard";
import { Markdown } from "./components/Markdown";
import { QuickSwitcher } from "./components/QuickSwitcher";
import { SignIn } from "./components/SignIn";
import { useIntake } from "./lib/useIntake";
import { useAuth } from "./lib/auth";

const load = <T,>(k: string, d: T): T => { try { return JSON.parse(localStorage.getItem(k) ?? "") as T; } catch { return d; } };
const save = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage full or blocked */ } };

export function App() {
  const auth = useAuth();
  if (auth.enabled && !auth.ready) return null;            // a saved session is restored before anything shows
  if (auth.enabled && !auth.session) return <SignIn auth={auth} />;
  return <Workspace email={auth.session?.user?.email} onSignOut={auth.enabled ? auth.signOut : undefined} />;
}

function Workspace({ email, onSignOut }: { email?: string | null; onSignOut?: () => void }) {
  const [chats, setChats] = useState<Chat[]>(() => load("synapse.chats", []));
  const [active, setActive] = useState<string>(() => load("synapse.active", ""));
  const [pane, setPane] = useState<Pane>(null);
  const [specialists, setSpecialists] = useState<SpecialistSummary[]>([]);
  const [builds, setBuilds] = useState<Build[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => load("synapse.theme", matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth >= 768);
  const [narrow, setNarrow] = useState(window.innerWidth < 1024);
  const [tab, setTab] = useState<"chat" | "pane">("chat");
  const [paneWidth, setPaneWidth] = useState(() => load("synapse.paneWidth", 600));
  const [switcher, setSwitcher] = useState(false);
  const [notice, setNotice] = useState("");
  const abort = useRef<AbortController | null>(null);
  // The chat that pushes write to. A ref, not `active`, so every message and stream delta of one send lands in
  // the same chat (closures over `active` all saw "" and each created a new chat).
  const activeRef = useRef(active);
  const selectChat = (id: string) => { activeRef.current = id; setActive(id); };

  useEffect(() => { save("synapse.chats", chats.slice(0, 50)); }, [chats]);
  useEffect(() => { save("synapse.active", active); }, [active]);
  useEffect(() => { document.documentElement.dataset.theme = theme; save("synapse.theme", theme); }, [theme]);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 1024);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const refreshSpecialists = useCallback(() => { getJSON<SpecialistSummary[]>("/api/specialists").then(setSpecialists).catch(() => {}); }, []);
  const refreshBuilds = useCallback(() => { getJSON<Build[]>("/api/builds").then(setBuilds).catch(() => {}); }, []);
  useEffect(refreshSpecialists, [refreshSpecialists]);
  const anyRunning = builds.some((b) => b.status === "running" || b.status === "queued");
  useEffect(() => {
    refreshBuilds();
    const t = window.setInterval(refreshBuilds, anyRunning ? 4000 : 30000);
    return () => window.clearInterval(t);
  }, [refreshBuilds, anyRunning]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setSwitcher((s) => !s); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { if (!notice) return; const t = window.setTimeout(() => setNotice(""), 5000); return () => window.clearTimeout(t); }, [notice]);

  const chat = chats.find((c) => c.id === active);
  const messages = chat?.messages ?? [];
  const update = (fn: (m: Msg[]) => Msg[], title?: string) => {
    if (!activeRef.current) selectChat(uid());
    const id = activeRef.current;
    setChats((cs) => {
      const list = cs.find((c) => c.id === id) ? cs : [{ id, title: title ?? "New chat", messages: [], updated: Date.now() }, ...cs];
      return list.map((c) => (c.id === id ? { ...c, messages: fn(c.messages), updated: Date.now(), title: c.title === "New chat" && title ? title : c.title } : c))
        .sort((a, b) => b.updated - a.updated);
    });
  };
  const push = (m: Omit<Msg, "id">, title?: string) => {
    const id = uid();
    update((ms) => [...ms, { ...m, id }], title);
    return id;
  };
  const patchLast = (fn: (m: Msg) => Msg) => update((ms) => ms.map((m, i) => (i === ms.length - 1 ? fn(m) : m)));
  const patch = (id: string, fn: (m: Msg) => Msg) => update((ms) => ms.map((m) => (m.id === id ? fn(m) : m)));

  const remove = (id: string) => update((ms) => ms.filter((m) => m.id !== id));

  const intake = useIntake({ push, patch, remove });

  const askModel = async (history: Msg[]) => {
    setStreaming(true);
    abort.current = new AbortController();
    push({ role: "assistant", content: "", kind: "text" });
    const msgs = history.filter((m) => (!m.kind || m.kind === "text") && m.content).map((m) => ({ role: m.role, content: m.content }));
    try {
      const res = await streamChat(msgs, (d) => patchLast((m) => ({ ...m, content: m.content + d })), abort.current.signal);
      if (res.error) patchLast((m) => ({ ...m, kind: "error", content: res.error! }));
    } catch (e: any) {
      if (e.name !== "AbortError") patchLast((m) => ({ ...m, kind: "error", content: "Connection lost. Retry to try again." }));
    }
    setStreaming(false);
  };

  const send = async (text: string, file?: File) => {
    let attachment;
    if (file) {
      const body = await file.text();
      attachment = { name: file.name, rows: body.split("\n").filter((l) => l.trim()).length };
    }
    push({ role: "user", content: text, attachment }, text.slice(0, 48));
    const waiting = !file && intake.pending(messages);
    if (waiting && await intake.reply(waiting, text)) return;
    if (await intake.handle(text, file)) return;
    askModel([...messages, { id: "", role: "user", content: text }]);
  };

  const openPane = (p: Pane) => { setPane(p); if (p) setTab("pane"); };
  const startBuild = async (msg: Msg) => {
    try {
      const r = await postJSON("/api/builds", { task_card: msg.card });
      patch(msg.id, (m) => ({ ...m, started: r.run_id }));
      openPane({ kind: "build", runId: r.run_id, replay: !!r.replay, taskId: msg.card.task_id, title: msg.card.task_name });
      refreshBuilds();
    } catch (e: any) {
      push({ role: "assistant", kind: "error", content: `Couldn't start the build: ${e.message}` });
    }
  };
  const showBuild = (msg: Msg) => msg.started && openPane({ kind: "build", runId: msg.started, replay: !!msg.replay, taskId: msg.card?.task_id, title: msg.card?.task_name });

  const renderSpecial = (m: Msg) => {
    if (m.kind === "data") return <DataStepMessage msg={m} onSay={(t) => send(t)} />;
    if (m.kind === "ask") return <AskMessage msg={m} />;
    if (m.kind === "taskcard") return (
      <>
        {m.content && <div className="mb-3"><Markdown text={m.content} /></div>}
        <TaskCardMessage msg={m} onBuild={startBuild} onShowBuild={showBuild} intake={intake} />
      </>
    );
    if (m.kind === "questions") return <Markdown text={m.content} />;     // chats saved before intake became a conversation
    return null;
  };

  const buildAction = async (b: Build, action: "cancel" | "retry") => {
    try { await postJSON(`/api/builds/${b.run_id}/${action}`); refreshBuilds(); }
    catch (e: any) { setNotice(e.message); }
  };

  const startDrag = (e: React.MouseEvent) => {
    const x0 = e.clientX, w0 = paneWidth;
    let last = w0;
    const move = (ev: MouseEvent) => { last = Math.min(Math.max(w0 - (ev.clientX - x0), 400), window.innerWidth - 420); setPaneWidth(last); };
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); save("synapse.paneWidth", last); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };

  const card = pane?.kind === "build" ? chats.flatMap((c) => c.messages).find((m) => m.started === pane.runId)?.card : undefined;
  const paneEl = pane && (
    <div className="flex h-full min-w-0 flex-col bg-surface">
      <div className="flex min-h-0 flex-1 flex-col">
        {pane.kind === "build" ? (
          <TrainingView key={pane.runId} runId={pane.runId} replay={pane.replay} card={card} title={pane.title}
            improveOf={pane.improveOf} onClose={() => setPane(null)}
            onFinished={(r) => { refreshSpecialists(); refreshBuilds(); const sid = r?.specialist_id ?? pane.improveOf; if (sid) setPane({ kind: "specialist", sid }); }} />
        ) : <SpecialistPanel key={pane.sid} sid={pane.sid} onClose={() => setPane(null)}
              onChanged={() => { refreshSpecialists(); refreshBuilds(); }}
              onImproveStarted={(runId, replay, name) => openPane({ kind: "build", runId, replay, title: name, improveOf: pane.sid })} />}
      </div>
    </div>
  );

  return (
    <div className="flex h-full">
      {sidebarOpen && (
        <div className="fixed inset-0 z-30 flex md:static md:z-auto">
          <Sidebar chats={chats} activeChat={active} specialists={specialists} builds={builds}
            activeSpecialist={pane?.kind === "specialist" ? pane.sid : undefined}
            activeRun={pane?.kind === "build" ? pane.runId : undefined}
            onNewChat={() => { selectChat(""); setPane(null); setTab("chat"); }}
            onOpenChat={(id) => { selectChat(id); setTab("chat"); if (window.innerWidth < 768) setSidebarOpen(false); }}
            onOpenSpecialist={(sid) => { openPane({ kind: "specialist", sid }); if (window.innerWidth < 768) setSidebarOpen(false); }}
            onOpenBuild={(b) => { openPane({ kind: "build", runId: b.run_id, replay: false, taskId: b.task_id, title: b.task_name, improveOf: b.kind === "improve" ? b.specialist_id ?? undefined : undefined }); if (window.innerWidth < 768) setSidebarOpen(false); }}
            onCancelBuild={(b) => buildAction(b, "cancel")} onRetryBuild={(b) => buildAction(b, "retry")}
            theme={theme} onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
            onClose={window.innerWidth < 768 ? () => setSidebarOpen(false) : undefined} email={email} onSignOut={onSignOut} />
          <div className="flex-1 bg-black/30 md:hidden" onClick={() => setSidebarOpen(false)} />
        </div>
      )}
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2 lg:hidden">
          <button className="btn-ghost" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar">Menu</button>
          {pane && (
            <div role="tablist" className="ml-auto flex gap-1">
              <button role="tab" aria-selected={tab === "chat"} className={tab === "chat" ? "btn" : "btn-ghost"} onClick={() => setTab("chat")}>Chat</button>
              <button role="tab" aria-selected={tab === "pane"} className={tab === "pane" ? "btn" : "btn-ghost"} onClick={() => setTab("pane")}>{pane.kind === "build" ? "Build" : "Specialist"}</button>
            </div>
          )}
        </div>
        <div className="flex min-h-0 flex-1">
          <div className={`min-w-0 flex-1 ${pane && tab === "pane" ? "hidden lg:flex" : "flex"}`}>
            <MainChat messages={messages} streaming={streaming} busy={intake.busy} onSend={send} onStop={() => abort.current?.abort()}
              onRetry={() => { const hist = messages.slice(0, -1); update(() => hist); askModel(hist); }}
              renderSpecial={renderSpecial} onExample={(label) => send(label)} />
          </div>
          {pane && (
            <>
              <div className="hidden w-1 cursor-col-resize bg-border hover:bg-focus lg:block" onMouseDown={startDrag} role="separator" aria-orientation="vertical" aria-label="Resize pane" />
              <div className={`min-w-0 ${tab === "pane" ? "flex flex-1" : "hidden"} lg:flex lg:flex-none`} style={{ width: narrow ? undefined : paneWidth }}>
                <div className="w-full">{paneEl}</div>
              </div>
            </>
          )}
        </div>
      </main>
      {switcher && <QuickSwitcher chats={chats} specialists={specialists} onClose={() => setSwitcher(false)}
        onChat={(id) => { selectChat(id); setSwitcher(false); setTab("chat"); }}
        onSpecialist={(sid) => { openPane({ kind: "specialist", sid }); setSwitcher(false); }} />}
      {notice && <div role="status" className="card fixed bottom-4 left-1/2 z-50 -translate-x-1/2 px-4 py-2 text-sm">{notice}</div>}
    </div>
  );
}

export { EXAMPLES };
