import { useEffect, useRef, useState } from "react";
import type { Chat, SpecialistSummary } from "../lib/types";

export function QuickSwitcher({ chats, specialists, onClose, onChat, onSpecialist }: {
  chats: Chat[]; specialists: SpecialistSummary[]; onClose: () => void; onChat: (id: string) => void; onSpecialist: (sid: string) => void;
}) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { input.current?.focus(); }, []);
  const items = [
    ...specialists.map((s) => ({ key: `s-${s.specialist_id}`, label: s.display_name, hint: "Specialist", color: s.color, go: () => onSpecialist(s.specialist_id) })),
    ...chats.map((c) => ({ key: `c-${c.id}`, label: c.title, hint: "Chat", color: undefined as string | undefined, go: () => onChat(c.id) })),
  ].filter((i) => i.label.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/30 pt-[15vh]" onClick={onClose}>
      <div role="dialog" aria-label="Quick switcher" className="card w-full max-w-md p-2" onClick={(e) => e.stopPropagation()}>
        <input ref={input} className="input" placeholder="Jump to a chat or specialist" value={q}
          onChange={(e) => { setQ(e.target.value); setSel(0); }}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            if (e.key === "ArrowDown") setSel((s) => Math.min(s + 1, items.length - 1));
            if (e.key === "ArrowUp") setSel((s) => Math.max(s - 1, 0));
            if (e.key === "Enter") items[sel]?.go();
          }} />
        <ul className="mt-2 max-h-72 overflow-y-auto">
          {items.map((i, k) => (
            <li key={i.key}>
              <button className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm ${k === sel ? "bg-surface-2" : ""}`} onClick={i.go}>
                {i.color && <span className="h-2.5 w-2.5 rounded-full" style={{ background: i.color }} />}
                <span className="truncate">{i.label}</span><span className="ml-auto text-xs text-ink-3">{i.hint}</span>
              </button>
            </li>
          ))}
          {items.length === 0 && <li className="px-2 py-1.5 text-sm text-ink-3">No matches</li>}
        </ul>
      </div>
    </div>
  );
}
