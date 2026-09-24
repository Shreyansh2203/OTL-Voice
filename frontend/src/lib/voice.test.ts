import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSpeechInput, useAudioPlayer } from './voice';
import { useMicLevel } from './useMicLevel';
import { OciSpeechRecognition } from './ociSpeech';

describe('useSpeechInput with Web Speech API', () => {
  let mockRecognitionInstance: any;
  const speechResult = (
    transcript: string,
    isFinal = true,
    confidence?: number
  ) => ({ 0: { transcript, confidence }, isFinal, length: 1 });

  beforeEach(() => {
    class MockSpeechRecognition {
      continuous = false;
      interimResults = false;
      lang = '';
      maxAlternatives = 1;
      start = vi.fn();
      stop = vi.fn();
      abort = vi.fn();
      onspeechstart: any = null;
      onaudiostart: any = null;
      onresult: any = null;
      onerror: any = null;
      onend: any = null;

      constructor() {
        // eslint-disable-next-line @typescript-eslint/no-this-alias
        mockRecognitionInstance = this;
      }
    }

    (window as any).SpeechRecognition = MockSpeechRecognition;
    (window as any).webkitSpeechRecognition = MockSpeechRecognition;
  });

  afterEach(() => {
    delete (window as any).SpeechRecognition;
    delete (window as any).webkitSpeechRecognition;
  });

  it('detects browser support correctly', () => {
    const { result } = renderHook(() => useSpeechInput());
    expect(result.current.supported).toBe(true);
    expect(result.current.listening).toBe(false);
  });

  it('starts speech recognition and triggers callbacks on results', async () => {
    const { result } = renderHook(() => useSpeechInput());

    const onFinal = vi.fn();
    const onInterim = vi.fn();
    const onSpeechStart = vi.fn();

    await act(async () => {
      await result.current.start(onFinal, onInterim, onSpeechStart, true);
    });

    expect(result.current.listening).toBe(true);
    expect(mockRecognitionInstance.start).toHaveBeenCalled();

    // Trigger speech start
    act(() => {
      mockRecognitionInstance.onspeechstart();
    });
    expect(onSpeechStart).toHaveBeenCalled();

    // Trigger interim speech result
    act(() => {
      mockRecognitionInstance.onresult({
        resultIndex: 0,
        results: [
          {
            0: { transcript: 'I worked 4 hours' },
            isFinal: false,
            length: 1,
          },
        ],
      });
    });
    expect(onInterim).toHaveBeenCalledWith('I worked 4 hours');
    expect(onFinal).not.toHaveBeenCalled();

    // Trigger final speech result
    act(() => {
      mockRecognitionInstance.onresult({
        resultIndex: 0,
        results: [
          {
            0: { transcript: 'I worked 4 hours on Alpha' },
            isFinal: true,
            length: 1,
          },
        ],
      });
    });
    expect(onFinal).toHaveBeenCalledWith('I worked 4 hours on Alpha');
  });

  it('stops speech recognition cleanly', async () => {
    const { result } = renderHook(() => useSpeechInput());

    await act(async () => {
      await result.current.start(vi.fn());
    });
    expect(result.current.listening).toBe(true);

    act(() => {
      result.current.stop();
    });

    expect(mockRecognitionInstance.stop).toHaveBeenCalled();
    expect(result.current.listening).toBe(false);
  });

  it('aborts when cancelled', async () => {
    const { result } = renderHook(() => useSpeechInput());

    await act(async () => {
      await result.current.start(vi.fn());
    });

    act(() => {
      result.current.stop(true);
    });

    expect(mockRecognitionInstance.abort).toHaveBeenCalled();
    expect(result.current.listening).toBe(false);
  });

  it('handles permission denied errors', async () => {
    const { result } = renderHook(() => useSpeechInput());

    await act(async () => {
      await result.current.start(vi.fn());
    });

    act(() => {
      mockRecognitionInstance.onerror({ error: 'not-allowed' });
    });

    expect(result.current.listening).toBe(false);
    expect(result.current.errorMsg).toContain('Microphone access blocked');
  });

  it('does not treat opening the microphone as detected speech', async () => {
    const { result } = renderHook(() => useSpeechInput());
    const onSpeechStart = vi.fn();
    await act(async () => {
      await result.current.start(vi.fn(), vi.fn(), onSpeechStart);
    });

    act(() => mockRecognitionInstance.onaudiostart?.());
    expect(onSpeechStart).not.toHaveBeenCalled();
    act(() => mockRecognitionInstance.onspeechstart());
    expect(onSpeechStart).toHaveBeenCalledTimes(1);
  });

  it('ignores every late recognition callback after stopping', async () => {
    const { result } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    const onInterim = vi.fn();
    const onSpeechStart = vi.fn();
    await act(async () => {
      await result.current.start(onFinal, onInterim, onSpeechStart);
    });
    const stoppedRecognition = mockRecognitionInstance;
    act(() => result.current.stop());
    act(() => {
      stoppedRecognition.onspeechstart();
      stoppedRecognition.onresult({ results: [speechResult('ghost words')] });
      stoppedRecognition.onerror({ error: 'not-allowed' });
      stoppedRecognition.onend();
    });

    expect(onFinal).not.toHaveBeenCalled();
    expect(onInterim).not.toHaveBeenCalled();
    expect(onSpeechStart).not.toHaveBeenCalled();
    expect(result.current.errorMsg).toBeNull();
    expect(result.current.listening).toBe(false);
    expect(stoppedRecognition.start).toHaveBeenCalledTimes(1);
  });

  it('keeps a new session active when callbacks arrive from the old one', async () => {
    const { result } = renderHook(() => useSpeechInput());
    const oldFinal = vi.fn();
    const newFinal = vi.fn();
    const newSpeechStart = vi.fn();
    await act(async () => result.current.start(oldFinal));
    const oldRecognition = mockRecognitionInstance;
    await act(async () =>
      result.current.start(newFinal, vi.fn(), newSpeechStart)
    );
    const newRecognition = mockRecognitionInstance;
    act(() => {
      oldRecognition.onspeechstart();
      oldRecognition.onresult({ results: [speechResult('old words')] });
      oldRecognition.onerror({ error: 'not-allowed' });
      oldRecognition.onend();
    });

    expect(newFinal).not.toHaveBeenCalled();
    expect(oldFinal).not.toHaveBeenCalled();
    expect(newSpeechStart).not.toHaveBeenCalled();
    expect(result.current.listening).toBe(true);
    expect(result.current.errorMsg).toBeNull();
    expect(newRecognition.abort).not.toHaveBeenCalled();
    act(() => newRecognition.onresult({ results: [speechResult('4')] }));
    expect(newFinal).toHaveBeenCalledWith('4');
  });

  it('joins cumulative phrases and ignores repeated finalized results', async () => {
    const { result } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    const onInterim = vi.fn();
    const onSpeechStart = vi.fn();
    await act(async () =>
      result.current.start(onFinal, onInterim, onSpeechStart)
    );
    const first = speechResult(' I worked 4 hours ');
    const second = speechResult('on Alpha');
    act(() => mockRecognitionInstance.onresult({ results: [first] }));
    act(() =>
      mockRecognitionInstance.onresult({ results: [first, second] })
    );
    expect(onFinal).toHaveBeenLastCalledWith('I worked 4 hours on Alpha');
    expect(onFinal).toHaveBeenCalledTimes(2);
    onSpeechStart.mockClear();
    act(() =>
      mockRecognitionInstance.onresult({ results: [first, second] })
    );
    expect(onSpeechStart).not.toHaveBeenCalled();
    expect(onFinal).toHaveBeenCalledTimes(2);
    expect(onInterim).not.toHaveBeenCalled();
  });

  it('clears withdrawn interim words without resending previous final text', async () => {
    const { result } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    const onInterim = vi.fn();
    const onSpeechStart = vi.fn();
    await act(async () =>
      result.current.start(onFinal, onInterim, onSpeechStart)
    );
    const final = speechResult('4 hours');
    act(() => mockRecognitionInstance.onresult({ results: [final] }));
    act(() =>
      mockRecognitionInstance.onresult({
        results: [final, speechResult('random words', false)],
      })
    );
    onSpeechStart.mockClear();
    act(() => mockRecognitionInstance.onresult({ results: [final] }));

    expect(onInterim).toHaveBeenLastCalledWith('');
    expect(onFinal).toHaveBeenCalledTimes(1);
    expect(onSpeechStart).not.toHaveBeenCalled();
  });

  it('does not deliver final text after a callback stops the session', async () => {
    const { result } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    await act(async () =>
      result.current.start(onFinal, vi.fn(), () => result.current.stop())
    );
    act(() =>
      mockRecognitionInstance.onresult({ results: [speechResult('late text')] })
    );
    expect(onFinal).not.toHaveBeenCalled();
  });

  it('preserves finalized text across a continuous browser restart', async () => {
    const { result } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    await act(async () => result.current.start(onFinal));
    act(() =>
      mockRecognitionInstance.onresult({ results: [speechResult('4 hours')] })
    );
    act(() => mockRecognitionInstance.onend());
    expect(mockRecognitionInstance.start).toHaveBeenCalledTimes(2);
    act(() =>
      mockRecognitionInstance.onresult({ results: [speechResult('on Alpha')] })
    );
    expect(onFinal).toHaveBeenLastCalledWith('4 hours on Alpha');
  });

  it('rejects uncertain final words, clears their preview and requests a repeat', async () => {
    const { result } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    const onInterim = vi.fn();
    await act(async () => result.current.start(onFinal, onInterim));
    act(() =>
      mockRecognitionInstance.onresult({
        results: [speechResult('random words', false)],
      })
    );
    act(() =>
      mockRecognitionInstance.onresult({
        results: [speechResult('random words', true, 0.2)],
      })
    );
    expect(onFinal).not.toHaveBeenCalled();
    expect(onInterim).toHaveBeenLastCalledWith('');
    expect(result.current.errorMsg).toContain('Please repeat');
  });

  it('does not re-finalize an earlier accepted fragment when newer words are rejected', async () => {
    const { result } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    const onInterim = vi.fn();
    await act(async () => result.current.start(onFinal, onInterim));
    const accepted = speechResult('4 hours', true, 0.9);
    const rejected = speechResult('random words', true, 0.1);
    act(() => mockRecognitionInstance.onresult({ results: [accepted] }));
    act(() =>
      mockRecognitionInstance.onresult({ results: [accepted, rejected] })
    );
    act(() =>
      mockRecognitionInstance.onresult({ results: [accepted, rejected] })
    );
    expect(onFinal).toHaveBeenCalledTimes(1);
    expect(onInterim).toHaveBeenLastCalledWith('');
    act(() =>
      mockRecognitionInstance.onresult({
        results: [accepted, rejected, speechResult('on Alpha', true, 0.8)],
      })
    );
    expect(onFinal).toHaveBeenLastCalledWith('4 hours on Alpha');
    expect(result.current.errorMsg).toBeNull();
  });

  it.each([
    ['yes', 0.8],
    ['no', 0.5],
    ['4', 0],
    ['3.5', undefined],
    ['yes', Number.NaN],
    ['4', Number.POSITIVE_INFINITY],
  ])('keeps the short reply %s when confidence is %s', async (text, confidence) => {
    const { result } = renderHook(() => useSpeechInput());
    const onFinal = vi.fn();
    await act(async () => result.current.start(onFinal));
    act(() =>
      mockRecognitionInstance.onresult({
        results: [speechResult(text, true, confidence)],
      })
    );
    expect(onFinal).toHaveBeenCalledWith(text);
    expect(result.current.errorMsg).toBeNull();
  });
});

describe('OciSpeechRecognition', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('accumulates multiple final transcripts before emitting results', async () => {
    class MockWebSocket {
      static OPEN = 1;
      static instance: MockWebSocket | null = null;
      readyState = 0;
      onopen: (() => void) | null = null;
      onmessage: ((event: { data: string }) => void) | null = null;
      onerror: (() => void) | null = null;
      onclose: (() => void) | null = null;
      port = { onmessage: null };

      constructor() {
        MockWebSocket.instance = this;
      }

      close() {}
      send() {}
    }
    class MockAudioContext {
      audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
      destination = {};
      createMediaStreamSource() {
        return { connect: vi.fn() };
      }
      close() {
        return Promise.resolve();
      }
    }
    class MockAudioWorkletNode {
      port = { onmessage: null };
      connect() {}
      disconnect() {}
    }

    vi.spyOn(navigator.mediaDevices, 'getUserMedia').mockResolvedValue({
      getTracks: () => [{ stop: vi.fn() }],
    } as unknown as MediaStream);
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('AudioContext', MockAudioContext);
    vi.stubGlobal('AudioWorkletNode', MockAudioWorkletNode);

    const recognition = new OciSpeechRecognition();
    const onResult = vi.fn();
    recognition.onresult = onResult;
    recognition.start();
    await vi.waitFor(() =>
      expect(MockWebSocket.instance?.onmessage).toBeTypeOf('function')
    );

    MockWebSocket.instance?.onmessage?.({
      data: JSON.stringify({ text: 'I worked 4 hours', isFinal: true }),
    });
    MockWebSocket.instance?.onmessage?.({
      data: JSON.stringify({ text: 'on Alpha', isFinal: true }),
    });
    MockWebSocket.instance?.onmessage?.({
      data: JSON.stringify({ text: 'for testing', isFinal: false }),
    });

    const lastEvent = onResult.mock.calls.at(-1)?.[0];
    expect(
      lastEvent.results.map((result: any) => result[0].transcript)
    ).toEqual(['I worked 4 hours', 'on Alpha', 'for testing']);
    expect(lastEvent.results.map((result: any) => result.isFinal)).toEqual([
      true,
      true,
      false,
    ]);
    recognition.stop();
  });
});

describe('useMicLevel', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('stops a microphone stream acquired after start was cancelled', async () => {
    const track = { stop: vi.fn() };
    let resolveMedia!: (stream: MediaStream) => void;
    vi.spyOn(navigator.mediaDevices, 'getUserMedia').mockReturnValue(
      new Promise<MediaStream>((resolve) => {
        resolveMedia = resolve;
      })
    );
    const { result } = renderHook(() => useMicLevel());
    let startPromise!: Promise<void>;
    act(() => {
      startPromise = result.current.start();
    });
    act(() => {
      result.current.stop();
    });
    await act(async () => {
      resolveMedia({ getTracks: () => [track] } as unknown as MediaStream);
      await startPromise;
    });
    expect(track.stop).toHaveBeenCalledTimes(1);
  });
});

describe('useAudioPlayer', () => {
  let originalAudio: typeof Audio;

  beforeEach(() => {
    originalAudio = window.Audio;
    window.URL.createObjectURL = vi.fn(() => 'blob:mock-url');
    window.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    window.Audio = originalAudio;
  });

  it('initializes in not playing state', () => {
    const { result } = renderHook(() => useAudioPlayer());
    expect(result.current.playing).toBe(false);
  });
});
