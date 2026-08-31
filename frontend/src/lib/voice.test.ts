import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSpeechInput, useAudioPlayer } from './voice';

describe('useSpeechInput with Web Speech API', () => {
  let mockRecognitionInstance: any;

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
