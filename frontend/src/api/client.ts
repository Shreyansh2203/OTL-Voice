import { readSse } from '../lib/sse';
import type {
  AssignmentsResponse,
  ChatEvent,
  ChatMessage,
  Identity,
  SubmitResponse,
  TimecardEntry,
  TimecardsResponse,
} from '../types';
const API = import.meta.env.VITE_API_URL || '/api';
const CSRF_COOKIE_NAME = 'csrf_token';
const CSRF_HEADER_NAME = 'X-CSRF-Token';
let csrfToken: string | null = null;

export function getWsApiUrl(path: string): string {
  if (API.startsWith('http')) {
    return API.replace(/^http/, 'ws') + path;
  }
  const loc = window.location;
  const protocol = loc.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${loc.host}${API}${path}`;
}

function captureCsrfToken(response: Response): void {
  const value = response.headers?.get?.(CSRF_HEADER_NAME);
  if (value) csrfToken = value;
}

function getCsrfToken(): string | null {
  const match = document.cookie.match(
    new RegExp(`(^|;\\s*)${CSRF_COOKIE_NAME}=([^;]+)`)
  );
  return match ? match[2] : csrfToken;
}
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}
async function parseError(res: Response): Promise<ApiError> {
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const data = await res.json();
    if (data && typeof data.detail === 'string') detail = data.detail;
  } catch (e) {
    void e;
  }
  return new ApiError(res.status, detail);
}
async function fetchWithRetry(
  url: string,
  options: RequestInit = {},
  retries = 3,
  backoff = 300
): Promise<Response> {
  try {
    options.headers = { ...defaultHeaders(), ...options.headers };
    const response = await fetch(url, options);
    captureCsrfToken(response);
    const method = options.method?.toUpperCase() || 'GET';
    const isSafeMethod = ['GET', 'HEAD', 'OPTIONS'].includes(method);
    if (response.status >= 500 && isSafeMethod && retries > 0) {
      await new Promise((resolve) => setTimeout(resolve, backoff));
      return fetchWithRetry(url, options, retries - 1, backoff * 2);
    }
    return response;
  } catch (err) {
    const method = options.method?.toUpperCase() || 'GET';
    const isSafeMethod = ['GET', 'HEAD', 'OPTIONS'].includes(method);
    if (isSafeMethod && retries > 0) {
      await new Promise((resolve) => setTimeout(resolve, backoff));
      return fetchWithRetry(url, options, retries - 1, backoff * 2);
    }
    throw err;
  }
}
export function defaultHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const csrfToken = getCsrfToken();
  if (csrfToken) {
    headers[CSRF_HEADER_NAME] = csrfToken;
  }
  const sessionToken = localStorage.getItem('otl_session');
  if (sessionToken) {
    headers['Authorization'] = `Bearer ${sessionToken}`;
  }
  return headers;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  const headers = defaultHeaders();
  if (body) {
    headers['Content-Type'] = 'application/json';
  }
  return {
    method,
    credentials: 'include',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

export async function login(
  username: string,
  password = ''
): Promise<Identity> {
  if (!getCsrfToken()) {
    await fetchWithRetry(API + '/health', { credentials: 'include' });
  }
  const res = await fetch(
    `${API}/auth/login`,
    jsonInit('POST', { username, password })
  );
  captureCsrfToken(res);
  if (!res.ok) throw await parseError(res);
  const data = await res.json();
  if (data.sessionToken) {
    localStorage.setItem('otl_session', data.sessionToken);
  }
  return data.employee ? data.employee : data;
}
export async function getSession(): Promise<Identity | null> {
  const res = await fetchWithRetry(`${API}/auth/session`, {
    credentials: 'include',
  });
  if (res.status === 401) {
    localStorage.removeItem('otl_session');
    return null;
  }
  if (!res.ok) throw await parseError(res);
  return res.json();
}
export async function refreshSession(): Promise<void> {
  const res = await fetch(`${API}/auth/refresh`, jsonInit('POST'));
  captureCsrfToken(res);
  if (!res.ok) throw await parseError(res);
}
export async function logout(): Promise<void> {
  const res = await fetch(`${API}/auth/logout`, jsonInit('POST'));
  captureCsrfToken(res);
  if (!res.ok && res.status !== 401) throw await parseError(res);
  localStorage.removeItem('otl_session');
  csrfToken = null;
}
export async function chatStream(
  messages: ChatMessage[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const history = messages.map((m) => ({ role: m.role, content: m.content }));
  const controller = new AbortController();
  const abortHandler = () => controller.abort();
  if (signal) {
    if (signal.aborted) {
      controller.abort();
    } else {
      signal.addEventListener('abort', abortHandler);
    }
  }
  try {
    const res = await fetch(`${API}/chat`, {
      ...jsonInit('POST', { messages: history }),
      signal: controller.signal,
    });
    if (!res.ok) throw await parseError(res);
    await readSse(res, onEvent, controller.signal);
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      return;
    }
    throw err;
  } finally {
    if (signal) {
      signal.removeEventListener('abort', abortHandler);
    }
  }
}
export async function tts(text: string, rate = 1.0): Promise<Blob> {
  const res = await fetch(`${API}/tts`, jsonInit('POST', { text, rate }));
  if (!res.ok) throw await parseError(res);
  return res.blob();
}
export async function getAssignments(): Promise<AssignmentsResponse> {
  const res = await fetchWithRetry(`${API}/labour/assignments`, {
    credentials: 'include',
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}
export async function submitTimecard(
  entries: TimecardEntry[]
): Promise<SubmitResponse> {
  const res = await fetch(`${API}/otl/timecard`, jsonInit('POST', { entries }));
  if (!res.ok) throw await parseError(res);
  return res.json();
}
export async function listTimecards(
  limit = 25,
  offset = 0
): Promise<TimecardsResponse> {
  const res = await fetchWithRetry(
    `${API}/otl/timecards?limit=${limit}&offset=${offset}`,
    { credentials: 'include' }
  );
  if (!res.ok) throw await parseError(res);
  return res.json();
}
export async function getHealth(): Promise<{ status: string }> {
  const res = await fetchWithRetry(`${API}/health`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}
export async function getHealthOtl(): Promise<{
  ok: boolean;
  username?: string;
}> {
  const res = await fetchWithRetry(
    `${API}/health/otl`,
    { credentials: 'include' },
    0
  );
  if (!res.ok) throw await parseError(res);
  return res.json();
}
export async function refreshCatalogue(): Promise<{
  isLoaded: boolean;
  isLoading: boolean;
  totalProjects: number;
  totalPersonsIndexed: number;
  catalogueAgeSeconds?: number;
  refreshIntervalSeconds: number;
}> {
  const res = await fetch(`${API}/admin/refresh-catalogue`, jsonInit('POST'));
  if (!res.ok) throw await parseError(res);
  return res.json();
}
export async function getCatalogueStatus(): Promise<{
  isLoaded: boolean;
  isLoading: boolean;
  totalProjects: number;
  totalPersonsIndexed: number;
  catalogueAgeSeconds?: number;
  refreshIntervalSeconds: number;
}> {
  const res = await fetchWithRetry(`${API}/admin/catalogue-status`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}
