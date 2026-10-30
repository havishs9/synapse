import { useEffect, useState } from "react";
import { Markdown } from "./Markdown";
import { download, getText } from "../lib/api";

export function ReportDrawer({ spec, onClose }: { spec: any; onClose: () => void }) {
  const [version, setVersion] = useState<number>((spec.live ?? spec.versions[0])?.version);
  const v = spec.versions.find((x: any) => x.version === version);
  const [md, setMd] = useState<string | null>("");
  const [err, setErr] = useState("");
  useEffect(() => {
    setMd("");
    if (v) getText(`/api/runs/${v.run_id}/report?fmt=md`).then(setMd);
  }, [v?.run_id]);  // eslint-disable-line
  const get = (fmt: "json" | "md") => download(`/api/runs/${v.run_id}/report?fmt=${fmt}`, `${spec.specialist_id}-v${v.version}-report.${fmt}`)
    .catch((e) => setErr(e.message));
  return (
    <div className="absolute inset-0 z-20 flex justify-end bg-black/20" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-label="Report card" className="h-full w-full max-w-[680px] overflow-y-auto border-l border-border bg-surface p-5"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold">Report card</h2>
            {spec.versions.length > 1 && (
              <select className="input w-auto py-1 text-sm" value={version} onChange={(e) => setVersion(Number(e.target.value))} aria-label="Version">
                {spec.versions.map((x: any) => <option key={x.version} value={x.version}>v{x.version}{x.live ? " (live)" : x.gate_result === "rejected" ? " (rejected)" : ""}</option>)}
              </select>
            )}
          </div>
          <div className="flex gap-2">
            {md && <button className="btn" onClick={() => get("json")}>Download JSON</button>}
            {md && <button className="btn" onClick={() => get("md")}>Download Markdown</button>}
            <button className="btn" onClick={onClose} autoFocus>Close</button>
          </div>
        </div>
        {err && <p className="mb-2 text-sm text-danger" role="alert">{err}</p>}
        {md === null
          ? <p className="text-sm text-ink-2">v{v?.version}'s build run ({v?.run_id}) isn't stored on this server, so its report card can't be shown. Its sealed-test score is in the version history.</p>
          : <Markdown text={md || "Loading…"} />}
      </aside>
    </div>
  );
}
