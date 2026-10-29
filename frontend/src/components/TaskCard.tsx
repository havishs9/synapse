import { useState } from "react";
import type { Msg, Question } from "../lib/types";
import type { Intake } from "../lib/useIntake";
import { fmtInt } from "../lib/api";

const same = (a: any, b: any) => JSON.stringify(a) === JSON.stringify(b);

/** One message with at most 7 clarifying questions (spec 01 §2.2). Each has quick answers and a free-text box. */
export function QuestionsMessage({ msg, intake }: { msg: Msg; intake: Intake }) {
  const [answers, setAnswers] = useState<Record<string, any>>(msg.answers ?? {});
  const [texts, setTexts] = useState<Record<string, string>>(msg.texts ?? {});
  const [samples, setSamples] = useState((msg.samples ?? []).join("\n"));
  const [showCats, setShowCats] = useState(false);
  const done = !!msg.answered;
  const qs = (msg.questions ?? []).slice(0, 7);

  const submit = () => intake.answer(msg, answers, Object.fromEntries(Object.entries(texts).filter(([, v]) => v.trim())),
                                     samples.split("\n").map((s) => s.trim()).filter(Boolean));
  return (
    <div>
      <p className="mb-3">{msg.content}</p>
      <ol className="space-y-4">
        {qs.map((q: Question, i) => (
          <li key={q.id}>
            <div className="mb-1.5 flex gap-2"><span className="text-ink-3 tabular-nums">{i + 1}.</span><span>{q.text}</span></div>
            {q.id === "labels" && !!msg.categories?.length && (
              <div className="mb-1.5 pl-5">
                <button className="btn-ghost text-xs" onClick={() => setShowCats((s) => !s)} aria-expanded={showCats}>
                  {showCats ? "Hide" : "Show"} the {msg.categories.length} categories
                </button>
                {showCats && <p className="mt-1 text-sm text-ink-2">{msg.categories.join(" · ")}</p>}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-1.5 pl-5" role="radiogroup" aria-label={q.text}>
              {q.options.map((o) => {
                const on = !texts[q.id]?.trim() && same(answers[q.id], o.value);
                return (
                  <button key={String(o.value)} role="radio" aria-checked={on} disabled={done}
                    className={`rounded-full border px-3 py-1 text-sm transition-colors ${on ? "border-ink bg-ink text-surface" : "border-border text-ink-2 hover:bg-surface-2"}`}
                    onClick={() => { setAnswers((a) => ({ ...a, [q.id]: o.value })); setTexts((t) => ({ ...t, [q.id]: "" })); }}>
                    {o.label}
                  </button>
                );
              })}
              <input className="input min-w-[140px] flex-1 py-1 text-sm" placeholder="Or say it in your words" disabled={done}
                aria-label={`${q.text} (free text)`} value={texts[q.id] ?? ""} onChange={(e) => setTexts((t) => ({ ...t, [q.id]: e.target.value }))} />
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-4">
        <label className="mb-1 block text-sm font-medium" htmlFor={`samples-${msg.id}`}>Sample rows</label>
        <p className="mb-1.5 text-xs text-ink-3">{msg.samplesHint}</p>
        <textarea id={`samples-${msg.id}`} className="input mono min-h-[72px] text-sm" rows={3} disabled={done}
          placeholder="One record per line" value={samples} onChange={(e) => setSamples(e.target.value)} />
      </div>
      {!done && <button className="btn-primary mt-3" onClick={submit} disabled={intake.busy}>{intake.busy ? "Making the task card…" : "Make task card"}</button>}
    </div>
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
        <dd>{binary ? card.positive_definition : `${card.labels.length} from the dataset`}</dd>
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
