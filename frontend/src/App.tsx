import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, postJSON, streamChat, uid } from "./lib/api";
import type { Chat, Msg, Pane, SpecialistSummary } from "./lib/types";
import { Sidebar } from "./components/Sidebar";
import { EXAMPLES, MainChat } from "./components/MainChat";
import { TrainingView } from "./components/TrainingView";
import { SpecialistPanel } from "./components/SpecialistPanel";
import { TaskCardMessage } from "./components/TaskCard";
import { QuickSwitcher } from "./components/QuickSwitcher";
import { useIntake } from "./lib/useIntake";

const load = <T,>(k: string, d: T): T => { try { return JSON.parse(localStorage.getItem(k) ?? "") as T; } catch { return d; } };

export function App() {
  const [chats, setChats] = useState<Chat[]>(() => load("synapse.chats", []));
  const [active, setActive] = useState<string>(() => load("synapse.active", ""));
  const [pane, setPane] = useState<Pane>(null);
  const [specialists, setSpecialists] = useState<SpecialistSummary[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => load("synapse.theme", matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth >= 768);
  const [tab, setTab] = useState<"chat" | "pane">("chat");
  const [paneWidth, setPaneWidth] = useState(() => load("synapse.paneWidth", 560));
  const [switcher, setSwitcher] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => { localStorage.setItem("synapse.chats", JSON.stringify(chats.slice(0, 50))); }, [chats]);
  useEffect(() => { localStorage.setItem("synapse.active", JSON.stringify(active)); }, [active]);
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("synapse.theme", JSON.stringify(theme)); }, [theme]);
  const refreshSpecialists = useCallback(() => { getJSON<SpecialistSummary[]>("/api/specialists").then(setSpecialists).catch(() => {}); }, []);
  useEffect(refreshSpecialists, [refreshSpecialists]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setSwitcher((s) => !s); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const chat = chats.find((c) => c.id === active);
  const messages = chat?.messages ?? [];
  const update = (fn: (m: Msg[]) => Msg[], title?: string) => {
    setChats((cs) => {
      let id = active, list = cs;
      if (!cs.find((c) => c.id === id)) {
        id = uid(); setActive(id);
        list = [{ id, title: title ?? "New chat", messages: [], updated: Date.now() }, ...cs];
      }
      return list.map((c) => (c.id === id ? { ...c, messages: fn(c.messages), updated: Date.now(), title: c.title === "New chat" && title ? title : c.title } : c))
        .sort((a, b) => b.updated - a.updated);
    });
  };
  const push = (m: Omit<Msg, "id">, title?: string) => update((ms) => [...ms, { ...m, id: uid() }], title);
  const patchLast = (fn: (m: Msg) => Msg) => update((ms) => ms.map((m, i) => (i === ms.length - 1 ? fn(m) : m)));

  const intake = useIntake({ push, patchLast, messages });

  const askModel = async (history: Msg[]) => {
    setStreaming(true);
    abort.current = new AbortController();
    push({ role: "assistant", content: "", kind: "text" });
    const msgs = history.filter((m) => !m.kind || m.kind === "text").map((m) => ({ role: m.role, content: m.content }));
    try {
      const res = await streamChat(msgs, (d) => patchLast((m) => ({ ...m, content: m.content + d })), abort.current.signal);
      if (res.error) patchLast((m) => ({ ...m, kind: "error", content: res.error! }));
    } catch (e: any) {
      if (e.name !== "AbortError") patchLast((m) => ({ ...m, kind: "error", content: "Connection lost. Retry to try again." }));
    }
    setStreaming(false);
  };

  const send = async (text: string, file?: File) => {
    const title = text.slice(0, 48);
    let attachment;
    if (file) {
      const body = await file.text();
      attachment = { name: file.name, rows: body.split("\n").filter((l) => l.trim()).length };
    }
    push({ role: "user", content: text, attachment }, title);
    if (await intake.handle(text, file)) return;
    askModel([...messages, { id: "", role: "user", content: text }]);
  };

  const onExample = (label: string) => send(label);
  const startBuild = async (card: any) => {
    const r = await postJSON("/api/builds", { task_card: card });
    push({ role: "assistant", content: "", kind: "build", runId: r.run_id, card });
    setPane({ kind: "build", runId: r.run_id, replay: r.replay, taskId: card.task_id });
    setTab("pane");
  };

  const renderSpecial = (m: Msg) => {
    if (m.kind === "taskcard" || m.kind === "questions") return <TaskCardMessage msg={m} onBuild={startBuild} intake={intake} />;
    if (m.kind === "build") return (
      <button className="btn" onClick={() => { setPane({ kind: "build", runId: m.runId!, replay: false, taskId: m.card?.task_id }); setTab("pane"); }}>
        Show build progress for {m.card?.task_name}
      </button>);
    return null;
  };

  const startDrag = (e: React.MouseEvent) => {
    const x0 = e.clientX, w0 = paneWidth;
    const move = (ev: MouseEvent) => setPaneWidth(Math.min(Math.max(w0 - (ev.clientX - x0), 380), window.innerWidth - 420));
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); localStorage.setItem("synapse.paneWidth", JSON.stringify(paneWidth)); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };

  const paneEl = pane && (
    <div className="flex h-full min-w-0 flex-col bg-surface">
      <div className="flex justify-end border-b border-border px-2 py-1">
        <button className="btn-ghost text-xs" onClick={() => setPane(null)} aria-label="Close pane">Close</button>
      </div>
      <div className="min-h-0 flex-1">
        {pane.kind === "build" ? (
          <TrainingView key={pane.runId} runId={pane.runId} replay={pane.replay}
            card={chat?.messages.find((m) => m.runId === pane.runId)?.card}
            onFinished={(r) => { refreshSpecialists(); if (r?.specialist_id) setPane({ kind: "specialist", sid: r.specialist_id }); }} />
        ) : <SpecialistPanel sid={pane.sid} onChanged={refreshSpecialists} />}
      </div>
    </div>
  );

  return (
    <div className="flex h-full">
      {sidebarOpen && (
        <div className="fixed inset-0 z-30 flex md:static md:z-auto">
          <Sidebar chats={chats} activeChat={active} specialists={specialists}
            activeSpecialist={pane?.kind === "specialist" ? pane.sid : undefined}
            onNewChat={() => { setActive(""); setPane(null); setTab("chat"); }}
            onOpenChat={(id) => { setActive(id); setTab("chat"); }}
            onOpenSpecialist={(sid) => { setPane({ kind: "specialist", sid }); setTab("pane"); if (window.innerWidth < 768) setSidebarOpen(false); }}
            theme={theme} onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
            onClose={window.innerWidth < 768 ? () => setSidebarOpen(false) : undefined} />
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
            <MainChat messages={messages} streaming={streaming} onSend={send} onStop={() => abort.current?.abort()}
              onRetry={() => { const hist = messages.slice(0, -1); update(() => hist); askModel(hist); }}
              renderSpecial={renderSpecial} onExample={onExample} />
          </div>
          {pane && (
            <>
              <div className="hidden w-1 cursor-col-resize bg-border hover:bg-focus lg:block" onMouseDown={startDrag} role="separator" aria-orientation="vertical" />
              <div className={`min-w-0 ${tab === "pane" ? "flex flex-1" : "hidden"} lg:flex lg:flex-none`} style={{ width: window.innerWidth >= 1024 ? paneWidth : undefined }}>
                <div className="w-full">{paneEl}</div>
              </div>
            </>
          )}
        </div>
      </main>
      {switcher && <QuickSwitcher chats={chats} specialists={specialists} onClose={() => setSwitcher(false)}
        onChat={(id) => { setActive(id); setSwitcher(false); setTab("chat"); }}
        onSpecialist={(sid) => { setPane({ kind: "specialist", sid }); setSwitcher(false); setTab("pane"); }} />}
    </div>
  );
}

export { EXAMPLES };
