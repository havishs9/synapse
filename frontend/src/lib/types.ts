export type RunEvent = {
  ts: number; agent: string; stage: string; message: string; data_ref?: string | null;
  spend_usd: number; kind: string; data?: any; replay?: boolean;
};

export type Msg = {
  id: string; role: "user" | "assistant"; content: string;
  kind?: "text" | "questions" | "taskcard" | "build" | "error";
  card?: any; runId?: string; attachment?: { name: string; rows: number };
  questions?: any[];
};

export type Chat = { id: string; title: string; messages: Msg[]; updated: number };

export type Pane = { kind: "build"; runId: string; replay: boolean; taskId: string } | { kind: "specialist"; sid: string } | null;

export type SpecialistSummary = {
  specialist_id: string; display_name: string; color: string; monogram: string; task_id: string;
  live_version: number | null; versions: number;
};
