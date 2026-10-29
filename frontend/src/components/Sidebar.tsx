import { useState } from "react";
import type { Build, Chat, SpecialistSummary } from "../lib/types";
import { fmtUsd } from "../lib/api";

type Props = {
  chats: Chat[]; activeChat: string; specialists: SpecialistSummary[]; activeSpecialist?: string;
  builds: Build[]; activeRun?: string;
  onNewChat: () => void; onOpenChat: (id: string) => void; onOpenSpecialist: (sid: string) => void;
  onOpenBuild: (b: Build) => void; onCancelBuild: (b: Build) => void; onRetryBuild: (b: Build) => void;
  theme: "light" | "dark"; onToggleTheme: () => void; onClose?: () => void;
  email?: string | null; onSignOut?: () => void;
};

const STATUS: Record<Build["status"], string> = { queued: "Queued", running: "Running", done: "Done", failed: "Failed", cancelled: "Cancelled" };

function buildLine(b: Build) {
  if (b.status === "running") return `${b.stage ?? "starting"}${b.round && b.n_rounds ? ` · round ${b.round}/${b.n_rounds}` : ""}`;
  if (b.status === "done" && b.version) return b.deployed ? `v${b.version} deployed` : `v${b.version} not deployed`;
  return STATUS[b.status];
}

export function Sidebar(p: Props) {
  const [allBuilds, setAllBuilds] = useState(false);
  const builds = allBuilds ? p.builds : p.builds.slice(0, 4);
  const item = (active: boolean) => `w-full rounded px-2 py-1.5 text-left text-sm ${active ? "bg-surface text-ink" : "text-ink-2 hover:bg-surface"}`;
  return (
    <nav className="flex h-full w-[260px] shrink-0 flex-col border-r border-border bg-surface-2" aria-label="Sidebar">
      <div className="flex items-center justify-between px-3 pb-2 pt-3">
        <span className="text-md font-semibold">Synapse</span>
        {p.onClose && <button className="btn-ghost" onClick={p.onClose} aria-label="Close sidebar">Close</button>}
      </div>
      <div className="px-3"><button className="btn w-full justify-start" onClick={p.onNewChat}>New chat</button></div>
      <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <div className="px-2 pb-1 text-xs text-ink-3">Recent chats</div>
        {p.chats.length === 0 && <div className="px-2 text-sm text-ink-3">No chats yet</div>}
        {p.chats.map((c) => (
          <button key={c.id} onClick={() => p.onOpenChat(c.id)} className={`block truncate ${item(c.id === p.activeChat)}`}>{c.title}</button>
        ))}

        <div className="mt-4 px-2 pb-1 text-xs text-ink-3">Specialists</div>
        {p.specialists.length === 0 && <div className="px-2 text-sm text-ink-3">None yet</div>}
        {p.specialists.map((s) => (
          <button key={s.specialist_id} onClick={() => p.onOpenSpecialist(s.specialist_id)} className={`flex items-center gap-2 ${item(s.specialist_id === p.activeSpecialist)}`}>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: s.color }} aria-hidden />
            <span className="truncate">{s.display_name}</span>
            <span className="ml-auto text-xs text-ink-3">{s.live_version ? `v${s.live_version}` : "not live"}</span>
          </button>
        ))}

        {p.builds.length > 0 && <>
          <div className="mt-4 px-2 pb-1 text-xs text-ink-3">Builds</div>
          {builds.map((b) => (
            <div key={b.run_id} className={`group rounded ${b.run_id === p.activeRun ? "bg-surface" : "hover:bg-surface"}`}>
              <button className="w-full px-2 pt-1.5 text-left text-sm" onClick={() => p.onOpenBuild(b)}
                aria-label={`${b.kind === "improve" ? "Improve" : "Build"} ${b.task_name}: ${STATUS[b.status]}`}>
                <div className="flex items-center gap-2">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${b.status === "running" || b.status === "queued" ? "bg-focus" : b.status === "done" ? "bg-ok" : "bg-danger"}`} aria-hidden />
                  <span className="truncate text-ink">{b.kind === "improve" ? "Improve " : ""}{b.task_name}</span>
                </div>
                <div className="flex justify-between gap-2 pl-3.5 text-xs text-ink-3">
                  <span className="truncate" title={b.message}>{buildLine(b)}</span>
                  <span className="shrink-0 tabular-nums">{fmtUsd(b.spend_usd, 2)}</span>
                </div>
              </button>
              <div className="flex gap-1 pb-1 pl-5">
                {(b.status === "running" || b.status === "queued") &&
                  <button className="btn-ghost px-1.5 py-0.5 text-xs" onClick={() => p.onCancelBuild(b)}>Cancel</button>}
                {(b.status === "failed" || b.status === "cancelled") &&
                  <button className="btn-ghost px-1.5 py-0.5 text-xs" onClick={() => p.onRetryBuild(b)}>Retry</button>}
              </div>
            </div>
          ))}
          {p.builds.length > 4 && <button className="btn-ghost mt-0.5 text-xs" onClick={() => setAllBuilds((v) => !v)}>
            {allBuilds ? "Show fewer" : `Show all ${p.builds.length}`}</button>}
        </>}
      </div>
      <div className="flex items-center gap-1 border-t border-border px-3 py-2">
        <button className="btn-ghost flex-1 justify-start" onClick={p.onToggleTheme}>{p.theme === "dark" ? "Light mode" : "Dark mode"}</button>
        {p.onSignOut && <button className="btn-ghost" onClick={p.onSignOut} title={p.email ?? undefined}>Sign out</button>}
      </div>
    </nav>
  );
}
