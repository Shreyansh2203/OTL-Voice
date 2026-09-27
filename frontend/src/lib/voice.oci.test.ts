import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';

const oci = vi.hoisted(() => ({
  instances: [] as any[],
  constructorError: null as unknown,
  startError: null as unknown,
}));

vi.mock('./ociSpeech', () => {
  class FakeOciSpeechRecognition {
    continuous = false;
    interimResults = false;
    lang = '';
    maxAlternatives = 1;
    onspeechstart: (() => void) | null = null;
    onresult: ((event: any) => void) | null = null;
    onerror: ((event: { error: string }) => void) | null = null;
    onend: (() => void) | null = null;
    closed?: boolean;
    stop = vi.fn();
    abort = vi.fn();
    start = vi.fn(() => {
      if (oci.startError) throw oci.startError;
    });

    constructor() {
      if (oci.constructorError) throw oci.constructorError;
      oci.instances.push(this);
    }
  }
  return { OciSpeechRecognition: FakeOciSpeechRecognition };
});

const { useSpeechInput } = await import('./voice');

const latest = () => oci.instances.at(-1);

const result = (transcript: string, isFinal = true) => ({
  0: { transcript, confidence: 0.9 },
  isFinal,
  length: 1,
});

describe('useSpeechInput without a browser speech engine', () => {
  beforeEach(() => {
    oci.instances = [];
    oci.constructorError = null;
    oci.startError = null;
    delete (window as any).SpeechRecognition;
    delete (window as any).webkitSpeechRecognition;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('drives the OCI engine when the browser has no speech API', async () => {
    const { result: hook } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    const onInterim = vi.fn();
    const onSpeechStart = vi.fn();

    await act(async () => {
      await hook.current.start(onFinal, onInterim, onSpeechStart, true);
    });

    expect(hook.current.listening).toBe(true);
    const engine = latest();
    expect(engine.continuous).toBe(true);
    expect(engine.interimResults).toBe(true);
    expect(engine.maxAlternatives).toBe(1);
    expect(engine.start).toHaveBeenCalled();

    act(() => engine.onspeechstart?.());
    expect(onSpeechStart).toHaveBeenCalledTimes(1);

    act(() => engine.onresult?.({ results: [result('four hours', false)] }));
    expect(onInterim).toHaveBeenCalledWith('four hours');

    act(() => engine.onresult?.({ results: [result('four hours')] }));
    expect(onFinal).toHaveBeenCalledWith('four hours');
    expect(hook.current.notice).toBeNull();
  });

  it('asks the user to type when OCI speech has no browser fallback', async () => {
    const { result: hook } = renderHook(() => useSpeechInput());
    await act(async () => {
      await hook.current.start(vi.fn());
    });
    act(() => latest().onerror?.({ error: 'network' }));
    expect(hook.current.errorMsg).toMatch(/OCI speech is unavailable/);
    expect(hook.current.listening).toBe(false);
    expect(hook.current.browserSpeechFallbackAvailable).toBe(false);
  });

  it('reports a blocked microphone when the OCI engine cannot be constructed', async () => {
    oci.constructorError = Object.assign(new Error('denied'), {
      name: 'NotAllowedError',
    });
    const { result: hook } = renderHook(() => useSpeechInput());
    await act(async () => {
      await hook.current.start(vi.fn());
    });
    expect(hook.current.errorMsg).toMatch(/Microphone access blocked/);
    expect(hook.current.listening).toBe(false);
  });

  it('reports a generic failure when the OCI engine throws a value', async () => {
    oci.constructorError = 'not an error';
    const { result: hook } = renderHook(() => useSpeechInput());
    await act(async () => {
      await hook.current.start(vi.fn());
    });
    expect(hook.current.errorMsg).toMatch(/check your input device/);
  });

  it('reports a blocked microphone when the OCI engine refuses to start', async () => {
    oci.startError = Object.assign(new Error('denied'), {
      name: 'NotAllowedError',
    });
    const { result: hook } = renderHook(() => useSpeechInput());
    await act(async () => {
      await hook.current.start(vi.fn());
    });
    expect(hook.current.errorMsg).toMatch(/Microphone access blocked/);
    expect(hook.current.listening).toBe(false);
  });

  it('reports a generic start failure when the OCI engine throws a value', async () => {
    oci.startError = 'not an error';
    const { result: hook } = renderHook(() => useSpeechInput());
    await act(async () => {
      await hook.current.start(vi.fn());
    });
    expect(hook.current.errorMsg).toMatch(/could not start/);
    expect(hook.current.listening).toBe(false);
  });

  it('restarts a continuous OCI session after it ends', async () => {
    const { result: hook } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    await act(async () => {
      await hook.current.start(onFinal);
    });
    const engine = latest();
    act(() => engine.onresult?.({ results: [result('four hours')] }));
    act(() => engine.onend?.());
    expect(engine.start).toHaveBeenCalledTimes(2);
    act(() => engine.onresult?.({ results: [result('on Alpha')] }));
    expect(onFinal).toHaveBeenLastCalledWith('four hours on Alpha');
    expect(hook.current.listening).toBe(true);
  });
});
