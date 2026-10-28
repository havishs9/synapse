import { getJSON } from "./api";
import type { Msg } from "./types";

const TASK_FOR: Record<string, string> = {
  "sort purchase records into spending categories": "procurement",
  "flag anomalies in system logs": "hdfs_logs",
  "route support tickets to the right team": "support_tickets",
};

/** Phase 1 intake: example prompts map straight to the demo task cards. */
export function useIntake({ push }: { push: (m: Omit<Msg, "id">) => void; patchLast: (fn: (m: Msg) => Msg) => void; messages: Msg[] }) {
  return {
    async handle(text: string, _file?: File): Promise<boolean> {
      const task = TASK_FOR[text.trim().toLowerCase()];
      if (!task) return false;
      const card = await getJSON(`/api/demo_tasks/${task}`);
      push({ role: "assistant", kind: "taskcard", content: "", card });
      return true;
    },
    answer: async (_: any) => {},
    busy: false,
  };
}
export type Intake = ReturnType<typeof useIntake>;
