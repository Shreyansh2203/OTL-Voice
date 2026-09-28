import { describe, expect, it, vi } from 'vitest';
import {
  DENY_URLS,
  REDACTED,
  containsCredential,
  isSensitiveKey,
  scrubEvent,
  scrubStorageSnapshot,
  scrubString,
  scrubTransaction,
  scrubValue,
} from './sentryPrivacy';

const JWT =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r';

const PEM = `-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAtSomePrivateKeyMaterialForTesting/1234567890abcdef
ghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/abcdefgh
-----END RSA PRIVATE KEY-----`;

type Rec = Record<string, unknown>;

/** `scrubEvent` preserves its input type, so tests read fields through this. */
const rec = (value: unknown): Rec => value as Rec;

describe('isSensitiveKey', () => {
  it.each([
    'password',
    'passwd',
    'pwd',
    'Password',
    'PASSWORD',
    'token',
    'refreshToken',
    'apiKey',
    'api_key',
    'API-KEY',
    'apikey',
    'secret',
    'clientSecret',
    'authorization',
    'credential',
    'privateKey',
    'sessionId',
    'cookie',
    'otp',
    'cvv',
    'ssn',
  ])('flags %s', (key) => {
    expect(isSensitiveKey(key)).toBe(true);
  });

  it.each(['name', 'projectId', 'hours', 'entryDate', 'status', 'url'])(
    'leaves %s alone',
    (key) => {
      expect(isSensitiveKey(key)).toBe(false);
    }
  );
});

describe('scrubString', () => {
  it('leaves ordinary text untouched', () => {
    const text = 'Failed to submit 3 entries for project PRJ-1 on 2026-09-25.';
    expect(scrubString(text)).toBe(text);
    expect(containsCredential(text)).toBe(false);
  });

  it('redacts bearer and basic authorization headers', () => {
    expect(scrubString('Authorization: Bearer abc123def456ghi789')).toBe(
      `Authorization: Bearer ${REDACTED}`
    );
    expect(scrubString('used Basic dXNlcjpwYXNzd29yZA== to authenticate')).toBe(
      `used Basic ${REDACTED} to authenticate`
    );
  });

  it('redacts a bare JWT anywhere in the text', () => {
    expect(scrubString(`rejected token ${JWT} for request`)).toBe(
      `rejected token ${REDACTED} for request`
    );
  });

  it('redacts an inline PEM private key block', () => {
    const text = `signing failed\n${PEM}\ntrailer`;
    const out = scrubString(text);
    expect(out).not.toContain(
      'MIIEowIBAAKCAQEAtSomePrivateKeyMaterialForTesting'
    );
    expect(out).not.toContain('BEGIN RSA PRIVATE KEY');
    expect(out).toContain(REDACTED);
    expect(out).toContain('signing failed');
    expect(out).toContain('trailer');
  });

  it.each([
    'password=hunter2',
    'password: hunter2',
    '"password": "hunter2"',
    'apiKey=sk-live-1234',
    'token: abc.def',
    'secret="s3cr3t"',
    'authorization=Bearer abc123def456',
  ])('redacts the credential assignment in %s', (text) => {
    const out = scrubString(text);
    expect(out).toContain(REDACTED);
    expect(out).not.toMatch(/hunter2|sk-live-1234|s3cr3t/);
  });

  it('is idempotent', () => {
    const once = scrubString(`password=hunter2 ${JWT}`);
    expect(scrubString(once)).toBe(once);
  });

  it('is stateless across calls despite the shared global regexes', () => {
    for (let i = 0; i < 3; i += 1) {
      expect(scrubString(`password=hunter2`)).toBe(`password=${REDACTED}`);
      expect(containsCredential(`password=hunter2`)).toBe(true);
      expect(containsCredential('nothing to see here')).toBe(false);
    }
  });
});

describe('scrubValue', () => {
  it('replaces sensitive keys at any depth', () => {
    const out = scrubValue({
      username: '7',
      password: 'testpass',
      nested: { apiKey: 'sk-live-1', keep: 'value' },
      list: [{ token: 'abc' }],
    });
    expect(out).toEqual({
      username: '7',
      password: REDACTED,
      nested: { apiKey: REDACTED, keep: 'value' },
      list: [{ token: REDACTED }],
    });
  });

  it('scrubs credentials hiding inside otherwise safe values', () => {
    const out = scrubValue({ note: 'retried with password=hunter2' });
    expect(out.note).toBe(`retried with password=${REDACTED}`);
  });

  it('maps arrays and preserves primitives', () => {
    expect(scrubValue(['a', 'password=x'])).toEqual([
      'a',
      `password=${REDACTED}`,
    ]);
    expect(scrubValue(42)).toBe(42);
    expect(scrubValue(true)).toBe(true);
    expect(scrubValue(null)).toBe(null);
    expect(scrubValue(undefined)).toBe(undefined);
  });

  it('stringifies bigints instead of throwing', () => {
    expect(scrubValue({ big: 10n })).toEqual({ big: '10' });
  });

  it('collapses circular references rather than recursing forever', () => {
    const node: Record<string, unknown> = { name: 'root' };
    node.self = node;
    const out = scrubValue(node) as Record<string, unknown>;
    expect(out.name).toBe('root');
    expect(out.self).toBe('[circular]');
  });

  it('does not mutate the input', () => {
    const input = { password: 'testpass' };
    scrubValue(input);
    expect(input.password).toBe('testpass');
  });
});

describe('scrubStorageSnapshot', () => {
  const stub = (keys: string[]): Pick<Storage, 'length' | 'key'> => ({
    length: keys.length,
    key: (i: number) => keys[i] ?? null,
  });

  it('records key names only, sorted, never values', () => {
    const out = scrubStorageSnapshot(stub(['otl_user', 'otl_token']));
    expect(out).toEqual({ localStorageKeys: ['otl_token', 'otl_user'] });
    expect(JSON.stringify(out)).not.toContain('secret-value');
  });

  it('returns an empty object when storage is unavailable', () => {
    expect(scrubStorageSnapshot(null)).toEqual({});
    expect(scrubStorageSnapshot(undefined)).toEqual({});
  });

  it('returns an empty object when storage is empty', () => {
    expect(scrubStorageSnapshot(stub([]))).toEqual({});
  });

  it('returns an empty object when key() is not implemented', () => {
    const partial = { length: 3 } as unknown as Pick<Storage, 'length' | 'key'>;
    expect(scrubStorageSnapshot(partial)).toEqual({});
  });

  it('returns an empty object when storage access throws', () => {
    const hostile = {
      length: 1,
      key: () => {
        throw new Error('SecurityError');
      },
    } as unknown as Pick<Storage, 'length' | 'key'>;
    expect(scrubStorageSnapshot(hostile)).toEqual({});
  });
});

describe('scrubEvent', () => {
  it('redacts request headers, cookies, and bodies', () => {
    const out = rec(
      scrubEvent({
        message: 'request failed',
        request: {
          url: 'https://otl.example.com/api/auth/login?token=abc123',
          query_string: 'token=abc123',
          headers: {
            'Content-Type': 'application/json',
            Authorization: 'Bearer abc123def456',
          },
          cookies: { session: 'sess-1', theme: 'dark' },
          data: { personNumber: '7', password: 'testpass' },
        },
      })
    );
    const request = rec(out.request);

    expect(request.headers).toEqual({
      'Content-Type': 'application/json',
      Authorization: REDACTED,
    });
    expect(request.cookies).toEqual({ session: REDACTED, theme: REDACTED });
    expect(request.data).toEqual({ personNumber: '7', password: REDACTED });
    expect(request.query_string).toBe(REDACTED);
    // The query string inside the URL is scrubbed too, not just `query_string`.
    expect(request.url).toBe(
      `https://otl.example.com/api/auth/login?token=${REDACTED}`
    );
  });

  it('redacts every cookie value while keeping the names', () => {
    const out = rec(
      scrubEvent({
        request: { cookies: { sid: 'a', _ga: 'b', theme: 'dark' } },
      })
    );
    expect(rec(out.request).cookies).toEqual({
      sid: REDACTED,
      _ga: REDACTED,
      theme: REDACTED,
    });
  });

  it('redacts a cookie list and a raw cookie header string', () => {
    const list = rec(
      scrubEvent({
        request: { cookies: [{ name: 'sid', value: 'abc', httpOnly: true }] },
      })
    );
    expect(rec(list.request).cookies).toEqual([
      { name: 'sid', value: REDACTED, httpOnly: true },
    ]);
    const header = rec(
      scrubEvent({ request: { cookies: 'sid=abc; theme=dark' } })
    );
    expect(rec(header.request).cookies).toBe(REDACTED);
  });

  it('redacts response data and headers', () => {
    const out = rec(
      scrubEvent({
        response: {
          statusCode: 401,
          headers: { 'Set-Cookie': 'sid=abc' },
          data: { token: 'abc' },
        },
      })
    );
    expect(rec(out.response).headers).toEqual({ 'Set-Cookie': REDACTED });
    expect(rec(out.response).data).toEqual({ token: REDACTED });
  });

  it('scrubs user, extra, contexts, and tags', () => {
    const out = rec(
      scrubEvent({
        user: { id: '7', ip_address: '10.0.0.1', username: 'mala' },
        extra: { apiKey: 'sk-live-1', retry: 2 },
        contexts: { device: { name: 'iPad' }, auth: { token: 'abc' } },
        tags: { secret: 'shh', env: 'test' },
      })
    );
    const contexts = rec(out.contexts);
    expect(out.user).toEqual({
      id: '7',
      ip_address: '10.0.0.1',
      username: 'mala',
    });
    expect(out.extra).toEqual({ apiKey: REDACTED, retry: 2 });
    expect(contexts.device).toEqual({ name: 'iPad' });
    // A key named `auth` is dropped whole, including its subtree.
    expect(contexts.auth).toBe(REDACTED);
    expect(out.tags).toEqual({ secret: REDACTED, env: 'test' });
  });

  it('scrubs breadcrumb messages and data', () => {
    const out = rec(
      scrubEvent({
        breadcrumbs: [
          {
            message: 'login password=hunter2',
            data: { password: 'hunter2', page: '/login' },
          },
          { message: 'clicked submit' },
          'not-an-object',
        ],
      })
    );
    const crumbs = out.breadcrumbs as Rec[];
    expect(crumbs[0].message).toBe(`login password=${REDACTED}`);
    expect(crumbs[0].data).toEqual({ password: REDACTED, page: '/login' });
    expect(crumbs[1]).toEqual({ message: 'clicked submit' });
    expect(crumbs[2]).toBe('not-an-object');
  });

  it('redacts credential shapes in the top-level message and transaction', () => {
    expect(scrubEvent({ message: `login failed for ${JWT}` }).message).toBe(
      `login failed for ${REDACTED}`
    );
    // A token carried in a transaction name is scrubbed rather than kept.
    expect(scrubEvent({ transaction: 'POST /api?token=abc' }).transaction).toBe(
      `POST /api?token=${REDACTED}`
    );
  });

  it('attaches a redacted storage key inventory', () => {
    window.localStorage.setItem('otl_probe', 'value-not-sent');
    const out = rec(scrubEvent({ message: 'boom' }));
    expect(rec(out.contexts).storage).toEqual({
      localStorageKeys: ['otl_probe'],
    });
    expect(JSON.stringify(out)).not.toContain('value-not-sent');
  });

  it('omits the storage context when storage is empty', () => {
    expect(rec(scrubEvent({})).contexts).toBeUndefined();
    expect(rec(scrubEvent({ message: 'boom' })).contexts).toBeUndefined();
  });

  it('tolerates an empty or non-object event', () => {
    expect(scrubEvent({})).toEqual({});
    expect(scrubEvent({ message: 'no http sections here' }).message).toBe(
      'no http sections here'
    );
  });

  it('does not mutate the caller-supplied event', () => {
    const event = {
      request: { headers: { authorization: 'Bearer abc123def456' } },
    };
    scrubEvent(event);
    expect(event.request.headers.authorization).toBe('Bearer abc123def456');
  });
});

describe('scrubTransaction', () => {
  it('applies the same scrubbing to transaction payloads', () => {
    const out = rec(
      scrubTransaction({
        transaction: 'POST /api/timesheets',
        request: { headers: { Authorization: 'Bearer abc123def456' } },
        spans: [{ description: 'select', data: { sql: 'SELECT 1' } }],
      })
    );
    expect(rec(rec(out.request).headers).Authorization).toBe(REDACTED);
    expect((out.spans as Rec[])[0].description).toBe('select');
  });
});

describe('DENY_URLS', () => {
  it.each([
    'https://otl.example.com/api/auth/login',
    'https://otl.example.com/auth/refresh',
    'https://otl.example.com/oauth2/authorize',
    'https://o123.ingest.sentry.io/api/123/envelope',
  ])('denies %s', (url) => {
    expect(DENY_URLS.some((pattern) => pattern.test(url))).toBe(true);
  });

  it.each([
    'https://otl.example.com/api/timesheets',
    'https://otl.example.com/api/projects',
  ])('allows %s', (url) => {
    expect(DENY_URLS.some((pattern) => pattern.test(url))).toBe(false);
  });

  it('has no stateful lastIndex across calls', () => {
    for (let i = 0; i < 3; i += 1) {
      expect(DENY_URLS.some((pattern) => pattern.test('/api/auth/login'))).toBe(
        true
      );
    }
  });
});

describe('scrubbed payload is JSON-serialisable', () => {
  it('survives JSON.stringify for a realistic event', () => {
    const event = scrubEvent({
      message: `boom ${JWT}`,
      request: {
        url: 'https://otl.example.com/api/timesheets',
        data: { password: 'testpass' },
      },
      breadcrumbs: [{ message: 'nav', data: { to: '/chat' } }],
    });
    const round = JSON.parse(JSON.stringify(event)) as Record<string, unknown>;
    expect(JSON.stringify(round)).not.toContain('testpass');
    expect(JSON.stringify(round)).not.toContain(JWT);
    expect(vi.isMockFunction(console.error)).toBe(false);
  });
});
