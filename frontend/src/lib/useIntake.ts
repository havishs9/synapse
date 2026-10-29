import { useState } from "react";
import { postJSON } from "./api";
import type { Msg } from "./types";

/** Requests that should go through intake (clarifying questions → task card) instead of plain chat. */
const BUILD_INTENT = /\b(sort|categori[sz]e|classif|route|routing|flag|detect|label|triage|tag|automate|specialist|build|anomal)/i;

type Deps = {
  push: (m: Omit<Msg, "id">) => void;
  patch: (id: string, fn: (m: Msg) => Msg) => void;
};

/** Intake (spec 01 §2.2): Nemotron Ultra asks one message with at most 7 questions; the answers become an
 * editable task card whose plan-change lines show what each answer does to the build. */
export function useIntake({ push, patch }: Deps) {
  const [busy, setBusy] = useState(false);

  const sampleRows = async (file?: File) => {
    if (!file) return [];
    const text = await file.text();
    return text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).slice(0, 20);
  };

  return {
    busy,
    /** Returns true when the message was handled as a build request. */
    async handle(text: string, file?: File): Promise<boolean> {
      if (!BUILD_INTENT.test(text) && !file) return false;
      setBusy(true);
      try {
        const samples = await sampleRows(file);
        const r = await postJSON("/api/intake/start", { text, samples });
        if (!r.task_id) {
          push({ role: "assistant", kind: "text", content: r.message });
          return true;
        }
        push({ role: "assistant", kind: "questions", content: r.message, taskId: r.task_id, questions: r.questions,
               categories: r.categories, samplesHint: r.samples_hint, samples, replay: r.replay,
               answers: Object.fromEntries(r.questions.map((q: any) => [q.id, q.default])) });
        return true;
      } catch (e: any) {
        push({ role: "assistant", kind: "error", content: `Couldn't start intake: ${e.message}` });
        return true;
      } finally {
        setBusy(false);
      }
    },
    /** Answers submitted: build the task card. */
    async answer(msg: Msg, answers: Record<string, any>, texts: Record<string, string>, samples: string[]) {
      setBusy(true);
      try {
        const r = await postJSON("/api/intake/card", { task_id: msg.taskId, answers, texts, samples });
        patch(msg.id, (m) => ({ ...m, answered: true, answers, texts, samples }));
        push({ role: "assistant", kind: "taskcard", content: "", card: r.card, planChanges: r.plan_changes,
               taskId: msg.taskId, answers, texts, samples, replay: r.replay });
      } catch (e: any) {
        push({ role: "assistant", kind: "error", content: `Couldn't make the task card: ${e.message}` });
      } finally {
        setBusy(false);
      }
    },
    /** A field on the card was edited: recompute the card and its plan changes. */
    async edit(msg: Msg, field: string, value: any) {
      const answers = { ...(msg.answers ?? {}), [field]: value };
      const texts = { ...(msg.texts ?? {}) };
      delete texts[field];              // the edited value replaces a free-text answer to the same question
      const r = await postJSON("/api/intake/card", { task_id: msg.taskId, answers, texts, samples: msg.samples ?? [] });
      patch(msg.id, (m) => ({ ...m, card: r.card, planChanges: r.plan_changes, answers, texts }));
    },
  };
}
export type Intake = ReturnType<typeof useIntake>;
