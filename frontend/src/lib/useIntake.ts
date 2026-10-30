import { useState } from "react";
import { postJSON } from "./api";
import type { DataOption, Msg } from "./types";

/** Requests that should go through intake (data step → questions → task card) instead of plain chat. */
const BUILD_INTENT = /\b(sort|categori[sz]e|classif|route|routing|flag|detect|label|triage|tag|automate|specialist|build|anomal)/i;
/** "Create / make / train a model that…" */
const MODEL_INTENT = /\b(create|make|train|need|want|new)\b.*\b(model|classifier|predictor)s?\b/i;
/** Replies to "OK to train on it?" */
const DECLINE = /^\s*(no|nope|nah)\b|\b(don't|do not|rather not|something else|other data|different data)\b/i;
const APPROVE = /\b(yes|yeah|yep|yup|sure|ok|okay|sounds good|go ahead|use (it|that|this)|works|fine|great|perfect|do it|let's go)\b/i;
const ORDINAL: Record<string, number> = { first: 0, "1st": 0, second: 1, "2nd": 1, third: 2, "3rd": 2 };

type Deps = {
  push: (m: Omit<Msg, "id">) => string;
  patch: (id: string, fn: (m: Msg) => Msg) => void;
};

/** The data option a reply names for a custom task ("synthetic", "the second one", a dataset name), if any. */
function named(options: DataOption[], text: string): DataOption | undefined {
  const t = text.toLowerCase();
  if (/synthetic|generate/.test(t)) return options.find((o) => o.kind === "synthetic");
  const ord = Object.keys(ORDINAL).find((w) => new RegExp(`\\b${w}\\b`).test(t));
  if (ord) return options.filter((o) => o.kind === "hf")[ORDINAL[ord]];
  return options.find((o) => o.kind === "hf" && (t.includes(o.name.toLowerCase()) || t.includes(o.name.split("/").pop()!.toLowerCase())));
}

/** Intake as a conversation (spec 01 §2.2). The request gets a data message: what the dataset search found and the
 * training data to approve. Approval brings one message with the clarifying questions (at most 7, DECISION D5),
 * answered in a normal chat reply. The reply becomes an editable task card whose plan-change lines show what
 * each answer does to the build. */
export function useIntake({ push, patch }: Deps) {
  const [busy, setBusy] = useState(false);

  const sampleRows = async (file?: File) => {
    if (!file) return [];
    const text = await file.text();
    return text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).slice(0, 20);
  };

  return {
    busy,
    /** The intake message waiting for the user's reply, if the latest assistant message is one. */
    pending(messages: Msg[]): Msg | undefined {
      const last = [...messages].reverse().find((m) => m.role === "assistant");
      return last && (last.kind === "data" || last.kind === "ask") && !last.answered ? last : undefined;
    },
    /** Returns true when the message was handled as a build request. */
    async handle(text: string, file?: File): Promise<boolean> {
      if (!BUILD_INTENT.test(text) && !MODEL_INTENT.test(text) && !file) return false;
      setBusy(true);
      // A new task (not one of the demo datasets) searches Hugging Face and the web, which takes a while.
      const id = push({ role: "assistant", kind: "text", content: "_Reading your request and looking for labeled "
                        + "training data with a license we can use…_" });
      const replace = (m: Omit<Msg, "id">) => patch(id, () => ({ ...m, id }));
      try {
        const samples = await sampleRows(file);
        const r = await postJSON("/api/intake/start", { text, samples });
        if (!r.task_id) {
          replace({ role: "assistant", kind: "text", content: r.message });
          return true;
        }
        replace({ role: "assistant", kind: "data", content: r.message, taskId: r.task_id, categories: r.categories,
                  samples, replay: r.replay, ask: r.ask, dataStep: r.data_step, draftCard: r.card,
                  dataOptions: r.data_options, dataChoice: r.data_choice, dataRejected: r.data_rejected });
        return true;
      } catch (e: any) {
        replace({ role: "assistant", kind: "error", content: `Couldn't start intake: ${e.message}` });
        return true;
      } finally {
        setBusy(false);
      }
    },
    /** The user's chat reply to a pending intake message. Returns false when it isn't an answer (a question, say),
     * so the main chat answers it instead. */
    async reply(msg: Msg, text: string): Promise<boolean> {
      if (msg.kind === "data") {
        const options = msg.dataOptions ?? [];
        const option = named(options, text);
        if (!option && DECLINE.test(text)) {
          push({ role: "assistant", kind: "text", content: options.length
            ? "No problem. Pick another of the options above (or synthetic data), or describe the task differently and I'll search again."
            : "No problem. Training on your own labeled data from an upload is next on our roadmap; until then this "
              + "vetted dataset is what I can build this task from. Describe a different task and I'll search for its data." });
          return true;
        }
        if (!option && !APPROVE.test(text)) return false;
        const chosen = option ?? options.find((o) => o.id === msg.dataChoice) ?? options[0];
        patch(msg.id, (m) => ({ ...m, answered: true, dataChoice: chosen?.id ?? m.dataChoice }));
        push({ role: "assistant", kind: "ask", content: msg.ask ?? "", taskId: msg.taskId, draftCard: msg.draftCard,
               dataOption: chosen, samples: msg.samples, replay: msg.replay });
        return true;
      }
      if (text.trim().endsWith("?")) return false;      // a question about the questions: answer it in chat
      setBusy(true);
      try {
        const r = await postJSON("/api/intake/card", { task_id: msg.taskId, reply: text, samples: msg.samples ?? [],
                                                       card: msg.draftCard, data_option: msg.dataOption });
        patch(msg.id, (m) => ({ ...m, answered: true }));
        push({ role: "assistant", kind: "taskcard", content: r.ack ?? "", card: r.card, planChanges: r.plan_changes,
               taskId: msg.taskId, answers: r.answers, texts: {}, samples: msg.samples, replay: r.replay,
               draftCard: msg.draftCard, dataOption: msg.dataOption });
      } catch (e: any) {
        push({ role: "assistant", kind: "error", content: `Couldn't make the task card: ${e.message}` });
      } finally {
        setBusy(false);
      }
      return true;
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
