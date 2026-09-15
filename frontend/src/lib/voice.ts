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
    callbacksRef.current = {};
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
        let lastInterim = '';
        let completedFinal = '';
        const rejectedFinals = new Map<number, string>();
        const isCurrentRecognition = () =>
          isListeningRef.current && recognitionRef.current === recognition;

        recognition.onspeechstart = () => {
          if (!isCurrentRecognition()) return;
          if (!hasStarted) {
            hasStarted = true;
            callbacksRef.current.onSpeechStart?.();
          }
        };

        recognition.onresult = (event: any) => {
          if (!isCurrentRecognition()) return;
          const interimParts: string[] = [];
          const finalParts: string[] = [];
          let hasNewRejectedFinal = false;

          for (let i = 0; i < event.results.length; ++i) {
            const result = event.results[i];
            const transcript = (result[0]?.transcript || '').trim();
            if (!transcript) continue;
            if (result.isFinal) {
              const confidence = result[0]?.confidence;
              // Some browsers omit confidence or report zero when it is
              // unavailable. Only reject an explicit, positive low score.
              if (
                Number.isFinite(confidence) &&
                confidence > 0 &&
                confidence < 0.5
              ) {
                if (rejectedFinals.get(i) !== transcript) {
                  hasNewRejectedFinal = true;
                  rejectedFinals.set(i, transcript);
                }
                continue;
              }
              finalParts.push(transcript);
            } else {
              interimParts.push(transcript);
            }
          }
          const finalTranscript = [completedFinal, ...finalParts]
            .filter(Boolean)
            .join(' ');
          const interimTranscript = interimParts.join(' ');
          const hasNewFinal =
            !!finalTranscript && finalTranscript !== lastFinal;
          const hasNewInterim =
            !!interimTranscript && interimTranscript !== lastInterim;
          const interimCleared = !!lastInterim && !interimTranscript;
          lastInterim = interimTranscript;

          if (hasNewRejectedFinal) {
            // Clear the provisional draft and cancel any prior send timer.
            // Do not turn an earlier accepted fragment into a new final here.
            lastFinal = finalTranscript;
            hasStarted = false;
            setErrorMsg(
              "I couldn't hear that clearly. Please repeat or type your reply."
            );
            callbacksRef.current.onInterim?.('');
            return;
          }

          // A cumulative result can contain only previously finalized words.
          // That is not evidence of a new utterance or an interruption.
          if (!hasStarted && (hasNewFinal || hasNewInterim)) {
            hasStarted = true;
            callbacksRef.current.onSpeechStart?.();
            if (!isCurrentRecognition()) return;
          }

          if (interimCleared) {
            callbacksRef.current.onInterim?.('');
            if (!isCurrentRecognition()) return;
          }

          if (hasNewFinal) {
            lastFinal = finalTranscript;
            hasStarted = !!interimTranscript;
            setErrorMsg(null);
            callbacksRef.current.onFinal?.(finalTranscript);
            if (!isCurrentRecognition()) return;
            if (!continuous) {
              stop();
              return;
            }
          }
          if (interimTranscript && (hasNewFinal || hasNewInterim)) {
            callbacksRef.current.onInterim?.(
              [finalTranscript, interimTranscript].filter(Boolean).join(' ')
            );
          }
        };

        recognition.onerror = (event: any) => {
          if (!isCurrentRecognition()) return;
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
          if (!isCurrentRecognition()) return;
          if (continuous) {
            try {
              // Browser restarts reset their results array; retain finalized
              // words from earlier cycles of this same dictation session.
              completedFinal = lastFinal;
              lastInterim = '';
              rejectedFinals.clear();
              hasStarted = false;
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
