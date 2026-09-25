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
const MAX_CHAT_MESSAGES = 50;
const MAX_CHAT_CONTENT_LENGTH = 10_000;
const MAX_TTS_LENGTH = 2_000;
let csrfToken: string | null = null;
let refreshPromise: Promise<void> | null = null;

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

function getCookieCsrfToken(): string | null {
  const match = document.cookie.match(
    new RegExp(`(^|;\\s*)${CSRF_COOKIE_NAME}=([^;]+)`)
  );
  return match ? match[2] : null;
}

function getCsrfToken(): string | null {
  return getCookieCsrfToken() || csrfToken;
}

function withCurrentCsrf(headers?: HeadersInit): Headers {
  const current = new Headers(headers);
  const token = getCsrfToken();
  if (token) current.set(CSRF_HEADER_NAME, token);
  else current.delete(CSRF_HEADER_NAME);
  return current;
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
    const data: unknown = await res.json();
    if (
      data &&
      typeof data === 'object' &&
      'detail' in data &&
      typeof data.detail === 'string'
    ) {
      detail = data.detail;
    }
  } catch (error: unknown) {
    void error;
  }
  return new ApiError(res.status, detail);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function parseSubmitResponse(value: unknown): SubmitResponse {
  const invalid = () =>
    new ApiError(
      502,
      'The server returned an invalid submission confirmation. Retry safely.'
    );
  if (!isRecord(value) || !Array.isArray(value.results)) throw invalid();
  const { submitted: rawSubmitted, succeeded: rawSucceeded, failed: rawFailed, results } = value;
  const submitted = rawSubmitted as number;
  const succeeded = rawSucceeded as number;
  const failed = rawFailed as number;
  if (
    !Number.isInteger(submitted) ||
    !Number.isInteger(succeeded) ||
    !Number.isInteger(failed) ||
    submitted !== results.length ||
    submitted === 0 ||
    succeeded + failed !== submitted
  ) {
    throw invalid();
  }
  const seen = new Set<number>();
  const parsed = results.map((item) => {
    if (
      !isRecord(item) ||
      !Number.isInteger(item.index) ||
      typeof item.ok !== 'boolean' ||
      (item.id !== undefined && typeof item.id !== 'string' && typeof item.id !== 'number') ||
      (item.recordNumber !== undefined && typeof item.recordNumber !== 'string') ||
      (item.recordName !== undefined && typeof item.recordName !== 'string') ||
      (item.status !== undefined && !Number.isInteger(item.status)) ||
      (item.error !== undefined && typeof item.error !== 'string')
    ) {
      throw invalid();
    }
    const index = item.index as number;
    if (index < 0 || index >= results.length || seen.has(index)) throw invalid();
    seen.add(index);
    return {
      index,
      ok: item.ok,
      id: item.id as string | number | undefined,
      recordNumber: item.recordNumber as string | undefined,
      recordName: item.recordName as string | undefined,
      status: item.status as number | undefined,
      error: item.error as string | undefined,
    };
  });
  if (parsed.filter((row) => row.ok).length !== succeeded) throw invalid();
  return {
    submitted,
    succeeded,
    failed,
    results: parsed,
  };
}

export function defaultHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getCsrfToken();
  if (token) headers[CSRF_HEADER_NAME] = token;
  return headers;
}

function jsonInit(method: string, body?: unknown, signal?: AbortSignal): RequestInit {
  const headers = defaultHeaders();
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  return {
    method,
    credentials: 'include',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  };
}

async function primeCsrf(): Promise<void> {
  if (getCookieCsrfToken()) return;
  const response = await fetch(`${API}/health`, { credentials: 'include' });
  captureCsrfToken(response);
}

async function performRefresh(): Promise<void> {
  await primeCsrf();
  const response = await fetch(`${API}/auth/refresh`, jsonInit('POST'));
  captureCsrfToken(response);
  if (!response.ok) throw await parseError(response);
}

export async function refreshSession(): Promise<void> {
  if (!refreshPromise) {
    refreshPromise = performRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  await refreshPromise;
}

async function fetchAuthenticated(
  url: string,
  options: RequestInit,
  canRefresh = true
): Promise<Response> {
  const send = () =>
    fetch(url, {
      ...options,
      credentials: 'include',
      headers: withCurrentCsrf(options.headers),
    });
  const response = await send();
  captureCsrfToken(response);
  if (response.status !== 401 || !canRefresh || options.signal?.aborted) {
    return response;
  }
  await refreshSession();
  const retry = await send();
  captureCsrfToken(retry);
  return retry;
}

async function fetchWithRetry(
  url: string,
  options: RequestInit = {},
  retries = 3,
  backoff = 300
): Promise<Response> {
  try {
    const response = await fetchAuthenticated(url, options);
    const method = options.method?.toUpperCase() || 'GET';
    const isSafeMethod = ['GET', 'HEAD', 'OPTIONS'].includes(method);
    if (response.status >= 500 && isSafeMethod && retries > 0) {
      if (options.signal?.aborted) {
        throw new DOMException('The operation was aborted.', 'AbortError');
      }
      await new Promise((resolve) => setTimeout(resolve, backoff));
      if (options.signal?.aborted) {
        throw new DOMException('The operation was aborted.', 'AbortError');
      }
      return fetchWithRetry(url, options, retries - 1, backoff * 2);
    }
    return response;
  } catch (err) {
    if (options.signal?.aborted) throw err;
    const method = options.method?.toUpperCase() || 'GET';
    const isSafeMethod = ['GET', 'HEAD', 'OPTIONS'].includes(method);
    if (isSafeMethod && retries > 0) {
      await new Promise((resolve) => setTimeout(resolve, backoff));
      return fetchWithRetry(url, options, retries - 1, backoff * 2);
    }
    throw err;
  }
}

export async function login(
  username: string,
  password = ''
): Promise<Identity> {
  await primeCsrf();
  const response = await fetch(`${API}/auth/login`, jsonInit('POST', {
    username,
    password,
  }));
  captureCsrfToken(response);
  if (!response.ok) throw await parseError(response);
  const data: unknown = await response.json();
  if (
    data &&
    typeof data === 'object' &&
    'employee' in data &&
    data.employee &&
    typeof data.employee === 'object'
  ) {
    return data.employee as Identity;
  }
  return data as Identity;
}

export async function getSession(): Promise<Identity | null> {
  let response = await fetchAuthenticated(
    `${API}/auth/session`,
    { credentials: 'include' },
    false
  );
  if (response.status === 401) {
    try {
      await refreshSession();
      response = await fetchAuthenticated(
        `${API}/auth/session`,
        { credentials: 'include' },
        false
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return null;
      throw err;
    }
  }
  if (response.status === 401) return null;
  if (!response.ok) throw await parseError(response);
  return response.json();
}

export async function logout(): Promise<void> {
  await primeCsrf();
  const response = await fetch(`${API}/auth/logout`, jsonInit('POST'));
  captureCsrfToken(response);
  if (!response.ok && response.status !== 401) throw await parseError(response);
  csrfToken = null;
}

export async function chatStream(
  messages: ChatMessage[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const history = messages
    .filter((message) => message.content.trim().length > 0)
    .slice(-MAX_CHAT_MESSAGES)
    .map((message) => ({
      role: message.role,
      content: message.content.slice(0, MAX_CHAT_CONTENT_LENGTH),
    }));
  const controller = new AbortController();
  const abortHandler = () => controller.abort();
  if (signal?.aborted) {
    controller.abort();
  } else {
    signal?.addEventListener('abort', abortHandler, { once: true });
  }
  try {
    const response = await fetchAuthenticated(
      `${API}/chat`,
      jsonInit('POST', { messages: history }, controller.signal)
    );
    if (!response.ok) throw await parseError(response);
    await readSse(response, onEvent, controller.signal);
  } catch (err) {
    if (controller.signal.aborted) return;
    throw err;
  } finally {
    signal?.removeEventListener('abort', abortHandler);
  }
}

export async function tts(
  text: string,
  rate = 1,
  signal?: AbortSignal
): Promise<Blob> {
  const response = await fetchAuthenticated(
    `${API}/tts`,
    jsonInit('POST', { text: text.slice(0, MAX_TTS_LENGTH), rate }, signal)
  );
  if (!response.ok) throw await parseError(response);
  return response.blob();
}

export async function getAssignments(
  signal?: AbortSignal
): Promise<AssignmentsResponse> {
  const response = await fetchWithRetry(`${API}/labour/assignments`, {
    credentials: 'include',
    signal,
  });
  if (!response.ok) throw await parseError(response);
  return response.json();
}

export async function submitTimecard(
  entries: TimecardEntry[]
): Promise<SubmitResponse> {
  const response = await fetchAuthenticated(
    `${API}/otl/timecard`,
    jsonInit('POST', { entries })
  );
  if (!response.ok) throw await parseError(response);
  return parseSubmitResponse(await response.json());
}

export async function listTimecards(
  limit = 25,
  offset = 0,
  signal?: AbortSignal
): Promise<TimecardsResponse> {
  const response = await fetchWithRetry(
    `${API}/otl/timecards?limit=${limit}&offset=${offset}`,
    { credentials: 'include', signal },
    0
  );
  if (!response.ok) throw await parseError(response);
  return response.json();
}

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetchWithRetry(`${API}/health`);
  if (!response.ok) throw await parseError(response);
  return response.json();
}

export async function getHealthOtl(
  signal?: AbortSignal
): Promise<{
  ok: boolean;
  username?: string;
}> {
  const response = await fetchWithRetry(
    `${API}/health/otl`,
    { credentials: 'include', signal },
    0
  );
  if (!response.ok) throw await parseError(response);
  return response.json();
}

export async function refreshCatalogue(): Promise<{
  isLoaded: boolean;
  isLoading: boolean;
  totalProjects: number;
  totalPersonsIndexed: number;
  catalogueAgeSeconds?: number;
  refreshIntervalSeconds: number;
}> {
  const response = await fetchAuthenticated(
    `${API}/admin/refresh-catalogue`,
    jsonInit('POST')
  );
  if (!response.ok) throw await parseError(response);
  return response.json();
}

export async function getCatalogueStatus(): Promise<{
  isLoaded: boolean;
  isLoading: boolean;
  totalProjects: number;
  totalPersonsIndexed: number;
  catalogueAgeSeconds?: number;
  refreshIntervalSeconds: number;
}> {
  const response = await fetchWithRetry(`${API}/admin/catalogue-status`);
  if (!response.ok) throw await parseError(response);
  return response.json();
}
