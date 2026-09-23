import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Reports live microphone amplitude (0-1) for UI feedback (the voice orb)
 * and adaptive silence detection.
 *
 * Supports an optional onLevel callback so 60 FPS microphone sampling can update
 * CSS transforms directly without triggering full React component re-renders.
 */
export function useMicLevel(onLevel?: (level: number) => void) {
  const [level, setLevel] = useState(0);
  const onLevelRef = useRef(onLevel);
  useEffect(() => {
    onLevelRef.current = onLevel;
  }, [onLevel]);

  const levelRef = useRef(0);
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
    levelRef.current = 0;

    if (onLevelRef.current) {
      onLevelRef.current(0);
    } else {
      setLevel(0);
    }
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
        const ctx = new (
          window.AudioContext || (window as any).webkitAudioContext
        )();
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
          if (!activeRef.current || !analyserRef.current || !dataRef.current)
            return;
          analyserRef.current.getByteTimeDomainData(dataRef.current);
          let sumSq = 0;
          for (let i = 0; i < dataRef.current.length; i++) {
            const v = (dataRef.current[i] - 128) / 128;
            sumSq += v * v;
          }
          const rms = Math.sqrt(sumSq / dataRef.current.length);
          // Perceptual compression so quiet speech still visibly moves the UI.
          const normalized = Math.min(1, Math.sqrt(rms) * 2.4);
          const next = levelRef.current + (normalized - levelRef.current) * 0.5;
          levelRef.current = next;

          if (onLevelRef.current) {
            onLevelRef.current(next);
          } else {
            setLevel(next);
          }

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

  return { level, levelRef, start, stop };
}
