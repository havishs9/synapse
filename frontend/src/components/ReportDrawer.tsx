import { useEffect, useState } from "react";
import { Markdown } from "./Markdown";
import { download, getText } from "../lib/api";

export function ReportDrawer({ spec, onClose }: { spec: any; onClose: () => void }) {
  const v = spec.live ?? spec.versions[0];
  const [md, setMd] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    if (v) getText(`/api/runs/${v.run_id}/report?fmt=md`).then((t) => setMd(t ?? "Report not available."));
  }, [v?.run_id]);
  const get = (fmt: "json" | "md") => download(`/api/runs/${v.run_id}/report?fmt=${fmt}`, `${spec.specialist_id}-v${v.version}-report.${fmt}`)
    .catch((e) => setErr(e.message));
  return (
    <div className="absolute inset-0 z-20 flex justify-end bg-black/20" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-label="Report card" className="h-full w-full max-w-[680px] overflow-y-auto border-l border-border bg-surface p-5"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">Report card · v{v?.version}</h2>
          <div className="flex gap-2">
            {v && <button className="btn" onClick={() => get("json")}>Download JSON</button>}
            {v && <button className="btn" onClick={() => get("md")}>Download Markdown</button>}
            <button className="btn" onClick={onClose} autoFocus>Close</button>
          </div>
        </div>
        {err && <p className="mb-2 text-sm text-danger" role="alert">{err}</p>}
        <Markdown text={md || "Loading…"} />
      </aside>
    </div>
  );
}
