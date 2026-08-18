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
/**
 * Authenticates an employee using their Oracle Fusion credentials.
 * 
 * @param username - The Oracle Fusion Person Number or username.
 * @param password - The user's password.
 * @returns The authenticated identity.
 * @throws {ApiError} If authentication fails.
 */
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

/**
 * Terminates the active session and clears the session cookie.
 * 
 * @throws {ApiError} If the logout request fails.
 */
export async function logout(): Promise<void> {
  await fetch(`${API}/auth/logout`, jsonInit("POST"));
}

// --------------------------------------------------------------------------- //
// Chat (SSE)
// --------------------------------------------------------------------------- //
/**
 * Streams assistant responses via Server-Sent Events (SSE).
 * 
 * @param messages - The message history and new user message.
 * @param onEvent - Callback fired when a new SSE token or event arrives.
 * @param signal - Optional AbortSignal to cancel the streaming request.
 * @throws {ApiError} If the stream initiation fails.
 */
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
/**
 * Synthesizes speech audio from provided text using OCI AI Speech Service.
 * 
 * @param text - The text to synthesize.
 * @param rate - The speech rate multiplier (default: 1.0).
 * @returns A Blob containing the binary audio data (e.g. MP3).
 * @throws {ApiError} If the TTS service is unavailable.
 */
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
/**
 * Submits validated timecard entries to Oracle Fusion Cloud HCM.
 * 
 * @param entries - Array of prepared timecard entries to submit.
 * @returns The submission results, including succeeded and failed counts.
 * @throws {ApiError} If the submission is rejected.
 */
export async function submitTimecard(
  entries: TimecardEntry[]
): Promise<SubmitResponse> {
  const res = await fetch(`${API}/otl/timecard`, jsonInit("POST", { entries }));
  if (!res.ok) throw await parseError(res);
  return res.json();
}

/**
 * Queries historical timecard entries from Oracle Fusion for the current employee.
 * 
 * @param limit - Maximum number of records to fetch (default: 25).
 * @param offset - Pagination offset (default: 0).
 * @returns Paginated list of historical timecards.
 * @throws {ApiError} If the fetch fails.
 */
export async function listTimecards(limit = 25, offset = 0): Promise<unknown> {
  const res = await fetch(
    `${API}/otl/timecards?limit=${limit}&offset=${offset}`,
    { credentials: "include" }
  );
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// --------------------------------------------------------------------------- //
// Health & Admin
// --------------------------------------------------------------------------- //
/**
 * Basic service liveness check.
 * 
 * @returns The health status of the API.
 */
export async function getHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API}/health`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

/**
 * Validates connectivity and credentials against the upstream Oracle Fusion HCM REST API.
 * 
 * @returns Status of the Fusion API connection.
 */
export async function getHealthOtl(): Promise<unknown> {
  const res = await fetch(`${API}/health/otl`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

/**
 * Re-exports data from Oracle Fusion and reloads the local catalogue cache.
 * 
 * @returns Status of the refresh operation.
 */
export async function refreshCatalogue(): Promise<unknown> {
  const res = await fetch(`${API}/admin/refresh-catalogue`, jsonInit("POST"));
  if (!res.ok) throw await parseError(res);
  return res.json();
}

/**
 * Returns the current cache status and last synchronization timestamp of the labour catalogue.
 * 
 * @returns The catalogue status.
 */
export async function getCatalogueStatus(): Promise<unknown> {
  const res = await fetch(`${API}/admin/catalogue-status`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}
