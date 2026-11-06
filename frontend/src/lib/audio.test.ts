import { afterEach, describe, expect, it, vi } from 'vitest';
import { playMicStart, playMicStop, playThinkingCue } from './audio';

class FakeAudioContext {
  static OPEN = 1;
  currentTime = 0;
  destination = {};
  state: 'running' | 'suspended' = 'running';
  resumeState: 'running' | 'suspended' = 'running';
  failOscillator = false;
  readonly stateRef = { value: 'running' as 'running' | 'suspended' };

  getState() {
    return this.stateRef.value;
  }

  resume() {
    this.stateRef.value = this.resumeState;
    return Promise.resolve();
  }

  createOscillator() {
    if (this.failOscillator) throw new Error('oscillator unavailable');
    const oscillator = {
      type: 'sine',
      frequency: { setValueAtTime: vi.fn() },
      onended: undefined as (() => void) | undefined,
      connect: vi.fn(),
      start: vi.fn(() => {
        queueMicrotask(() => oscillator.onended?.());
      }),
      stop: vi.fn(),
    };
    return oscillator;
  }

  createGain() {
    return {
      gain: {
        setValueAtTime: vi.fn(),
        linearRampToValueAtTime: vi.fn(),
      },
      connect: vi.fn(),
    };
  }
}

describe('audio cues', () => {
  const originalAudioContext = window.AudioContext;

  afterEach(() => {
    Object.defineProperty(window, 'AudioContext', {
      configurable: true,
      value: originalAudioContext,
    });
  });

  it('plays complete tone sequences and handles suspended and unavailable contexts', async () => {
    const context = new FakeAudioContext();
    context.stateRef.value = 'running';
    Object.defineProperty(window, 'AudioContext', {
      configurable: true,
      value: function FakeContext() {
        return context;
      },
    });
    Object.defineProperty(context, 'state', {
      configurable: true,
      get: () => context.getState(),
    });

    await playMicStart();
    await playMicStop();
    await playThinkingCue();

    context.stateRef.value = 'suspended';
    context.resumeState = 'running';
    await playThinkingCue();

    context.resumeState = 'suspended';
    await playThinkingCue();

    context.stateRef.value = 'running';
    context.failOscillator = true;
    await expect(playThinkingCue()).resolves.toBeUndefined();
  });
});
