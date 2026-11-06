import { describe, it, expect, vi } from 'vitest';
import { readSse } from './sse';
describe('readSse', () => {
  it('throws error if response body is null', async () => {
    const mockResponse = { body: null } as unknown as Response;
    await expect(readSse(mockResponse, vi.fn())).rejects.toThrow(
      'No response body to stream.'
    );
  });
  it('reads frames and parses JSON', async () => {
    const encoder = new TextEncoder();
    const data = 'data: {"delta": "hello"}\n\n';
    let chunkSent = false;
    const mockReader = {
      read: vi.fn().mockImplementation(() => {
        if (!chunkSent) {
          chunkSent = true;
          return Promise.resolve({ done: false, value: encoder.encode(data) });
        }
        return Promise.resolve({ done: true, value: undefined });
      }),
      releaseLock: vi.fn(),
    };
    const mockResponse = {
      body: {
        getReader: () => mockReader,
      },
    } as unknown as Response;
    const onEvent = vi.fn();
    await readSse(mockResponse, onEvent);
    expect(onEvent).toHaveBeenCalledWith({ delta: 'hello' });
    expect(mockReader.releaseLock).toHaveBeenCalled();
  });
  it('ignores malformed frames and respects abort signal', async () => {
    const encoder = new TextEncoder();
    const data1 = 'data: {bad json\n\n';
    const data2 = 'data: {"done": true}\n\n';
    let count = 0;
    const mockReader = {
      read: vi.fn().mockImplementation(() => {
        if (count === 0) {
          count++;
          return Promise.resolve({ done: false, value: encoder.encode(data1) });
        }
        if (count === 1) {
          count++;
          return Promise.resolve({ done: false, value: encoder.encode(data2) });
        }
        return Promise.resolve({ done: true, value: undefined });
      }),
      releaseLock: vi.fn(),
    };
    const mockResponse = {
      body: {
        getReader: () => mockReader,
      },
    } as unknown as Response;
    const onEvent = vi.fn();
    const abortController = new AbortController();
    await readSse(mockResponse, onEvent, abortController.signal);
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith({ done: true });
    count = 0;
    mockReader.read.mockImplementation(() => {
      abortController.abort();
      return Promise.resolve({
        done: false,
        value: encoder.encode('data: {}\n\n'),
      });
    });
    const onEvent2 = vi.fn();
    abortController.abort();
    await readSse(mockResponse, onEvent2, abortController.signal);
    expect(onEvent2).not.toHaveBeenCalled();
  });
  it('ignores lines that do not start with data or have empty payload', async () => {
    const encoder = new TextEncoder();
    const mockReader = {
      read: vi
        .fn()
        .mockResolvedValueOnce({
          done: false,
          value: encoder.encode('event: something\ndata: \n\n'),
        })
        .mockResolvedValueOnce({ done: true, value: undefined }),
      releaseLock: vi.fn(),
    };
    const mockResponse = {
      body: { getReader: () => mockReader },
    } as unknown as Response;
    const onEvent = vi.fn();
    await readSse(mockResponse, onEvent);
    expect(onEvent).not.toHaveBeenCalled();
  });
});
