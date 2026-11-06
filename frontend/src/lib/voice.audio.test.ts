import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useAudioPlayer } from './voice';

class FakeAudio {
  static instances: FakeAudio[] = [];
  static playResolves = true;
  static playRejectsWith: unknown = null;
  static errorCode: number | undefined;

  onended: (() => void) | null = null;
  onpause: (() => void) | null = null;
  onerror: (() => void) | null = null;
  error: { code: number } | undefined;
  paused = false;
  src = '';
  playCalls = 0;

  constructor(public url: string) {
    FakeAudio.instances.push(this);
  }

  pause() {
    this.paused = true;
  }

  play() {
    this.playCalls += 1;
    if (FakeAudio.playRejectsWith)
      return Promise.reject(FakeAudio.playRejectsWith);
    return Promise.resolve();
  }
}

describe('useAudioPlayer', () => {
  let originalAudio: typeof window.Audio;
  let revoked: string[];

  beforeEach(() => {
    FakeAudio.instances = [];
    FakeAudio.playResolves = true;
    FakeAudio.playRejectsWith = null;
    FakeAudio.errorCode = undefined;
    revoked = [];
    originalAudio = window.Audio;
    window.Audio = FakeAudio as unknown as typeof window.Audio;
    let counter = 0;
    window.URL.createObjectURL = vi.fn(() => `blob:mock-${(counter += 1)}`);
    window.URL.revokeObjectURL = vi.fn((url: string) => {
      revoked.push(url);
    });
  });

  afterEach(() => {
    window.Audio = originalAudio;
  });

  const blob = () => new Blob(['audio-bytes']);

  it('reports playing once the element accepts playback', async () => {
    const { result } = renderHook(() => useAudioPlayer());
    let outcome: unknown;
    await act(async () => {
      const pending = result.current.play(blob());
      const audio = FakeAudio.instances[0];
      await act(async () => {
        audio.onended?.();
      });
      outcome = await pending;
    });
    expect(outcome).toEqual({ success: true });
    await waitFor(() => expect(result.current.playing).toBe(false));
    expect(revoked).toEqual(['blob:mock-1']);
  });

  it('clears playing state while the audio is still running', async () => {
    const { result } = renderHook(() => useAudioPlayer());
    let pending!: Promise<unknown>;
    act(() => {
      pending = result.current.play(blob());
    });
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.playing).toBe(true));
    const audio = FakeAudio.instances[0];
    let outcome: unknown;
    await act(async () => {
      audio.onended?.();
      outcome = await pending;
    });
    expect(outcome).toEqual({ success: true });
    expect(result.current.playing).toBe(false);
  });

  it('reports a pause as an unsuccessful finish', async () => {
    const { result } = renderHook(() => useAudioPlayer());
    let outcome: unknown;
    await act(async () => {
      const pending = result.current.play(blob());
      const audio = FakeAudio.instances[0];
      await act(async () => {
        audio.onpause?.();
      });
      outcome = await pending;
    });
    expect(outcome).toEqual({ success: false });
  });

  it('flags a media error with code 4 as a blocked autoplay', async () => {
    const { result } = renderHook(() => useAudioPlayer());
    let outcome: unknown;
    await act(async () => {
      const pending = result.current.play(blob());
      const audio = FakeAudio.instances[0];
      audio.error = { code: 4 };
      await act(async () => {
        audio.onerror?.();
      });
      outcome = await pending;
    });
    expect(outcome).toEqual({ success: false, autoplayBlocked: true });
  });

  it('flags a media error with no code as a blocked autoplay', async () => {
    const { result } = renderHook(() => useAudioPlayer());
    let outcome: unknown;
    await act(async () => {
      const pending = result.current.play(blob());
      const audio = FakeAudio.instances[0];
      audio.error = undefined;
      await act(async () => {
        audio.onerror?.();
      });
      outcome = await pending;
    });
    expect(outcome).toEqual({ success: false, autoplayBlocked: true });
  });

  it('reports an ordinary media error as a plain failure', async () => {
    const { result } = renderHook(() => useAudioPlayer());
    let outcome: unknown;
    await act(async () => {
      const pending = result.current.play(blob());
      const audio = FakeAudio.instances[0];
      audio.error = { code: 2 };
      await act(async () => {
        audio.onerror?.();
      });
      outcome = await pending;
    });
    expect(outcome).toEqual({ success: false, autoplayBlocked: false });
  });

  it('flags a rejected play call as a blocked autoplay', async () => {
    FakeAudio.playRejectsWith = new DOMException('denied', 'NotAllowedError');
    const { result } = renderHook(() => useAudioPlayer());
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.play(blob());
    });
    expect(outcome).toEqual({ success: false, autoplayBlocked: true });
    await waitFor(() => expect(result.current.playing).toBe(false));
  });

  it('reports a non-DOMException play rejection without blaming autoplay', async () => {
    FakeAudio.playRejectsWith = new Error('decode failed');
    const { result } = renderHook(() => useAudioPlayer());
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.play(blob());
    });
    expect(outcome).toEqual({ success: false, autoplayBlocked: false });
  });

  it('ignores a stale finish callback after the next clip is queued', async () => {
    const { result } = renderHook(() => useAudioPlayer());
    let firstOutcome: unknown;
    let secondOutcome: unknown;
    await act(async () => {
      const first = result.current.play(blob());
      const firstAudio = FakeAudio.instances[0];
      const second = result.current.play(blob());
      const secondAudio = FakeAudio.instances[1];
      firstAudio.onended?.();
      secondAudio.onended?.();
      firstOutcome = await first;
      secondOutcome = await second;
    });
    expect(firstOutcome).toEqual({ success: false, interrupted: true });
    expect(secondOutcome).toEqual({ success: true });
  });

  it('interrupts the pending clip when stopped', async () => {
    const { result } = renderHook(() => useAudioPlayer());
    let outcome: unknown;
    await act(async () => {
      const pending = result.current.play(blob());
      await Promise.resolve();
      result.current.stop();
      outcome = await pending;
    });
    expect(outcome).toEqual({ success: false, interrupted: true });
    await waitFor(() => expect(result.current.playing).toBe(false));
  });

  it('stops nothing gracefully when called before any clip', () => {
    const { result } = renderHook(() => useAudioPlayer());
    expect(() => result.current.stop()).not.toThrow();
    expect(result.current.playing).toBe(false);
  });

  it('releases the element and the object url when the hook unmounts', async () => {
    const { result, unmount } = renderHook(() => useAudioPlayer());
    await act(async () => {
      void result.current.play(blob());
    });
    const audio = FakeAudio.instances[0];
    unmount();
    expect(audio.paused).toBe(true);
    expect(audio.src).toBe('');
    expect(audio.onended).toBeNull();
    expect(revoked).toEqual(['blob:mock-1']);
  });
});
