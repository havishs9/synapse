export type RunEvent = {
  ts: number; agent: string; stage: string; message: string; data_ref?: string | null;
  spend_usd: number; kind: string; data?: any; replay?: boolean;
};

export type QuestionOption = { value: any; label: string };
export type Question = { id: string; text: string; options: QuestionOption[]; default: any };
export type PlanChange = { question: string; answer: string; change: string };

/** A training-data choice for a custom task (backend/data_sourcing.py): a Hugging Face dataset or synthetic. */
export type DataOption = {
  id: string; kind: "hf" | "synthetic"; name: string; url?: string; license: string; rows?: number; why?: string;
  fit?: number; found_by?: string; labels: string[]; gap_labels: string[]; label_map?: Record<string, string>;
  text_column?: string; label_column?: string; samples?: { text: string; label: string }[];
  format_match?: { score: number | null; explanation: string };
};
export type RejectedDataset = { name: string; url: string; license: string; reason: string };
/** The data step of intake (backend/routes/product.py): the dataset search and, for demo tasks, the vetted dataset. */
export type DataStep = {
  search?: { hub_queries: string[]; web_query?: string | null; candidates: number; searched_at?: string; summary: string;
             left_out: RejectedDataset[] } | null;
  dataset?: { name: string; url: string; source: string; license: string; license_full: string; citation: string[];
              rows?: number | null; labels: number; about?: string };
};

export type Msg = {
  id: string; role: "user" | "assistant"; content: string;
  kind?: "text" | "questions" | "data" | "ask" | "taskcard" | "build" | "error";
  card?: any; runId?: string; attachment?: { name: string; rows: number };
  // intake
  taskId?: string; questions?: Question[]; categories?: string[]; samplesHint?: string; samples?: string[];
  answers?: Record<string, any>; texts?: Record<string, string>; planChanges?: PlanChange[];
  answered?: boolean; replay?: boolean; started?: string;
  // custom task: the drafted card and its data choices
  draftCard?: any; dataOptions?: DataOption[]; dataChoice?: string; dataRejected?: RejectedDataset[];
  dataOption?: DataOption;
  // conversational intake: the data step, then one message of questions answered in a chat reply
  dataStep?: DataStep; ask?: string;
};

export type Chat = { id: string; title: string; messages: Msg[]; updated: number };

export type Pane =
  | { kind: "build"; runId: string; replay: boolean; taskId?: string; title?: string; improveOf?: string }
  | { kind: "specialist"; sid: string }
  | null;

export type SpecialistSummary = {
  specialist_id: string; display_name: string; color: string; monogram: string; task_id: string;
  live_version: number | null; versions: number;
};

/** One row of GET /api/builds (contract: docs/TEAM_PLAN.md §1). */
export type Build = {
  run_id: string; task_id: string; task_name: string; status: "queued" | "running" | "done" | "failed" | "cancelled";
  stage: string | null; round: number | null; n_rounds: number | null; spend_usd: number; budget_usd: number | null;
  created_at: number | null; updated_at: number | null; message: string; specialist_id: string | null;
  version: number | null; deployed: boolean | null; kind: "build" | "improve";
};
