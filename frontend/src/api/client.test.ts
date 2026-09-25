import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  chatStream,
  getSession,
  login,
  logout,
  submitTimecard,
} from './client';

function response(body: unknown, status = 200, csrf?: string): Response {
  const headers = new Headers({ 'Content-Type': 'application/json' });
  if (csrf) headers.set('X-CSRF-Token', csrf);
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status,
    headers,
  });
}

function headersFor(call: unknown[]): Headers {
  const init = call[1] as RequestInit | undefined;
  return new Headers(init?.headers);
}

describe('cookie and CSRF client flow', () => {
  beforeEach(() => {
    document.cookie = 'csrf_token=; Max-Age=0; path=/';
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('primes CSRF before login and uses an HttpOnly session cookie', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ ok: true }, 200, 'primed-token'))
      .mockResolvedValueOnce(
        response({ username: '7', fullName: 'Mala Kumari', employeeId: '7' })
      );
    vi.stubGlobal('fetch', fetchMock);

    const identity = await login('7', 'secret');

    expect(identity.employeeId).toBe('7');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const loginCall = fetchMock.mock.calls[1];
    expect(loginCall[0]).toBe('/api/auth/login');
    expect((loginCall[1] as RequestInit).credentials).toBe('include');
    expect(headersFor(loginCall).get('X-CSRF-Token')).toBe('primed-token');
    expect(localStorage.getItem('otl_session')).toBeNull();
  });

  it('retries a submission with the newly rotated CSRF token after refresh', async () => {
    document.cookie = 'csrf_token=old-token; path=/';
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ detail: 'expired' }, 401))
      .mockImplementationOnce(async () => {
        const result = response({ ok: true }, 200, 'new-token');
        document.cookie = 'csrf_token=new-token; path=/';
        return result;
      })
      .mockResolvedValueOnce(
        response({
          submitted: 1,
          succeeded: 1,
          failed: 0,
          results: [{ index: 0, ok: true, id: 9001 }],
        })
      );
    vi.stubGlobal('fetch', fetchMock);

    await submitTimecard([
      {
        requestId: 'request-1',
        employeeNumber: '7',
        employeeName: 'Mala Kumari',
        projectId: 'PRJ-1',
        projectNo: 'PA-1',
        projectName: 'Operations',
        workOrder: 'WO-1',
        taskDetails: 'Task',
        hours: 1,
        date: '2026-09-25',
        currencyCode: 'USD',
      },
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(headersFor(fetchMock.mock.calls[0]).get('X-CSRF-Token')).toBe(
      'old-token'
    );
    expect(headersFor(fetchMock.mock.calls[1]).get('X-CSRF-Token')).toBe(
      'old-token'
    );
    expect(headersFor(fetchMock.mock.calls[2]).get('X-CSRF-Token')).toBe(
      'new-token'
    );
  });

  it('refreshes an expired session once and retries the session read', async () => {
    document.cookie = 'csrf_token=old-token; path=/';
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ detail: 'expired' }, 401))
      .mockImplementationOnce(async () => {
        const result = response({ ok: true }, 200, 'new-token');
        document.cookie = 'csrf_token=new-token; path=/';
        return result;
      })
      .mockResolvedValueOnce(
        response({ username: '7', fullName: 'Mala Kumari', employeeId: '7' })
      );
    vi.stubGlobal('fetch', fetchMock);

    await expect(getSession()).resolves.toMatchObject({ employeeId: '7' });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(headersFor(fetchMock.mock.calls[2]).get('X-CSRF-Token')).toBe(
      'new-token'
    );
  });

  it('rejects malformed submission confirmations as uncertain', async () => {
    document.cookie = 'csrf_token=test-token; path=/';
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        response({
          submitted: 1,
          succeeded: 0,
          failed: 0,
          results: [{ index: 0, ok: false }],
        })
      )
    );

    await expect(
      submitTimecard([
        {
          requestId: 'request-1',
          employeeNumber: '7',
          employeeName: 'Mala Kumari',
          projectId: 'PRJ-1',
          projectNo: 'PA-1',
          projectName: 'Operations',
          workOrder: 'WO-1',
          taskDetails: 'Task',
          hours: 1,
          date: '2026-09-25',
          currencyCode: 'USD',
        },
      ])
    ).rejects.toMatchObject({
      status: 502,
      message: expect.stringMatching(/invalid submission confirmation/i),
    });
  });

  it('returns null when both the session and refresh are unauthorized', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ detail: 'expired' }, 401))
      .mockResolvedValueOnce(response({ ok: true }, 200, 'rotated'))
      .mockResolvedValueOnce(response({ detail: 'expired' }, 401));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getSession()).resolves.toBeNull();
  });

  it('primes CSRF before logout and accepts an already expired session', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ ok: true }, 200, 'logout-token'))
      .mockResolvedValueOnce(response({ detail: 'expired' }, 401));
    vi.stubGlobal('fetch', fetchMock);

    await expect(logout()).resolves.toBeUndefined();
    expect(headersFor(fetchMock.mock.calls[1]).get('X-CSRF-Token')).toBe(
      'logout-token'
    );
    expect((fetchMock.mock.calls[1][1] as RequestInit).credentials).toBe('include');
  });

  it('surfaces non-authentication session failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ detail: 'down' }, 500)));

    await expect(getSession()).rejects.toBeInstanceOf(ApiError);
  });

  it('parses streamed assistant deltas without persisting auth tokens', async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'data: {"type":"assistant_delta","delta":"Hello"}\n\ndata: {"type":"done"}\n\n'
          )
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(stream, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        })
      )
    );

    const deltas: string[] = [];
    await chatStream([{ role: 'user', content: 'Hello' }], (event) => {
      if (event.delta) deltas.push(event.delta);
    });

    expect(deltas).toEqual(['Hello']);
    expect(localStorage.getItem('otl_session')).toBeNull();
  });
});
