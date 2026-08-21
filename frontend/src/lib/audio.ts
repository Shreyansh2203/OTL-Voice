/**
 * Simple tone generator for assistant "earcons" (chimes) using the Web Audio API.
 */

let audioCtx: AudioContext | null = null;

function getAudioContext() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
  }
  return audioCtx;
}

/** Plays a brief tone. */
function playTone(frequency: number, type: OscillatorType, durationMs: number): Promise<void> {
  return new Promise((resolve) => {
    try {
      const ctx = getAudioContext();
      // Resume context if suspended (common in browsers until user gesture)
      if (ctx.state === 'suspended') {
        ctx.resume().catch(() => {});
      }
      
      // If it is still suspended after trying to resume, resolve immediately to avoid hanging
      if (ctx.state === 'suspended') {
        return resolve();
      }

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = type;
      osc.frequency.setValueAtTime(frequency, ctx.currentTime);

      // Simple envelope to avoid clicks
      gain.gain.setValueAtTime(0, ctx.currentTime);
      gain.gain.linearRampToValueAtTime(0.1, ctx.currentTime + 0.02);
      gain.gain.setValueAtTime(0.1, ctx.currentTime + (durationMs / 1000) - 0.02);
      gain.gain.linearRampToValueAtTime(0, ctx.currentTime + (durationMs / 1000));

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + (durationMs / 1000));

      osc.onended = () => resolve();
    } catch {
      // Audio context might be blocked or unsupported; degrade gracefully
      resolve();
    }
  });
}

/** Plays an ascending double-chime to indicate the microphone is listening. */
export async function playMicStart() {
  await playTone(440, "sine", 100);
  await playTone(554, "sine", 150); // C#
}

/** Plays a descending double-chime to indicate the microphone has stopped listening. */
export async function playMicStop() {
  await playTone(554, "sine", 100);
  await playTone(440, "sine", 150);
}
