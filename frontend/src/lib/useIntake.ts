import { useState } from "react";
import { postJSON } from "./api";
import type { Msg } from "./types";

/** Requests that should go through intake (clarifying questions → task card) instead of plain chat. */
const BUILD_INTENT = /\b(sort|categori[sz]e|classif|route|routing|flag|detect|label|triage|tag|automate|specialist|build|anomal)/i;
/** "Create / make / train a model that…" */
const MODEL_INTENT = /\b(create|make|train|need|want|new)\b.*\b(model|classifier|predictor)s?\b/i;

type Deps = {
  push: (m: Omit<Msg, "id">) => string;
  patch: (id: string, fn: (m: Msg) => Msg) => void;
  remove: (id: string) => void;
};

/** Intake (spec 01 §2.2): Nemotron Ultra asks one message with at most 7 questions; the answers become an
 * editable task card whose plan-change lines show what each answer does to the build. */
export function useIntake({ push, patch, remove }: Deps) {
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
      if (!BUILD_INTENT.test(text) && !MODEL_INTENT.test(text) && !file) return false;
      setBusy(true);
      // A new task (not one of the demo datasets) searches Hugging Face and the web, which takes a while.
      const id = push({ role: "assistant", kind: "text", content: "_Reading your request. If it's a new task, I'll search "
                        + "Hugging Face and the web for a labeled dataset with an allowed license…_" });
      const replace = (m: Omit<Msg, "id">) => patch(id, () => ({ ...m, id }));
      try {
        const samples = await sampleRows(file);
        const r = await postJSON("/api/intake/start", { text, samples });
        if (r.chat) {                     // Nemotron read it as a question, not a build request: answer in plain chat
          remove(id);
          return false;
        }
        if (!r.task_id) {
          replace({ role: "assistant", kind: "text", content: r.message });
          return true;
        }
        replace({ role: "assistant", kind: "questions", content: r.message, taskId: r.task_id, questions: r.questions,
                  categories: r.categories, samplesHint: r.samples_hint, samples, replay: r.replay,
                  answers: Object.fromEntries(r.questions.map((q: any) => [q.id, q.default])),
                  draftCard: r.card, dataOptions: r.data_options, dataChoice: r.data_choice, dataRejected: r.data_rejected });
        return true;
      } catch (e: any) {
        replace({ role: "assistant", kind: "error", content: `Couldn't start intake: ${e.message}` });
        return true;
      } finally {
        setBusy(false);
      }
    },
    /** Answers submitted: build the task card. */
    async answer(msg: Msg, answers: Record<string, any>, texts: Record<string, string>, samples: string[], dataChoice?: string) {
      setBusy(true);
      try {
        const dataOption = msg.dataOptions?.find((o) => o.id === dataChoice);
        const r = await postJSON("/api/intake/card", { task_id: msg.taskId, answers, texts, samples,
                                                       card: msg.draftCard, data_option: dataOption });
        patch(msg.id, (m) => ({ ...m, answered: true, answers, texts, samples, dataChoice }));
        push({ role: "assistant", kind: "taskcard", content: "", card: r.card, planChanges: r.plan_changes,
               taskId: msg.taskId, answers, texts, samples, replay: r.replay, draftCard: msg.draftCard, dataOption });
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
      const r = await postJSON("/api/intake/card", { task_id: msg.taskId, answers, texts, samples: msg.samples ?? [],
                                                     card: msg.draftCard, data_option: msg.dataOption });
      patch(msg.id, (m) => ({ ...m, card: r.card, planChanges: r.plan_changes, answers, texts }));
    },
  };
}
export type Intake = ReturnType<typeof useIntake>;
