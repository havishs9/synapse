import type { Chat, SpecialistSummary } from "../lib/types";

type Props = {
  chats: Chat[]; activeChat: string; specialists: SpecialistSummary[]; activeSpecialist?: string;
  onNewChat: () => void; onOpenChat: (id: string) => void; onOpenSpecialist: (sid: string) => void;
  theme: "light" | "dark"; onToggleTheme: () => void; onClose?: () => void;
};

export function Sidebar(p: Props) {
  return (
    <nav className="flex h-full w-[240px] shrink-0 flex-col border-r border-border bg-surface-2" aria-label="Sidebar">
      <div className="flex items-center justify-between px-3 pb-2 pt-3">
        <span className="text-md font-semibold">Synapse</span>
        {p.onClose && <button className="btn-ghost" onClick={p.onClose} aria-label="Close sidebar">Close</button>}
      </div>
      <div className="px-3"><button className="btn w-full justify-start" onClick={p.onNewChat}>New chat</button></div>
      <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-2">
        <div className="px-2 pb-1 text-xs text-ink-3">Recent chats</div>
        {p.chats.length === 0 && <div className="px-2 text-sm text-ink-3">No chats yet</div>}
        {p.chats.map((c) => (
          <button key={c.id} onClick={() => p.onOpenChat(c.id)}
            className={`block w-full truncate rounded px-2 py-1.5 text-left text-sm ${c.id === p.activeChat ? "bg-surface text-ink" : "text-ink-2 hover:bg-surface"}`}>
            {c.title}
          </button>
        ))}
        <div className="mt-4 px-2 pb-1 text-xs text-ink-3">Specialists</div>
        {p.specialists.length === 0 && <div className="px-2 text-sm text-ink-3">None yet</div>}
        {p.specialists.map((s) => (
          <button key={s.specialist_id} onClick={() => p.onOpenSpecialist(s.specialist_id)}
            className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm ${s.specialist_id === p.activeSpecialist ? "bg-surface text-ink" : "text-ink-2 hover:bg-surface"}`}>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: s.color }} aria-hidden />
            <span className="truncate">{s.display_name}</span>
            <span className="ml-auto text-xs text-ink-3">{s.live_version ? `v${s.live_version}` : "not live"}</span>
          </button>
        ))}
      </div>
      <div className="border-t border-border px-3 py-2">
        <button className="btn-ghost w-full justify-start" onClick={p.onToggleTheme}>
          {p.theme === "dark" ? "Light mode" : "Dark mode"}
        </button>
      </div>
    </nav>
  );
}
