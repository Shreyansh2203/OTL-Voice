import { readSse } from "../lib/sse";
import type {
  AssignmentsResponse,
  ChatEvent,
  ChatMessage,
  Identity,
  SubmitResponse,
  TimecardEntry,
} from "../types";

/** Same-origin in prod; the Vite dev/preview proxy forwards /api to the backend. */
const API = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const data = await res.json();
    if (data && typeof data.detail === "string") detail = data.detail;
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, detail);
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    credentials: "include", // send/receive the session cookie
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

// --------------------------------------------------------------------------- //
// Auth
// --------------------------------------------------------------------------- //
export async function login(
  username: string,
  password: string
): Promise<Identity> {
  const res = await fetch(`${API}/auth/login`, jsonInit("POST", { username, password }));
  if (!res.ok) throw await parseError(res);
  return res.json();
}

/** Returns the signed-in employee, or null when there is no valid session. */
export async function getSession(): Promise<Identity | null> {
  const res = await fetch(`${API}/auth/session`, { credentials: "include" });
  if (res.status === 401) return null;
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function logout(): Promise<void> {
  await fetch(`${API}/auth/logout`, jsonInit("POST"));
}

// --------------------------------------------------------------------------- //
// Chat (SSE)
// --------------------------------------------------------------------------- //
export async function chatStream(
  messages: ChatMessage[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const history = messages.map((m) => ({ role: m.role, content: m.content }));
  const res = await fetch(`${API}/chat`, {
    ...jsonInit("POST", { messages: history }),
    signal,
  });
  if (!res.ok) throw await parseError(res);
  await readSse(res, onEvent, signal);
}

// --------------------------------------------------------------------------- //
// Text-to-speech
// --------------------------------------------------------------------------- //
export async function tts(text: string, rate = 1.0): Promise<Blob> {
  const res = await fetch(`${API}/tts`, jsonInit("POST", { text, rate }));
  if (!res.ok) throw await parseError(res);
  return res.blob();
}

// --------------------------------------------------------------------------- //
// Labour catalogue
// --------------------------------------------------------------------------- //
/** The signed-in employee's work orders, projects and their usual tasks. */
export async function getAssignments(): Promise<AssignmentsResponse> {
  const res = await fetch(`${API}/labour/assignments`, { credentials: "include" });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// --------------------------------------------------------------------------- //
// OTL timecard
// --------------------------------------------------------------------------- //
export async function submitTimecard(
  entries: TimecardEntry[]
): Promise<SubmitResponse> {
  const res = await fetch(`${API}/otl/timecard`, jsonInit("POST", { entries }));
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function listTimecards(limit = 25, offset = 0): Promise<unknown> {
  const res = await fetch(
    `${API}/otl/timecards?limit=${limit}&offset=${offset}`,
    { credentials: "include" }
  );
  if (!res.ok) throw await parseError(res);
  return res.json();
}
