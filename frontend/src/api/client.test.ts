import { describe, it, expect, vi, afterEach } from 'vitest';
import { login, getSession, logout, chatStream, tts, getAssignments, submitTimecard, listTimecards, ApiError } from './client';
import { readSse } from '../lib/sse';
vi.mock('../lib/sse', () => ({
  readSse: vi.fn(),
}));
describe('client API', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });
  it('login handles success', async () => {
    const mockIdentity = { username: 'testuser', fullName: 'Test', employeeId: '123' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockIdentity),
    }));
    const result = await login('testuser', 'password');
    expect(result).toEqual(mockIdentity);
    expect(fetch).toHaveBeenCalledWith('/api/auth/login', expect.objectContaining({
      method: 'POST'
    }));
  });
  it('login throws ApiError on failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      json: () => Promise.resolve({ detail: 'Wrong password' }),
    }));
    await expect(login('user', 'pass')).rejects.toThrow(ApiError);
    await expect(login('user', 'pass')).rejects.toThrow('Wrong password');
  });
  it('login handles missing json detail in error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: () => Promise.reject(new Error('not json')),
    }));
    await expect(login('user', 'pass')).rejects.toThrow('Internal Server Error');
  });
  it('getSession returns session', async () => {
    const mockIdentity = { username: 'testuser', fullName: 'Test', employeeId: '123' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockIdentity),
    }));
    const result = await getSession();
    expect(result).toEqual(mockIdentity);
  });
  it('getSession returns null on 401', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
    }));
    const result = await getSession();
    expect(result).toBeNull();
  });
  it('getSession throws error on other failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      json: () => Promise.resolve({}),
    }));
    await expect(getSession()).rejects.toThrow(ApiError);
  });
  it('logout calls fetch', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
    await logout();
    expect(fetch).toHaveBeenCalledWith('/api/auth/logout', expect.any(Object));
  });
  it('chatStream works correctly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
    const onEvent = vi.fn();
    await chatStream([{ role: 'user', content: 'hello' }], onEvent);
    expect(fetch).toHaveBeenCalledWith('/api/chat', expect.any(Object));
    expect(readSse).toHaveBeenCalled();
  });
  it('chatStream handles error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(chatStream([], vi.fn())).rejects.toThrow(ApiError);
  });
  it('tts returns blob', async () => {
    const blob = new Blob();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(blob),
    }));
    const result = await tts('hello', 1.0);
    expect(result).toBe(blob);
    expect(fetch).toHaveBeenCalledWith('/api/tts', expect.any(Object));
  });
  it('tts handles error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(tts('hello', 1)).rejects.toThrow(ApiError);
  });
  it('getAssignments returns assignments', async () => {
    const mockData = { ok: true };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockData),
    }));
    const result = await getAssignments();
    expect(result).toEqual(mockData);
  });
  it('getAssignments handles error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(getAssignments()).rejects.toThrow(ApiError);
  });
  it('submitTimecard works correctly', async () => {
    const mockData = { ok: true };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockData),
    }));
    const result = await submitTimecard([]);
    expect(result).toEqual(mockData);
    expect(fetch).toHaveBeenCalledWith('/api/otl/timecard', expect.any(Object));
  });
  it('submitTimecard handles error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(submitTimecard([])).rejects.toThrow(ApiError);
  });
  it('listTimecards handles success', async () => {
    const mockData = { items: [] };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockData),
    }));
    const result = await listTimecards(50, 0);
    expect(result).toEqual(mockData);
    expect(fetch).toHaveBeenCalledWith('/api/otl/timecards?limit=50&offset=0', expect.any(Object));
  });
  it('listTimecards handles error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(listTimecards()).rejects.toThrow(ApiError);
  });
});