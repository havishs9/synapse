import { useState } from "react";
import type { DataOption, DataStep, Msg } from "../lib/types";
import type { Intake } from "../lib/useIntake";
import { fmtInt } from "../lib/api";
import { Markdown } from "./Markdown";

/** Quick replies under an intake message. Each one is sent as the user's own chat message, so the conversation
 * reads the same whether they click or type. */
function QuickReplies({ replies, onSay, disabled }: { replies: string[]; onSay: (text: string) => void; disabled?: boolean }) {
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {replies.map((r) => (
        <button key={r} className="rounded-full border border-border px-3 py-1 text-sm text-ink-2 transition-colors hover:bg-surface-2"
          disabled={disabled} onClick={() => onSay(r)}>{r}</button>
      ))}
    </div>
  );
}

/** What the dataset search tried: queries, the Tavily web search, and each dataset left out with its reason. */
function SearchDetails({ search }: { search: NonNullable<DataStep["search"]> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button type="button" className="btn-ghost text-xs" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? "Hide" : "Show"} the search{search.left_out.length ? ` and the ${search.left_out.length} datasets left out` : ""}
      </button>
      {open && (
        <div className="mt-1 space-y-1 text-xs text-ink-3">
          <p>Hugging Face Hub search: {search.hub_queries.map((q) => `“${q}”`).join(", ")}</p>
          {search.web_query && <p>Tavily web search (huggingface.co): “{search.web_query}”</p>}
          {!!search.left_out.length && (
            <ul className="space-y-0.5">
              {search.left_out.map((r) => (
                <li key={r.name}><a className="hover:underline" href={r.url} target="_blank" rel="noreferrer">{r.name}</a>
                  {r.license && r.license !== "unknown" && <span className="ml-1">({r.license})</span>}: {r.reason}</li>
              ))}
            </ul>
          )}
          {search.searched_at && <p>Searched {search.searched_at}; recorded, so the demo doesn't depend on live results</p>}
        </div>
      )}
    </div>
  );
}

/** Intake step 1: where the training data comes from, for the user to approve before any questions. */
export function DataStepMessage({ msg, onSay }: { msg: Msg; onSay: (text: string) => void }) {
  const step = msg.dataStep ?? {};
  const d = step.dataset;
  const [choice, setChoice] = useState(msg.dataChoice);
  const options = msg.dataOptions ?? [];
  const chosen = options.find((o) => o.id === choice);
  const done = !!msg.answered;
  return (
    <div>
      <Markdown text={msg.content} />
      {d && (
        <div className="card mt-3 p-3 text-sm">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <a className="font-medium underline-offset-2 hover:underline" href={d.url} target="_blank" rel="noreferrer">{d.name}</a>
            <span className="chip" title={d.license_full}>{d.license}</span>
            {d.rows != null && <span className="text-xs text-ink-3 tabular-nums">{d.rows.toLocaleString()} labeled rows</span>}
          </div>
          {!!msg.categories?.length && <p className="mt-1 text-xs text-ink-3">{msg.categories.length > 2 ? `${msg.categories.length} categories: ` : "Labels: "}{msg.categories.slice(0, 8).join(" · ")}{msg.categories.length > 8 ? " …" : ""}</p>}
          {d.citation.filter(Boolean).map((c) => <p key={c} className="mt-1 text-xs text-ink-3">Cite: {c}</p>)}
        </div>
      )}
      {!!options.length && (
        <div className="mt-3">
          <DataChoice options={options} rejected={[]} value={choice} disabled={done} onChange={setChoice} name={`data-${msg.id}`} />
        </div>
      )}
      {step.search && <SearchDetails search={step.search} />}
      {!done && <QuickReplies onSay={onSay} replies={options.length
        ? [chosen ? (chosen.kind === "synthetic" ? "Use synthetic data" : `Use ${chosen.name}`) : "Yes, use it"]
        : ["Yes, use it", "No, something else"]} />}
    </div>
  );
}

/** Intake step 2: the clarifying questions as one conversational message; the answer is a normal chat reply. */
export function AskMessage({ msg }: { msg: Msg }) {
  return (
    <div>
      <Markdown text={msg.content} />
      {!msg.answered && <p className="mt-2 text-xs text-ink-3">Reply in the message box below.</p>}
    </div>
  );
}

/** Training data for a custom task: datasets found online (license-checked) or synthetic data from Nemotron. */
function DataChoice({ options, rejected, value, disabled, onChange, name }: {
  options: DataOption[]; rejected: { name: string; url: string; license: string; reason: string }[];
  value?: string; disabled: boolean; onChange: (id: string) => void; name: string;
}) {
  const [showRejected, setShowRejected] = useState(false);
  return (
    <fieldset className="mb-4 min-w-0">
      <legend className="mb-1.5 text-sm font-medium">Training data</legend>
      <div className="space-y-2">
        {options.map((o) => (
          <label key={o.id} className={`block cursor-pointer rounded border p-3 text-sm transition-colors ${value === o.id ? "border-ink" : "border-border hover:bg-surface-2"}`}>
            <div className="flex items-start gap-2">
              <input type="radio" className="mt-1" name={name} checked={value === o.id} disabled={disabled} onChange={() => onChange(o.id)} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  {o.url ? <a className="font-medium underline-offset-2 hover:underline" href={o.url} target="_blank" rel="noreferrer">{o.name}</a>
                         : <span className="font-medium">{o.name}</span>}
                  <span className="chip">{o.license}</span>
                  {o.rows != null && <span className="text-xs text-ink-3 tabular-nums">{o.kind === "synthetic" ? "about " : ""}{o.rows.toLocaleString()} rows</span>}
                </div>
                {o.why && <p className="mt-1 text-ink-2">{o.why}</p>}
                {o.kind === "hf" && <>
                  {!!o.label_map && <p className="mt-1 text-xs text-ink-3">Labels: {Object.entries(o.label_map).map(([a, b]) => a === b ? a : `${a} → ${b}`).join(" · ")}</p>}
                  {!!o.gap_labels.length && <p className="mt-0.5 text-xs text-ink-3">Not in this dataset, filled with synthetic examples: {o.gap_labels.join(", ")}</p>}
                  {o.format_match?.score != null && <p className="mt-0.5 text-xs text-ink-3">Format match with your samples: {o.format_match.score.toFixed(2)}. {o.format_match.explanation}</p>}
                  {!!o.samples?.length && (
                    <ul className="mono mt-1.5 space-y-0.5 text-xs text-ink-2">
                      {o.samples.map((x, i) => <li key={i} className="truncate"><span className="text-ink-3">[{x.label}]</span> {x.text}</li>)}
                    </ul>
                  )}
                  {o.found_by && <p className="mt-1 text-xs text-ink-3">Found by {o.found_by}</p>}
                </>}
              </div>
            </div>
          </label>
        ))}
      </div>
      {!!rejected.length && (
        <div className="mt-1.5">
          <button type="button" className="btn-ghost text-xs" onClick={() => setShowRejected((s) => !s)} aria-expanded={showRejected}>
            {showRejected ? "Hide" : "Show"} {rejected.length} dataset{rejected.length > 1 ? "s" : ""} left out
          </button>
          {showRejected && (
            <ul className="mt-1 space-y-0.5 text-xs text-ink-3">
              {rejected.map((r) => <li key={r.name}><a className="hover:underline" href={r.url} target="_blank" rel="noreferrer">{r.name}</a>: {r.reason}</li>)}
            </ul>
          )}
        </div>
      )}
    </fieldset>
  );
}

const METRIC_NAME: Record<string, string> = { macro_f1: "Macro-F1", recall_at_fpr: "Recall at a fixed false-positive rate", pr_auc: "PR-AUC", accuracy: "Accuracy" };

/** The task card as an editable summary with plan-change lines and one primary button. */
export function TaskCardMessage({ msg, onBuild, onShowBuild, intake }: {
  msg: Msg; onBuild: (msg: Msg) => void; onShowBuild: (msg: Msg) => void; intake: Intake;
}) {
  const card = msg.card;
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  if (!card) return null;
  const binary = card.output_type === "binary";
  const locked = !!msg.started;
  const edit = async (field: string, value: any) => {
    setSaving(true); setErr("");
    try { await intake.edit(msg, field, value); } catch (e: any) { setErr(e.message); }
    setSaving(false);
  };
  const metric = `${METRIC_NAME[card.optimization_metric] ?? card.optimization_metric}${card.fpr_target ? ` (${card.fpr_target * 100}% FPR)` : ""}`;

  return (
    <div className="card p-4" aria-busy={saving}>
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-md font-semibold">{card.task_name}</div>
        <span className="text-xs text-ink-3">Task card</span>
      </div>
      <p className="mt-1 text-sm text-ink-2">{card.description}</p>
      <dl className="mt-3 grid grid-cols-[minmax(110px,auto)_1fr] items-center gap-x-4 gap-y-2 text-sm">
        <dt className="text-ink-3">{binary ? "Positive case" : "Categories"}</dt>
        <dd>{binary ? card.positive_definition : `${card.labels.length}${card.data_source ? "" : " from the dataset"}`}</dd>
        {card.data_source && <>
          <dt className="text-ink-3">Training data</dt>
          <dd>
            {card.data_source.kind === "synthetic" ? "Synthetic, written by Nemotron Ultra"
              : <a className="underline-offset-2 hover:underline" href={card.data_source.url} target="_blank" rel="noreferrer">{card.data_source.name}</a>}
            <span className="ml-2 chip">{card.data_source.kind === "synthetic" ? "generated" : card.data_source.license}</span>
            {card.data_source.kind === "synthetic" && <div className="mt-0.5 text-xs text-ink-3">Scores, the sealed test included, are measured on synthetic data</div>}
          </dd>
        </>}
        <dt className="text-ink-3">Metric</dt>
        <dd>
          <select className="input py-1 text-sm" disabled={locked} value={card.error_preference} aria-label="Which mistake is worse"
            onChange={(e) => edit("error_preference", e.target.value)}>
            {binary ? <>
              <option value="recall_first">Missing one is worse</option>
              <option value="precision_first">False alarms are worse</option>
              <option value="balanced">Both equally</option>
            </> : <>
              <option value="balanced">All categories equally</option>
              <option value="recall_first">Some categories costlier to miss</option>
            </>}
          </select>
          <div className="mt-0.5 text-xs text-ink-3">{metric}{card.thresholds.per_class_floor ? `, recall floor ${card.thresholds.per_class_floor} per category` : ""}</div>
        </dd>
        <dt className="text-ink-3"><label htmlFor={`t-${msg.id}`}>Target</label></dt>
        <dd>
          <input key={card.thresholds.primary_min} id={`t-${msg.id}`} type="number" min={0.05} max={1} step={0.01} className="input w-24 py-1 text-sm tabular-nums" disabled={locked}
            defaultValue={card.thresholds.primary_min}
            onBlur={(e) => { const v = Number(e.target.value); if (v > 0 && v <= 1 && v !== card.thresholds.primary_min) edit("target", v); }} />
        </dd>
        <dt className="text-ink-3">Output</dt>
        <dd>
          <select className="input py-1 text-sm" disabled={locked} value={String(card.needs_reason)} aria-label="Output"
            onChange={(e) => edit("needs_reason", e.target.value === "true")}>
            <option value="false">Just the category</option><option value="true">Category and a reason</option>
          </select>
        </dd>
        <dt className="text-ink-3"><label htmlFor={`v-${msg.id}`}>Monthly volume</label></dt>
        <dd>
          <input key={card.monthly_volume} id={`v-${msg.id}`} type="number" min={1} step={1000} className="input w-36 py-1 text-sm tabular-nums" disabled={locked}
            defaultValue={card.monthly_volume ?? ""}
            onBlur={(e) => { const v = Math.round(Number(e.target.value)); if (v > 0 && v !== card.monthly_volume) edit("monthly_volume", v); }} />
          <span className="ml-2 text-xs text-ink-3">{fmtInt(card.monthly_volume)} a month</span>
        </dd>
        <dt className="text-ink-3">Latency budget</dt>
        <dd>
          <select className="input py-1 text-sm" disabled={locked} value={card.latency_budget_ms ?? ""} aria-label="Latency budget"
            onChange={(e) => edit("latency_budget_ms", e.target.value === "" ? null : Number(e.target.value))}>
            {[...new Set([20, 50, 500, card.latency_budget_ms].filter((x) => x != null))].sort((a, b) => a - b)
              .map((v) => <option key={v} value={v}>Under {v} ms</option>)}
            <option value="">No limit</option>
          </select>
        </dd>
        <dt className="text-ink-3">Deployment</dt>
        <dd>
          <select className="input py-1 text-sm" disabled={locked} value={card.deployment} aria-label="Deployment"
            onChange={(e) => edit("deployment", e.target.value)}>
            <option value="cloud_ok">Cloud calls allowed</option><option value="offline">Our own servers only</option>
          </select>
        </dd>
        <dt className="text-ink-3">Build budget</dt>
        <dd className="tabular-nums">${card.build_budget_usd?.toFixed(2)} of model calls</dd>
      </dl>
      {!!msg.planChanges?.length && (
        <div className="mt-4 border-t border-border pt-3">
          <div className="mb-1.5 text-sm font-medium">How your answers change the plan</div>
          <ul className="space-y-1.5 text-sm">
            {msg.planChanges.map((c, i) => (
              <li key={i} className="grid grid-cols-[minmax(0,180px)_1fr] gap-3">
                <span className="truncate text-ink-3" title={c.answer}>{c.answer}</span><span>{c.change}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {msg.replay && <p className="mt-3 text-xs text-ink-3">This server is in replay mode: Build specialist plays the recorded build of this task, so edits here don't change it.</p>}
      {err && <p className="mt-2 text-sm text-danger" role="alert">{err}</p>}
      <div className="mt-4 flex items-center gap-2">
        {locked
          ? <><span className="text-sm text-ink-2">Build started</span><button className="btn" onClick={() => onShowBuild(msg)}>Show progress</button></>
          : <button className="btn-primary" disabled={saving} onClick={() => onBuild(msg)}>Build specialist</button>}
      </div>
    </div>
  );
}
