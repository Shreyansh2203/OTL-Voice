import { useCallback, useEffect, useRef, useState } from 'react';

interface IWindowWithSpeech extends Window {
  SpeechRecognition?: any;
  webkitSpeechRecognition?: any;
}

export function useSpeechInput() {
  const [supported] = useState(() => {
    if (typeof window === 'undefined') return false;
    const win = window as unknown as IWindowWithSpeech;
    return !!(win.SpeechRecognition || win.webkitSpeechRecognition);
  });
  const [listening, setListening] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const recognitionRef = useRef<any>(null);
  const isListeningRef = useRef(false);
  const callbacksRef = useRef<{
    onFinal?: (text: string) => void;
    onInterim?: (text: string) => void;
    onSpeechStart?: () => void;
  }>({});

  const stop = useCallback((cancel = false) => {
    isListeningRef.current = false;
    if (recognitionRef.current) {
      const rec = recognitionRef.current;
      recognitionRef.current = null;
      try {
        if (cancel) {
          rec.abort();
        } else {
          rec.stop();
        }
      } catch {
        // ignore errors during stop/abort
      }
    }
    setListening(false);
  }, []);

  const start = useCallback(
    async (
      onFinal: (text: string) => void,
      onInterim?: (text: string) => void,
      onSpeechStart?: () => void,
      continuous = true
    ) => {
      setErrorMsg(null);
      if (!supported || typeof window === 'undefined') return;

      // Stop any existing instance
      stop(true);

      callbacksRef.current = { onFinal, onInterim, onSpeechStart };
      isListeningRef.current = true;
      setListening(true);

      const win = window as unknown as IWindowWithSpeech;
      const SpeechRecognitionClass =
        win.SpeechRecognition || win.webkitSpeechRecognition;
      if (!SpeechRecognitionClass) {
        setListening(false);
        isListeningRef.current = false;
        return;
      }

      try {
        const recognition = new SpeechRecognitionClass();
        recognition.continuous = continuous;
        recognition.interimResults = true;
        recognition.lang =
          typeof navigator !== 'undefined'
            ? navigator.language || 'en-US'
            : 'en-US';
        recognition.maxAlternatives = 1;

        let hasStarted = false;
        let lastFinal = '';

        recognition.onspeechstart = () => {
          if (!isListeningRef.current) return;
          if (!hasStarted) {
            hasStarted = true;
            callbacksRef.current.onSpeechStart?.();
          }
        };

        recognition.onaudiostart = () => {
          if (!isListeningRef.current) return;
          if (!hasStarted) {
            hasStarted = true;
            callbacksRef.current.onSpeechStart?.();
          }
        };

        recognition.onresult = (event: any) => {
          let interimTranscript = '';
          let finalTranscript = '';

          for (let i = 0; i < event.results.length; ++i) {
            const result = event.results[i];
            const transcript = result[0]?.transcript || '';
            if (result.isFinal) {
              finalTranscript += transcript;
            } else {
              interimTranscript += transcript;
            }
          }

          if (
            !hasStarted &&
            isListeningRef.current &&
            (interimTranscript.trim() || finalTranscript.trim())
          ) {
            hasStarted = true;
            callbacksRef.current.onSpeechStart?.();
          }

          if (finalTranscript.trim()) {
            const cleanFinal = finalTranscript.trim();
            if (cleanFinal !== lastFinal) {
              lastFinal = cleanFinal;
              hasStarted = false;
              callbacksRef.current.onFinal?.(cleanFinal);
            }
            if (!continuous) {
              stop();
            }
          }
          if (interimTranscript.trim()) {
            const combined = finalTranscript ? finalTranscript + ' ' + interimTranscript : interimTranscript;
            callbacksRef.current.onInterim?.(combined.trim());
          }
        };

        recognition.onerror = (event: any) => {
          const err = event?.error;
          if (err === 'not-allowed' || err === 'service-not-allowed') {
            setErrorMsg(
              'Microphone access blocked. Please allow mic in browser settings.'
            );
            stop(true);
          } else if (err === 'no-speech') {
            // Non-fatal, keep listening if continuous
          } else if (err !== 'aborted') {
            console.warn('Web Speech API recognition error:', err);
          }
        };

        recognition.onend = () => {
          if (
            isListeningRef.current &&
            continuous &&
            recognitionRef.current === recognition
          ) {
            try {
              recognition.start();
              return;
            } catch {
              // Ignore if already started or interrupted
            }
          }
          if (recognitionRef.current === recognition) {
            recognitionRef.current = null;
            setListening(false);
            isListeningRef.current = false;
          }
        };

        recognitionRef.current = recognition;
        recognition.start();
      } catch (err: any) {
        setListening(false);
        isListeningRef.current = false;
        let msg = 'Microphone error: ' + (err.message || String(err));
        if (err.name === 'NotAllowedError') {
          msg =
            'Microphone access blocked. Please allow mic in browser settings.';
        }
        setErrorMsg(msg);
      }
    },
    [supported, stop]
  );

  const isListening = useCallback(
    () => isListeningRef.current || listening,
    [listening]
  );

  useEffect(() => () => stop(true), [stop]);

  return { supported, listening, isListening, errorMsg, start, stop };
}

export function useAudioPlayer() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const resolveRef = useRef<
    | ((val: {
        success: boolean;
        autoplayBlocked?: boolean;
        interrupted?: boolean;
      }) => void)
    | null
  >(null);
  const [playing, setPlaying] = useState(false);

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    setPlaying(false);
    if (resolveRef.current) {
      resolveRef.current({ success: false, interrupted: true });
      resolveRef.current = null;
    }
  }, []);

  const play = useCallback(
    (
      blob: Blob
    ): Promise<{
      success: boolean;
      autoplayBlocked?: boolean;
      interrupted?: boolean;
    }> => {
      return new Promise((resolve) => {
        stop();
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        resolveRef.current = resolve;

        audio.onended = () => {
          setPlaying(false);
          if (urlRef.current) {
            URL.revokeObjectURL(urlRef.current);
            urlRef.current = null;
          }
          if (resolveRef.current === resolve) {
            resolveRef.current = null;
            resolve({ success: true });
          }
        };

        audio.onpause = () => {
          setPlaying(false);
          if (resolveRef.current === resolve) {
            resolveRef.current = null;
            resolve({ success: false });
          }
        };

        audio.onerror = (e) => {
          setPlaying(false);
          const isAutoplayBlocked =
            audio.error?.code === 4 || (e as any).name === 'NotAllowedError';
          if (resolveRef.current === resolve) {
            resolveRef.current = null;
            resolve({ success: false, autoplayBlocked: isAutoplayBlocked });
          }
        };

        audio
          .play()
          .then(() => {
            setPlaying(true);
          })
          .catch((err) => {
            setPlaying(false);
            const isAutoplayBlocked =
              err.name === 'NotAllowedError' || err.name === 'AbortError';
            if (resolveRef.current === resolve) {
              resolveRef.current = null;
              resolve({ success: false, autoplayBlocked: isAutoplayBlocked });
            }
          });
      });
    },
    [stop]
  );

  useEffect(
    () => () => {
      stop();
    },
    [stop]
  );

  return { play, stop, playing };
}
