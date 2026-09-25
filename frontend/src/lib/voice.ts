import { useCallback, useEffect, useRef, useState } from 'react';
import { OciSpeechRecognition } from './ociSpeech';

interface SpeechResultLike {
  0?: { transcript?: string; confidence?: number };
  isFinal?: boolean;
}

interface SpeechEventLike {
  results: ArrayLike<SpeechResultLike>;
}

interface RecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  onspeechstart: (() => void) | null;
  onresult: ((event: SpeechEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
  closed?: boolean;
}

type RecognitionConstructor = new () => RecognitionLike;

interface SpeechWindow extends Window {
  SpeechRecognition?: RecognitionConstructor;
  webkitSpeechRecognition?: RecognitionConstructor;
  __OTL_E2E_BROWSER_SPEECH__?: boolean;
}

interface SpeechCallbacks {
  onFinal?: (text: string) => void;
  onInterim?: (text: string) => void;
  onSpeechStart?: () => void;
}

const BROWSER_SPEECH_NOTICE =
  'Browser speech is active after your consent. Microphone audio is processed by your browser speech service.';

export function useSpeechInput() {
  const [supported] = useState(() => {
    if (typeof window === 'undefined') return false;
    const speechWindow = window as SpeechWindow;
    return !!(
      speechWindow.SpeechRecognition ||
      speechWindow.webkitSpeechRecognition ||
      navigator.mediaDevices?.getUserMedia
    );
  });
  const [listening, setListening] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [browserSpeechFallbackAvailable, setBrowserSpeechFallbackAvailable] =
    useState(false);
  const recognitionRef = useRef<RecognitionLike | null>(null);
  const isListeningRef = useRef(false);
  const sessionActiveRef = useRef(false);
  const browserFallbackPendingRef = useRef(false);
  const callbacksRef = useRef<SpeechCallbacks>({});
  const launchBrowserFallbackRef = useRef<(() => void) | null>(null);

  const stop = useCallback((cancel = false) => {
    sessionActiveRef.current = false;
    browserFallbackPendingRef.current = false;
    isListeningRef.current = false;
    callbacksRef.current = {};
    launchBrowserFallbackRef.current = null;
    setBrowserSpeechFallbackAvailable(false);
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    if (recognition) {
      try {
        if (cancel) recognition.abort();
        else recognition.stop();
      } catch {
        recognition.abort();
      }
    }
    setListening(false);
  }, []);

  const useBrowserSpeechFallback = useCallback(() => {
    launchBrowserFallbackRef.current?.();
  }, []);

  const start = useCallback(
    async (
      onFinal: (text: string) => void,
      onInterim?: (text: string) => void,
      onSpeechStart?: () => void,
      continuous = true
    ) => {
      setErrorMsg(null);
      setNotice(null);
      setBrowserSpeechFallbackAvailable(false);
      if (!supported || typeof window === 'undefined') return;
      stop(true);
      sessionActiveRef.current = true;
      callbacksRef.current = { onFinal, onInterim, onSpeechStart };
      isListeningRef.current = true;
      setListening(true);

      const speechWindow = window as SpeechWindow;
      const BrowserSpeech =
        speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;

      const offerBrowserFallback = () => {
        if (!sessionActiveRef.current) return;
        if (!BrowserSpeech) {
          isListeningRef.current = false;
          setListening(false);
          setErrorMsg('OCI speech is unavailable. Type your reply or try again.');
          return;
        }
        browserFallbackPendingRef.current = true;
        setBrowserSpeechFallbackAvailable(true);
        setErrorMsg(
          'OCI speech is unavailable. No browser speech fallback was started. Browser speech uses a different speech service.'
        );
      };

      const launchEngine = (
        EngineClass: RecognitionConstructor,
        isBrowserSpeech: boolean
      ) => {
        let recognition: RecognitionLike;
        try {
          recognition = new EngineClass();
        } catch (error: unknown) {
          if (!isBrowserSpeech && BrowserSpeech) {
            isListeningRef.current = false;
            setListening(false);
            offerBrowserFallback();
            return;
          }
          const name = error instanceof Error ? error.name : '';
          isListeningRef.current = false;
          setListening(false);
          setErrorMsg(
            name === 'NotAllowedError'
              ? 'Microphone access blocked. Please allow microphone in browser settings.'
              : 'Microphone error. Please check your input device.'
          );
          return;
        }
        recognition.continuous = continuous;
        recognition.interimResults = true;
        recognition.lang = navigator.language || 'en-US';
        recognition.maxAlternatives = 1;

        let hasStarted = false;
        let lastFinal = '';
        let lastInterim = '';
        let completedFinal = '';
        const rejectedFinals = new Map<number, string>();
        const isCurrent = () =>
          isListeningRef.current && recognitionRef.current === recognition;

        recognition.onspeechstart = () => {
          if (!isCurrent()) return;
          if (hasStarted) return;
          hasStarted = true;
          callbacksRef.current.onSpeechStart?.();
        };

        recognition.onresult = (event) => {
          if (!isCurrent()) return;
          const interimParts: string[] = [];
          const finalParts: string[] = [];
          let hasNewRejectedFinal = false;
          for (let index = 0; index < event.results.length; index += 1) {
            const result = event.results[index];
            const transcript = (result[0]?.transcript || '').trim();
            if (!transcript) continue;
            if (result.isFinal) {
              const confidence = result[0]?.confidence;
              if (
                Number.isFinite(confidence) &&
                confidence !== undefined &&
                confidence > 0 &&
                confidence < 0.5
              ) {
                if (rejectedFinals.get(index) !== transcript) {
                  hasNewRejectedFinal = true;
                  rejectedFinals.set(index, transcript);
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
            lastFinal = finalTranscript;
            hasStarted = false;
            setErrorMsg(
              "I couldn't hear that clearly. Please repeat or type your reply."
            );
            callbacksRef.current.onInterim?.('');
            return;
          }
          if (!hasStarted && (hasNewFinal || hasNewInterim)) {
            hasStarted = true;
            callbacksRef.current.onSpeechStart?.();
            if (!isCurrent()) return;
          }
          if (interimCleared) {
            callbacksRef.current.onInterim?.('');
            if (!isCurrent()) return;
          }
          if (hasNewFinal) {
            lastFinal = finalTranscript;
            hasStarted = !!interimTranscript;
            setErrorMsg(isBrowserSpeech ? BROWSER_SPEECH_NOTICE : null);
            setNotice(isBrowserSpeech ? BROWSER_SPEECH_NOTICE : null);
            callbacksRef.current.onFinal?.(finalTranscript);
            if (!isCurrent()) return;
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

        recognition.onerror = (event) => {
          if (!isCurrent()) return;
          const error = event.error;
          if (error === 'not-allowed' || error === 'service-not-allowed') {
            setErrorMsg(
              'Microphone access blocked. Please allow microphone in browser settings.'
            );
            stop(true);
          } else if (error === 'network' && !isBrowserSpeech) {
            offerBrowserFallback();
          } else if (error === 'network') {
            setErrorMsg(
              'Browser speech could not connect. Type your reply or try again.'
            );
            stop(true);
          } else if (error === 'no-speech') {
            return;
          } else if (error !== 'aborted') {
            setErrorMsg('Speech recognition stopped unexpectedly.');
            stop(true);
          }
        };

        recognition.onend = () => {
          if (!isCurrent()) return;
          if (recognition.closed) {
            recognitionRef.current = null;
            isListeningRef.current = false;
            setListening(false);
            if (browserFallbackPendingRef.current) return;
            sessionActiveRef.current = false;
            setErrorMsg(
              'Speech recognition session closed. Tap the microphone to try again.'
            );
            return;
          }
          if (continuous) {
            try {
              completedFinal = lastFinal;
              lastInterim = '';
              rejectedFinals.clear();
              hasStarted = false;
              recognition.start();
              return;
            } catch {
              stop(true);
              return;
            }
          }
          recognitionRef.current = null;
          isListeningRef.current = false;
          sessionActiveRef.current = false;
          setListening(false);
        };

        recognitionRef.current = recognition;
        try {
          recognition.start();
        } catch (error: unknown) {
          if (!isBrowserSpeech && BrowserSpeech) {
            recognitionRef.current = null;
            try {
              recognition.abort();
            } catch {
              setListening(false);
            }
            isListeningRef.current = false;
            setListening(false);
            offerBrowserFallback();
            return;
          }
          const name = error instanceof Error ? error.name : '';
          setErrorMsg(
            name === 'NotAllowedError'
              ? 'Microphone access blocked. Please allow microphone in browser settings.'
              : 'Speech recognition could not start.'
          );
          stop(true);
        }
      };

      launchBrowserFallbackRef.current = () => {
        if (!BrowserSpeech || !sessionActiveRef.current) return;
        const previous = recognitionRef.current;
        recognitionRef.current = null;
        previous?.abort();
        browserFallbackPendingRef.current = false;
        isListeningRef.current = true;
        setListening(true);
        setBrowserSpeechFallbackAvailable(false);
        setErrorMsg(BROWSER_SPEECH_NOTICE);
        launchEngine(BrowserSpeech, true);
      };

      const useTestBrowserSpeech =
        import.meta.env.MODE === 'test' ||
        speechWindow.__OTL_E2E_BROWSER_SPEECH__ === true;
      if (useTestBrowserSpeech && BrowserSpeech) launchEngine(BrowserSpeech, true);
      else launchEngine(OciSpeechRecognition, false);
    },
    [stop, supported]
  );

  const isListening = useCallback(
    () => isListeningRef.current || listening,
    [listening]
  );

  useEffect(() => () => stop(true), [stop]);

  return {
    supported,
    listening,
    isListening,
    errorMsg,
    notice,
    browserSpeechFallbackAvailable,
    useBrowserSpeechFallback,
    start,
    stop,
  };
}

export function useAudioPlayer() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const resolveRef = useRef<
    | ((value: {
        success: boolean;
        autoplayBlocked?: boolean;
        interrupted?: boolean;
      }) => void)
    | null
  >(null);
  const [playing, setPlaying] = useState(false);

  const release = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.onended = null;
      audio.onpause = null;
      audio.onerror = null;
      audio.pause();
      audio.src = '';
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    const resolve = resolveRef.current;
    resolveRef.current = null;
    release();
    setPlaying(false);
    resolve?.({ success: false, interrupted: true });
  }, [release]);

  const play = useCallback(
    (blob: Blob): Promise<{
      success: boolean;
      autoplayBlocked?: boolean;
      interrupted?: boolean;
    }> =>
      new Promise((resolve) => {
        stop();
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        resolveRef.current = resolve;
        const finish = (result: {
          success: boolean;
          autoplayBlocked?: boolean;
        }) => {
          if (resolveRef.current !== resolve) return;
          resolveRef.current = null;
          release();
          setPlaying(false);
          resolve(result);
        };
        audio.onended = () => finish({ success: true });
        audio.onpause = () => finish({ success: false });
        audio.onerror = () =>
          finish({
            success: false,
            autoplayBlocked:
              audio.error?.code === 4 ||
              (typeof DOMException !== 'undefined' &&
                audio.error?.code === undefined),
          });
        void audio
          .play()
          .then(() => {
            if (urlRef.current === url) setPlaying(true);
          })
          .catch((error: unknown) => {
            const autoplayBlocked =
              error instanceof DOMException && error.name === 'NotAllowedError';
            finish({ success: false, autoplayBlocked });
          });
      }),
    [release, stop]
  );

  useEffect(() => () => stop(), [stop]);

  return { play, stop, playing };
}
