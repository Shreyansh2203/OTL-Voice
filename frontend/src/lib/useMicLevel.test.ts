import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useMicLevel } from './useMicLevel';

function installMocks() {
  const trackStop = vi.fn();
  const stream = { getTracks: () => [{ stop: trackStop }] } as unknown as MediaStream;
  const getUserMedia = vi.fn().mockResolvedValue(stream);
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  });
  const analyser = {
    frequencyBinCount: 4,
    fftSize: 0,
    smoothingTimeConstant: 0,
    getByteTimeDomainData: vi.fn((data: Uint8Array) => {
      data.fill(220);
    }),
  };
  const source = { connect: vi.fn() };
  const close = vi.fn().mockResolvedValue(undefined);
  const audioContext = {
    createMediaStreamSource: vi.fn(() => source),
    createAnalyser: vi.fn(() => analyser),
    close,
  };
  Object.defineProperty(window, 'AudioContext', {
    configurable: true,
    value: function AudioContext() {
      return audioContext;
    },
  });
  let frame: FrameRequestCallback | null = null;
  const requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => {
    frame = callback;
    return 7;
  });
  const cancelAnimationFrame = vi.fn();
  Object.defineProperty(window, 'requestAnimationFrame', {
    configurable: true,
    value: requestAnimationFrame,
  });
  Object.defineProperty(window, 'cancelAnimationFrame', {
    configurable: true,
    value: cancelAnimationFrame,
  });
  return {
    stream,
    getUserMedia,
    analyser,
    source,
    close,
    trackStop,
    requestAnimationFrame,
    cancelAnimationFrame,
    runFrame: () => {
      const current = frame;
      frame = null;
      current?.(0);
    },
  };
}

describe('useMicLevel', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('samples microphone levels and releases all resources', async () => {
    const browser = installMocks();
    const onLevel = vi.fn();
    const { result, unmount } = renderHook(() => useMicLevel(onLevel));

    await act(async () => {
      await result.current.start();
    });
    expect(browser.source.connect).toHaveBeenCalledWith(browser.analyser);
    await act(async () => browser.runFrame());
    expect(onLevel).toHaveBeenCalledWith(expect.any(Number));
    expect(onLevel.mock.calls.some(([level]) => level > 0)).toBe(true);

    act(() => result.current.stop());
    expect(browser.trackStop).toHaveBeenCalledTimes(1);
    expect(browser.close).toHaveBeenCalledTimes(1);
    expect(browser.cancelAnimationFrame).toHaveBeenCalledWith(7);
    expect(onLevel).toHaveBeenLastCalledWith(0);
    unmount();
  });

  it('supports an existing stream, React state reporting, and repeated start guards', async () => {
    const browser = installMocks();
    const { result } = renderHook(() => useMicLevel());
    await act(async () => {
      await result.current.start(browser.stream);
    });
    await act(async () => browser.runFrame());
    expect(result.current.level).toBeGreaterThan(0);
    await act(async () => {
      await result.current.start(browser.stream);
    });
    expect(browser.getUserMedia).not.toHaveBeenCalled();
    expect(result.current.levelRef.current).toBeGreaterThan(0);
    act(() => result.current.stop());
  });

  it('stops cleanly when microphone setup fails', async () => {
    const browser = installMocks();
    browser.getUserMedia.mockRejectedValueOnce(new Error('unavailable'));
    const onLevel = vi.fn();
    const { result } = renderHook(() => useMicLevel(onLevel));
    await act(async () => {
      await result.current.start();
    });
    expect(onLevel).toHaveBeenLastCalledWith(0);
    expect(result.current.level).toBe(0);
  });
});
