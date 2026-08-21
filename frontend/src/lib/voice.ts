import { useCallback, useEffect, useRef, useState } from "react";


type RecognitionCtor = new () => any;

function getRecognition(): RecognitionCtor | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

/**
 * Voice input via the browser's Web Speech API (Chrome/Edge). `start(onFinal)`
 * listens once and calls `onFinal` with the transcript when speech ends.
 */
export function useSpeechInput() {
  const [supported] = useState(() => getRecognition() !== null);
  const [listening, setListening] = useState(false);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const recRef = useRef<any>(null);

  const manualStopRef = useRef(false);

  const stop = useCallback((cancel = false) => {
    manualStopRef.current = cancel;
    if (cancel) {
      recRef.current?.stop?.(); // Use graceful stop instead of buggy abort
      setListening(false);
      recRef.current = null;
    } else {
      recRef.current?.stop?.();
    }
  }, []);

  const start = useCallback((
    onFinal: (text: string) => void,
    onInterim?: (text: string) => void,
    onSpeechStart?: () => void
  ) => {
    const Ctor = getRecognition();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.continuous = true;
    manualStopRef.current = false;

    let finalText = "";
    let silenceTimer: ReturnType<typeof setTimeout> | null = null;
    let speechStarted = false;

    const resetSilenceTimeout = () => {
      if (silenceTimer) clearTimeout(silenceTimer);
      silenceTimer = setTimeout(() => {
        rec.stop();
      }, 5000); // 5 seconds of silence auto-stops the mic and auto-sends
    };

    // Start the timer when listening begins
    resetSilenceTimeout();

    rec.onspeechstart = () => {
      if (!speechStarted) {
        speechStarted = true;
        onSpeechStart?.();
      }
    };

    rec.onresult = (e: any) => {
      if (!speechStarted) {
        speechStarted = true;
        onSpeechStart?.();
      }
      resetSilenceTimeout();
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) {
          finalText += e.results[i][0].transcript;
        } else {
          interim += e.results[i][0].transcript;
        }
      }
      onInterim?.((finalText + interim).trim());
    };
    rec.onerror = (e: any) => {
      if (silenceTimer) clearTimeout(silenceTimer);
      setListening(false);
      if (e.error === "not-allowed") {
        setPermissionDenied(true);
      }
    };
    rec.onend = () => {
      if (silenceTimer) clearTimeout(silenceTimer);
      setListening(false);
      recRef.current = null;
      const text = finalText.trim();
      const wasCanceled = manualStopRef.current;
      manualStopRef.current = false;
      if (text && !wasCanceled) onFinal(text);
    };

    recRef.current = rec;
    setListening(true);
    rec.start();
  }, []);

  const isListening = useCallback(() => {
    return recRef.current !== null;
  }, []);

  useEffect(() => () => recRef.current?.abort?.(), []);

  return { supported, listening, isListening, permissionDenied, start, stop };
}

/** Plays TTS audio blobs, one at a time, cleaning up object URLs. */
export function useAudioPlayer() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const [playing, setPlaying] = useState(false);

  const stop = useCallback(() => {
    audioRef.current?.pause();
    setPlaying(false);
  }, []);

  const play = useCallback(
    (blob: Blob): Promise<boolean> => {
      return new Promise((resolve) => {
        audioRef.current?.pause();
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        
        audio.onended = () => {
          setPlaying(false);
          resolve(true); // natural completion
        };
        audio.onpause = () => {
          setPlaying(false);
          resolve(false); // interrupted or stopped
        };
        audio.onerror = () => {
          setPlaying(false);
          resolve(false);
        };

        audio.play().then(() => {
          setPlaying(true);
        }).catch(() => {
          setPlaying(false); // autoplay may be blocked until a user gesture
          resolve(false);
        });
      });
    },
    []
  );

  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    []
  );

  return { play, stop, playing };
}
