export type Role = "user" | "assistant";

/** The signed-in employee, as returned by login and session. */
export interface Identity {
  username: string;
  /** OTL Employee_Number_c — the app's authority on who is logging time. */
  employeeId: string;
  fullName: string;
}

/** One project an employee may log against, with its usual tasks. */
export interface AssignedProject {
  projectNo: number;
  projectName: string;
  tasks: string[];
}

/** A work order and the assigned projects beneath it (one WO, many projects). */
export interface AssignedWorkOrder {
  workOrder: string;
  description: string | null;
  projects: AssignedProject[];
}

export interface AssignmentsResponse {
  employeeId: string;
  fullName: string;
  workOrders: AssignedWorkOrder[];
}

export interface ToolCall {
  name: string;
  status: "running" | "completed" | "failed";
}

export interface ChatMessage {
  role: Role;
  content: string;
  /** Kickoff turn is sent to the model but not shown in the transcript. */
  hidden?: boolean;
  /** True while assistant text is still streaming in. */
  streaming?: boolean;
  /** True if the assistant is currently in a thinking state. */
  thinking?: boolean;
  /** Expandable reasoning trace text. */
  reasoning?: string;
  /** Tool invocations associated with this message. */
  toolCalls?: ToolCall[];
}

/** One timesheet entry, in the app shape the backend maps to TimecardEntry_c. */
export interface TimecardEntry {
  employeeNumber?: string;
  employeeName?: string;
  projectNo?: number;
  projectName?: string;
  workOrder?: string;
  taskDetails?: string;
  hours?: number;
  currencyCode?: string;
  recordName?: string;
}

export interface SubmitResultRow {
  index: number;
  ok: boolean;
  id?: number;
  recordNumber?: string;
  recordName?: string;
  status?: number;
  error?: string;
}

export interface SubmitResponse {
  submitted: number;
  succeeded: number;
  failed: number;
  results: SubmitResultRow[];
}

/** One SSE frame emitted by POST /api/chat. */
export interface ChatEvent {
  delta?: string;
  done?: boolean;
  error?: string;
}
