import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Reports live microphone amplitude (0-1) for UI feedback (the voice orb)
 * and adaptive silence detection.
 *
 * Web Speech API (the current transcription engine, see voice.ts) manages
 * its own internal audio capture and does not expose the underlying
 * MediaStream, so this hook cannot literally share a single mic handle with
 * it today — it opens its own lightweight getUserMedia + AnalyserNode tap.
 * If `start(existingStream)` is called with a stream the caller already
 * owns (e.g. a future engine that does expose one, such as the OCI
 * streaming path), this hook reuses it instead of requesting a second one,
 * and will not stop a stream it doesn't own.
 */
export function useMicLevel() {
  const [level, setLevel] = useState(0);
  const streamRef = useRef<MediaStream | null>(null);
  const ownsStreamRef = useRef(false);
  const ctxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const dataRef = useRef<Uint8Array<ArrayBuffer> | null>(null);
  const activeRef = useRef(false);

  const stop = useCallback(() => {
    activeRef.current = false;
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (streamRef.current && ownsStreamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
    }
    streamRef.current = null;
    ownsStreamRef.current = false;
    if (ctxRef.current) {
      ctxRef.current.close().catch(() => {});
      ctxRef.current = null;
    }
    analyserRef.current = null;
    setLevel(0);
  }, []);

  const start = useCallback(
    async (existingStream?: MediaStream) => {
      if (activeRef.current) return;
      try {
        let stream = existingStream;
        let owns = false;
        if (!stream) {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          owns = true;
        }
        if (!activeRef.current && streamRef.current) return; // stopped while awaiting
        streamRef.current = stream;
        ownsStreamRef.current = owns;
        const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
        ctxRef.current = ctx;
        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.6;
        source.connect(analyser);
        analyserRef.current = analyser;
        dataRef.current = new Uint8Array(analyser.frequencyBinCount);
        activeRef.current = true;

        const tick = () => {
          if (!activeRef.current || !analyserRef.current || !dataRef.current) return;
          analyserRef.current.getByteTimeDomainData(dataRef.current);
          let sumSq = 0;
          for (let i = 0; i < dataRef.current.length; i++) {
            const v = (dataRef.current[i] - 128) / 128;
            sumSq += v * v;
          }
          const rms = Math.sqrt(sumSq / dataRef.current.length);
          // Perceptual compression so quiet speech still visibly moves the UI.
          const normalized = Math.min(1, Math.sqrt(rms) * 2.4);
          setLevel((prev) => prev + (normalized - prev) * 0.5);
          rafRef.current = requestAnimationFrame(tick);
        };
        rafRef.current = requestAnimationFrame(tick);
      } catch {
        // Permission denied or no mic — the orb just stays flat; the actual
        // STT hook surfaces the real error message to the user.
        stop();
      }
    },
    [stop]
  );

  useEffect(() => () => stop(), [stop]);

  return { level, start, stop };
}
