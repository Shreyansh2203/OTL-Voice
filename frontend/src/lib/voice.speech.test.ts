import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useSpeechInput } from './voice';

type Mock = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
  abort: ReturnType<typeof vi.fn>;
  onspeechstart: (() => void) | null;
  onresult: ((event: any) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  closed?: boolean;
};

let latest: Mock;
let instances: Mock[];

class MockSpeechRecognition {
  continuous = false;
  interimResults = false;
  lang = '';
  maxAlternatives = 1;
  onspeechstart: (() => void) | null = null;
  onresult: ((event: any) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  closed?: boolean;
  start = vi.fn();
  stop = vi.fn();
  abort = vi.fn();

  constructor() {
    latest = this as unknown as Mock;
    instances.push(latest);
  }
}

const final = (transcript: string) => ({
  0: { transcript, confidence: 0.9 },
  isFinal: true,
  length: 1,
});

describe('useSpeechInput error and restart handling', () => {
  beforeEach(() => {
    instances = [];
    (window as any).SpeechRecognition = MockSpeechRecognition;
    (window as any).webkitSpeechRecognition = MockSpeechRecognition;
  });

  afterEach(() => {
    delete (window as any).SpeechRecognition;
    delete (window as any).webkitSpeechRecognition;
    vi.restoreAllMocks();
  });

  it('explains that browser speech could not connect', async () => {
    const { result } = renderHook(() => useSpeechInput());
    await act(async () => {
      await result.current.start(vi.fn());
    });
    act(() => latest.onerror?.({ error: 'network' }));
    expect(result.current.errorMsg).toMatch(/Browser speech could not connect/);
    expect(latest.abort).toHaveBeenCalled();
  });

  it.each([['no-speech'], ['aborted']])(
    'stays silent for the %s error',
    async (error) => {
      const { result } = renderHook(() => useSpeechInput());
      await act(async () => {
        await result.current.start(vi.fn());
      });
      act(() => latest.onerror?.({ error }));
      expect(result.current.errorMsg).toBeNull();
      expect(result.current.listening).toBe(true);
    }
  );

  it('reports an unrecognised recognition error', async () => {
    const { result } = renderHook(() => useSpeechInput());
    await act(async () => {
      await result.current.start(vi.fn());
    });
    act(() => latest.onerror?.({ error: 'audio-capture' }));
    expect(result.current.errorMsg).toMatch(/stopped unexpectedly/);
    expect(result.current.listening).toBe(false);
  });

  it('blocks the microphone when the service is not allowed', async () => {
    const { result } = renderHook(() => useSpeechInput());
    await act(async () => {
      await result.current.start(vi.fn());
    });
    act(() => latest.onerror?.({ error: 'service-not-allowed' }));
    expect(result.current.errorMsg).toMatch(/Microphone access blocked/);
  });

  it('reports a closed session so the user can try again', async () => {
    const { result } = renderHook(() => useSpeechInput());
    await act(async () => {
      await result.current.start(vi.fn());
    });
    act(() => {
      latest.closed = true;
      latest.onend?.();
    });
    expect(result.current.listening).toBe(false);
    expect(result.current.errorMsg).toMatch(/session closed/);
  });

  it('stays quiet when a closed session is the expected browser fallback', async () => {
    const { result } = renderHook(() => useSpeechInput());
    await act(async () => {
      await result.current.start(vi.fn());
    });
    // A network failure marks the fallback as pending before the engine ends.
    act(() => latest.onerror?.({ error: 'network' }));
    act(() => {
      latest.closed = true;
      latest.onend?.();
    });
    expect(result.current.errorMsg).toMatch(/Browser speech could not connect/);
  });

  it('tears the session down when a one-shot recognition ends', async () => {
    const { result } = renderHook(() => useSpeechInput());
    await act(async () => {
      await result.current.start(vi.fn(), vi.fn(), vi.fn(), false);
    });
    act(() => latest.onend?.());
    expect(result.current.listening).toBe(false);
    expect(latest.start).toHaveBeenCalledTimes(1);
  });

  it('stops after a final result when the session is not continuous', async () => {
    const { result } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    await act(async () => {
      await result.current.start(onFinal, vi.fn(), vi.fn(), false);
    });
    act(() => latest.onresult?.({ results: [final('4 hours')] }));
    expect(onFinal).toHaveBeenCalledWith('4 hours');
    expect(latest.stop).toHaveBeenCalled();
    expect(result.current.listening).toBe(false);
  });

  it('aborts instead of restarting when a continuous engine refuses to start', async () => {
    const { result } = renderHook(() => useSpeechInput());
    await act(async () => {
      await result.current.start(vi.fn());
    });
    latest.start.mockImplementation(() => {
      throw new Error('already started');
    });
    act(() => latest.onend?.());
    expect(latest.abort).toHaveBeenCalled();
    expect(result.current.listening).toBe(false);
  });

  it('aborts the engine when a graceful stop throws', async () => {
    const { result } = renderHook(() => useSpeechInput());
    await act(async () => {
      await result.current.start(vi.fn());
    });
    latest.stop.mockImplementation(() => {
      throw new Error('cannot stop');
    });
    act(() => result.current.stop());
    expect(latest.abort).toHaveBeenCalled();
    expect(result.current.listening).toBe(false);
  });

  it('ignores a browser fallback request when no browser engine exists', async () => {
    delete (window as any).SpeechRecognition;
    delete (window as any).webkitSpeechRecognition;
    const { result } = renderHook(() => useSpeechInput());
    await act(async () => {
      await result.current.start(vi.fn());
    });
    const created = instances.length;
    act(() => result.current.useBrowserSpeechFallback());
    expect(instances).toHaveLength(created);
  });
});
