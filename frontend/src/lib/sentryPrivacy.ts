

export const REDACTED = '[redacted]';


const SENSITIVE_KEY = new RegExp(
  [
    'pass(word|wd)?',
    'pwd',
    'secret',
    'token',
    'api[-_]?key',
    'apikey',
    'auth(horization)?',
    'credential',
    'private[-_]?key',
    'client[-_]?secret',
    'session[-_]?id',
    'session',
    'cookie',
    'otp',
    'cvv',
    'pin',
    'ssn',
  ].join('|'),
  'i'
);


const PEM_PRIVATE_KEY =
  /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----/g;


const BEARER_TOKEN = /\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]{8,}=*/gi;


const JWT = /\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*/g;


const CREDENTIAL_ASSIGNMENT =
  /(["']?\b(?:pass(?:word|wd)?|pwd|secret|token|api[-_]?key|apikey|auth(?:orization)?|client[-_]?secret|private[-_]?key)\b["']?\s*[:=]\s*)(?!(?:bearer|basic|digest|token)\b)(?:"[^"]*"|'[^']*'|[^\s"',;)\]}{[]+)/gi;


export function isSensitiveKey(key: string): boolean {
  return SENSITIVE_KEY.test(key);
}


export function containsCredential(value: string): boolean {
  PEM_PRIVATE_KEY.lastIndex = 0;
  BEARER_TOKEN.lastIndex = 0;
  JWT.lastIndex = 0;
  CREDENTIAL_ASSIGNMENT.lastIndex = 0;
  return (
    PEM_PRIVATE_KEY.test(value) ||
    BEARER_TOKEN.test(value) ||
    JWT.test(value) ||
    CREDENTIAL_ASSIGNMENT.test(value)
  );
}


export function scrubString(value: string): string {
  return value
    .replace(PEM_PRIVATE_KEY, REDACTED)
    .replace(BEARER_TOKEN, (match) => `${match.split(/\s+/)[0]} ${REDACTED}`)
    .replace(JWT, REDACTED)
    .replace(
      CREDENTIAL_ASSIGNMENT,
      (_match, prefix: string) => `${prefix}${REDACTED}`
    );
}

const isPlainish = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;


export function scrubValue<T>(
  value: T,
  seen: WeakSet<object> = new WeakSet()
): T {
  if (typeof value === 'string') return scrubString(value) as unknown as T;
  if (typeof value === 'bigint') return `${value}` as unknown as T;
  if (!isPlainish(value)) return value;

  if (seen.has(value)) return '[circular]' as unknown as T;
  seen.add(value);

  if (Array.isArray(value)) {
    return value.map((item) => scrubValue(item, seen)) as unknown as T;
  }

  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (isSensitiveKey(key)) {
      out[key] = REDACTED;
      continue;
    }
    out[key] = scrubValue(item, seen);
  }
  return out as unknown as T;
}


export function scrubStorageSnapshot(
  store: Pick<Storage, 'length' | 'key'> | undefined | null = typeof window ===
  'undefined'
    ? undefined
    : window.localStorage
): Record<string, unknown> {
  if (!store || typeof store.key !== 'function') return {};
  try {
    const keys: string[] = [];
    for (let i = 0; i < store.length; i += 1) {
      const key = store.key(i);
      if (key !== null) keys.push(key);
    }
    return keys.length > 0 ? { localStorageKeys: keys.sort() } : {};
  } catch {
    return {};
  }
}


interface HttpLike {
  url?: unknown;
  query_string?: unknown;
  headers?: unknown;
  cookies?: unknown;
  data?: unknown;
  env?: unknown;
  body?: unknown;
}


function scrubCookies(cookies: unknown): unknown {
  if (typeof cookies === 'string') return REDACTED;
  if (Array.isArray(cookies)) {
    return cookies.map((cookie) =>
      isPlainish(cookie) ? { ...cookie, value: REDACTED } : cookie
    );
  }
  if (!isPlainish(cookies)) return cookies;
  const out: Record<string, unknown> = {};
  for (const name of Object.keys(cookies)) out[name] = REDACTED;
  return out;
}


function scrubHttpSection(section: unknown): unknown {
  if (!isPlainish(section)) return section;
  const http = { ...(section as HttpLike) };
  if (http.headers !== undefined) http.headers = scrubValue(http.headers);
  if (http.cookies !== undefined) http.cookies = scrubCookies(http.cookies);
  if (http.data !== undefined) http.data = scrubValue(http.data);
  if (http.body !== undefined) http.body = scrubValue(http.body);
  if (http.env !== undefined) http.env = scrubValue(http.env);
  if (http.query_string !== undefined) {
    http.query_string =
      typeof http.query_string === 'string'
        ? REDACTED
        : scrubValue(http.query_string);
  }
  if (typeof http.url === 'string') http.url = scrubString(http.url);
  return http;
}


export function scrubEvent<T>(event: T): T {
  if (!isPlainish(event)) return event;
  const out: Record<string, unknown> = { ...event };

  if (typeof out.message === 'string') out.message = scrubString(out.message);
  if (typeof out.transaction === 'string') {
    out.transaction = scrubString(out.transaction);
  }
  if (out.user !== undefined) out.user = scrubValue(out.user);
  if (out.extra !== undefined) out.extra = scrubValue(out.extra);
  if (out.contexts !== undefined) out.contexts = scrubValue(out.contexts);
  if (out.tags !== undefined) out.tags = scrubValue(out.tags);

  if (out.request !== undefined) out.request = scrubHttpSection(out.request);
  if (out.response !== undefined) {
    out.response = scrubHttpSection(out.response);
  }

  if (Array.isArray(out.breadcrumbs)) {
    out.breadcrumbs = out.breadcrumbs.map((crumb) => {
      if (!isPlainish(crumb)) return crumb;
      const next: Record<string, unknown> = { ...crumb };
      if (typeof next.message === 'string') {
        next.message = scrubString(next.message);
      }
      if (next.data !== undefined) next.data = scrubValue(next.data);
      return next;
    });
  }

  const storage = scrubStorageSnapshot();
  if (Object.keys(storage).length > 0) {
    out.contexts = {
      ...(isPlainish(out.contexts) ? out.contexts : {}),
      storage,
    };
  }

  return out as unknown as T;
}


export function scrubTransaction<T>(event: T): T {
  return scrubEvent(event);
}


export const DENY_URLS: RegExp[] = [
  /\/api\/auth\//i,
  /\/auth\/(login|logout|token|refresh|verify|otp)/i,
  /\/oauth2?\//i,
  /sentry\.io\//i,
];
