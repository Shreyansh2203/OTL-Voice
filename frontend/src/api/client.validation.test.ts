import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  defaultHeaders,
  getAssignments,
  getCatalogueStatus,
  getHealth,
  getHealthOtl,
  getWsApiUrl,
  listTimecards,
  refreshCatalogue,
  submitTimecard,
  tts,
} from './client';

function response(body: unknown, status = 200, csrf?: string): Response {
  const headers = new Headers({ 'Content-Type': 'application/json' });
  if (csrf) headers.set('X-CSRF-Token', csrf);
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status,
    headers,
  });
}

function lastUrl(fetchMock: ReturnType<typeof vi.fn>): string {
  return String(fetchMock.mock.calls.at(-1)?.[0]);
}

describe('submit confirmation validation', () => {
  beforeEach(() => {
    document.cookie = 'csrf_token=tok; path=/';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const valid = (results: unknown[], extra: Record<string, unknown> = {}) => ({
    submitted: results.length,
    succeeded: results.filter((r) => (r as { ok: boolean }).ok).length,
    failed: results.filter((r) => !(r as { ok: boolean }).ok).length,
    results,
    ...extra,
  });

  it('accepts a well-formed confirmation and keeps every optional field', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response(
        valid([
          {
            index: 0,
            ok: true,
            id: 'R1',
            recordNumber: 'RN',
            recordName: 'Test',
            status: 1,
          },
          { index: 1, ok: false, error: 'rejected' },
        ]),
        200,
        'fresh'
      )
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await submitTimecard([]);

    expect(result.submitted).toBe(2);
    expect(result.succeeded).toBe(1);
    expect(result.failed).toBe(1);
    expect(result.results[0]).toEqual({
      index: 0,
      ok: true,
      id: 'R1',
      recordNumber: 'RN',
      recordName: 'Test',
      status: 1,
      error: undefined,
    });
    expect(result.results[1].error).toBe('rejected');
  });

  it.each([
    ['a JSON null body', null],
    ['a missing results list', { submitted: 0, succeeded: 0, failed: 0 }],
    [
      'a non-integer counter',
      {
        submitted: 1.5,
        succeeded: 1,
        failed: 0,
        results: [{ index: 0, ok: true }],
      },
    ],
    [
      'a counter that disagrees with the result count',
      {
        submitted: 2,
        succeeded: 1,
        failed: 0,
        results: [{ index: 0, ok: true }],
      },
    ],
    [
      'a zero submission count',
      { submitted: 0, succeeded: 0, failed: 0, results: [] },
    ],
    [
      'a success total that does not match the rows',
      {
        submitted: 1,
        succeeded: 1,
        failed: 0,
        results: [{ index: 0, ok: false }],
      },
    ],
  ])('rejects %s as uncertain', async (_label, body) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));
    await expect(submitTimecard([])).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    ['a row that is not an object', ['nope']],
    ['a row without an index', [{ ok: true }]],
    ['a row without a boolean ok', [{ index: 0 }]],
    ['a row with a bad id', [{ index: 0, ok: true, id: {} }]],
    [
      'a row with a bad recordNumber',
      [{ index: 0, ok: true, recordNumber: 4 }],
    ],
    ['a row with a bad recordName', [{ index: 0, ok: true, recordName: 4 }]],
    ['a row with a bad status', [{ index: 0, ok: true, status: 1.5 }]],
    ['a row with a bad error', [{ index: 0, ok: true, error: 4 }]],
    ['a negative index', [{ index: -1, ok: true }]],
    ['an out-of-range index', [{ index: 3, ok: true }]],
  ])('rejects %s as uncertain', async (_label, results) => {
    const succeeded = results.filter(
      (r) => (r as { ok?: boolean })?.ok === true
    ).length;
    const body = {
      submitted: results.length,
      succeeded,
      failed: results.length - succeeded,
      results,
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));
    await expect(submitTimecard([])).rejects.toBeInstanceOf(ApiError);
  });

  it('rejects a duplicated row index', async () => {
    const body = {
      submitted: 2,
      succeeded: 2,
      failed: 0,
      results: [
        { index: 0, ok: true },
        { index: 0, ok: true },
      ],
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));
    await expect(submitTimecard([])).rejects.toBeInstanceOf(ApiError);
  });

  it('keeps the per-row requestId and replayed flag the server sends', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        response(
          valid([
            {
              index: 0,
              ok: true,
              id: 'R1',
              requestId: 'request-1',
              replayed: true,
            },
            {
              index: 1,
              ok: false,
              status: 503,
              error: 'Oracle Cloud is temporarily unavailable.',
              requestId: 'request-2',
            },
          ]),
          200,
          'fresh'
        )
      )
    );

    const result = await submitTimecard([]);

    // Without these the client cannot tell a replayed write from a fresh one,
    // which is the only way to know a same-key retry is pointless.
    expect(result.results[0]).toMatchObject({
      requestId: 'request-1',
      replayed: true,
    });
    expect(result.results[1]).toMatchObject({
      requestId: 'request-2',
      replayed: undefined,
    });
  });

  it.each([
    [
      'a row with a non-string requestId',
      [{ index: 0, ok: true, requestId: 7 }],
    ],
    [
      'a row with a non-boolean replayed flag',
      [{ index: 0, ok: true, replayed: 'yes' }],
    ],
  ])('rejects %s as uncertain', async (_label, results) => {
    const body = {
      submitted: results.length,
      succeeded: results.length,
      failed: 0,
      results,
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));
    await expect(submitTimecard([])).rejects.toBeInstanceOf(ApiError);
  });

  it('surfaces a server rejection verbatim', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(response({ detail: 'fusion is down' }, 502))
    );
    await expect(submitTimecard([])).rejects.toMatchObject({
      status: 502,
      message: 'fusion is down',
    });
  });

  it('falls back to the status text when the body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(new Response('<html>oops</html>', { status: 503 }))
    );
    await expect(submitTimecard([])).rejects.toMatchObject({ status: 503 });
  });
});

describe('websocket url derivation', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('maps a relative API onto the current page origin', () => {
    expect(getWsApiUrl('/stt/stream')).toBe(
      'ws://localhost:3000/api/stt/stream'
    );
  });

  it('upgrades an https page to a secure websocket', () => {
    const original = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { protocol: 'https:', host: 'otl.example.com' },
    });
    try {
      expect(getWsApiUrl('/stt/stream')).toBe(
        'wss://otl.example.com/api/stt/stream'
      );
    } finally {
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: original,
      });
    }
  });

  it('rewrites an absolute http API to ws', async () => {
    vi.stubEnv('VITE_API_URL', 'http://10.0.0.5:8000/api');
    vi.resetModules();
    const module = await import('./client');
    expect(module.getWsApiUrl('/stt/stream')).toBe(
      'ws://10.0.0.5:8000/api/stt/stream'
    );
  });

  it('rewrites an absolute https API to wss', async () => {
    vi.stubEnv('VITE_API_URL', 'https://otl.example.com/api');
    vi.resetModules();
    const module = await import('./client');
    expect(module.getWsApiUrl('/stt/stream')).toBe(
      'wss://otl.example.com/api/stt/stream'
    );
  });
});

describe('csrf header construction', () => {
  beforeEach(() => {
    document.cookie = 'csrf_token=; Max-Age=0; path=/';
  });

  afterEach(() => {
    vi.resetModules();
  });

  it('omits the header when no token is available', async () => {
    // A fresh module registry so no earlier response has been captured.
    vi.resetModules();
    const module = await import('./client');
    expect(module.defaultHeaders()).toEqual({});
  });

  it('prefers the readable cookie over a captured header value', () => {
    document.cookie = 'csrf_token=cookie-token; path=/';
    expect(defaultHeaders()).toEqual({ 'X-CSRF-Token': 'cookie-token' });
  });
});

describe('reads that retry on a server error', () => {
  beforeEach(() => {
    document.cookie = 'csrf_token=tok; path=/';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('retries a safe read after a 503 and returns the eventual success', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ detail: 'busy' }, 503))
      .mockResolvedValueOnce(response({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
    const pending = getHealth();
    await vi.runAllTimersAsync();
    await expect(pending).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('gives up after the retry budget and reports the last failure', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(response({ detail: 'busy' }, 503));
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
    const pending = getHealth().catch((err: unknown) => err);
    await vi.runAllTimersAsync();
    const error = await pending;
    expect(error).toMatchObject({ status: 503, message: 'busy' });
    expect(fetchMock.mock.calls.length).toBe(4);
  });

  it('does not retry a state-changing request', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(response({ detail: 'busy' }, 503));
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
    const pending = refreshCatalogue().catch((err: unknown) => err);
    await vi.runAllTimersAsync();
    expect(await pending).toMatchObject({ status: 503 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('aborts a retrying read instead of issuing the next attempt', async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockImplementation(async () => {
      controller.abort();
      return response({ detail: 'busy' }, 503);
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
    const pending = getAssignments(controller.signal).catch(
      (err: unknown) => err
    );
    await vi.runAllTimersAsync();
    expect(await pending).toBeInstanceOf(DOMException);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('surfaces a read failure whose body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response('nope', { status: 502, statusText: 'Bad GW' })
        )
    );
    await expect(getAssignments()).rejects.toMatchObject({
      status: 502,
      message: 'Bad GW',
    });
  });

  it('returns the catalogue status shape', async () => {
    const body = {
      isLoaded: true,
      isLoading: false,
      totalProjects: 3,
      totalPersonsIndexed: 4,
      catalogueAgeSeconds: 12,
      refreshIntervalSeconds: 21600,
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));
    await expect(getCatalogueStatus()).resolves.toEqual(body);
  });

  it('rejects a failed catalogue refresh', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(response({ detail: 'forbidden' }, 403))
    );
    await expect(refreshCatalogue()).rejects.toMatchObject({
      status: 403,
      message: 'forbidden',
    });
  });

  it('passes the requested window through to the timecard list', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ items: [] }));
    vi.stubGlobal('fetch', fetchMock);
    await listTimecards(5, 10);
    expect(lastUrl(fetchMock)).toBe('/api/otl/timecards?limit=5&offset=10');
  });

  it('returns the OCI health probe result', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(response({ ok: true, username: 'svc' }))
    );
    await expect(getHealthOtl()).resolves.toEqual({
      ok: true,
      username: 'svc',
    });
  });

  it('rejects a failed OCI health probe', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(response({ detail: 'unreachable' }, 500))
    );
    await expect(getHealthOtl()).rejects.toMatchObject({ status: 500 });
  });
});

describe('tts', () => {
  beforeEach(() => {
    document.cookie = 'csrf_token=tok; path=/';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('truncates the requested text to the server limit', async () => {
    // A string body rather than a Blob: undici streams a Blob body via
    // Blob.stream(), which the Blob provided by the test environment does not
    // implement on every Node version. The response content is irrelevant here,
    // only the outgoing request body is asserted.
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response('audio', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const blob = await tts('x'.repeat(5000), 1.5);

    expect(blob.size).toBeGreaterThan(0);
    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit & { body: string }).body
    );
    expect(body.text).toHaveLength(2000);
    expect(body.rate).toBe(1.5);
  });

  it('rejects a synthesis failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(response({ detail: 'no quota' }, 503))
    );
    await expect(tts('hello')).rejects.toMatchObject({
      status: 503,
      message: 'no quota',
    });
  });
});
