import { useEffect, useState } from "react";
import { Markdown } from "./Markdown";

export function ReportDrawer({ spec, onClose }: { spec: any; onClose: () => void }) {
  const v = spec.live ?? spec.versions[0];
  const [md, setMd] = useState("");
  useEffect(() => {
    if (v) fetch(`/api/runs/${v.run_id}/report?fmt=md`).then((r) => (r.ok ? r.text() : "Report not available.")).then(setMd);
  }, [v?.run_id]);
  return (
    <div className="absolute inset-0 z-20 flex justify-end bg-black/20" onClick={onClose}>
      <aside role="dialog" aria-label="Report card" className="h-full w-full max-w-[640px] overflow-y-auto border-l border-border bg-surface p-5"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Report card</h2>
          <div className="flex gap-2">
            {v && <a className="btn" href={`/api/runs/${v.run_id}/report?fmt=json`}>Download JSON</a>}
            {v && <a className="btn" href={`/api/runs/${v.run_id}/report?fmt=md`}>Download Markdown</a>}
            <button className="btn" onClick={onClose} autoFocus>Close</button>
          </div>
        </div>
        <Markdown text={md || "Loading…"} />
      </aside>
    </div>
  );
}
