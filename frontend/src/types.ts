export type Role = "user" | "assistant";
export interface Identity {
  username: string;
  employeeId: string;
  fullName: string;
}
export interface AssignedTask {
  taskId: string | number;
  taskDetails: string;
}
export interface AssignedProject {
  projectNo: string | number;
  projectName: string;
  tasks: AssignedTask[];
}
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
  hidden?: boolean;
  streaming?: boolean;
  thinking?: boolean;
  reasoning?: string;
  toolCalls?: ToolCall[];
}
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
export interface ChatEvent {
  delta?: string;
  done?: boolean;
  error?: string;
}
export interface TimecardsResponse {
  items: any[];
}