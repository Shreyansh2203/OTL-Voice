import { useCallback, useEffect, useRef, useState } from "react";

const WORKLET_CODE = `
class STTProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.buffer = [];
    this.lastVal = 0;
    this.inputSampleRate = options?.processorOptions?.sampleRate || 48000;
    this.targetSampleRate = 16000;
    this.ratio = this.inputSampleRate / this.targetSampleRate;
    this.sampleAcc = 0;
    // Pre-calculate low-pass filter coefficient for anti-aliasing
    // alpha = 1 / (1 + 2*pi*fc/fs) where fc is cutoff frequency (targetSampleRate/2)
    const fc = this.targetSampleRate / 2;
    this.alpha = 1 / (1 + 2 * Math.PI * fc / this.inputSampleRate);
  }
  process(inputs) {
    const input = inputs[0];
    if (input.length > 0) {
      const channelData = input[0];
      // 1st-order IIR low-pass filter to prevent aliasing
      for (let i = 0; i < channelData.length; i++) {
         this.lastVal = this.lastVal + this.alpha * (channelData[i] - this.lastVal);
         this.sampleAcc += 1;
         if (this.sampleAcc >= this.ratio) {
             this.sampleAcc -= this.ratio;
             const val = Math.max(-1, Math.min(1, this.lastVal));
             this.buffer.push(val * 0x7FFF);
         }
      }
      if (this.buffer.length >= 4096) {
         const out = new Int16Array(this.buffer);
         this.port.postMessage(out.buffer, [out.buffer]);
         this.buffer = [];
      }
    }
    return true;
  }
}
registerProcessor("stt-processor", STTProcessor);
`;

export function useSpeechInput() {
  const [supported] = useState(
    () =>
      !!navigator.mediaDevices?.getUserMedia &&
      !!(
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext
      )
  );
  const [listening, setListening] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const isCleaningUpRef = useRef(false);
  const connectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isListeningRef = useRef(false);

  const cleanup = useCallback(() => {
    if (isCleaningUpRef.current) return;
    isCleaningUpRef.current = true;
    if (connectTimeoutRef.current) {
      clearTimeout(connectTimeoutRef.current);
      connectTimeoutRef.current = null;
    }
    if (nodeRef.current) {
      nodeRef.current.disconnect();
      nodeRef.current = null;
    }
    if (ctxRef.current && ctxRef.current.state !== "closed") {
      ctxRef.current.close().catch(() => {});
      ctxRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    isCleaningUpRef.current = false;
  }, []);

  const stop = useCallback(
    (cancel = false) => {
      isListeningRef.current = false;
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(new Uint8Array(0));
        if (cancel) {
          wsRef.current.close();
        }
      }
      cleanup();
      setListening(false);
    },
    [cleanup]
  );

  const start = useCallback(
    async (
      onFinal: (text: string) => void,
      onInterim?: (text: string) => void,
      onSpeechStart?: () => void,
      continuous = true
    ) => {
      setErrorMsg(null);
      if (!supported) return;
      cleanup();
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // ignore closed socket
        }
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
          },
        });
        streamRef.current = stream;
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/api/stt/stream`;
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;
        let finalText = "";
        let hasStarted = false;

        connectTimeoutRef.current = setTimeout(() => {
          if (ws.readyState === WebSocket.CONNECTING) {
            setErrorMsg("Connection to speech server timed out.");
            ws.close();
          }
        }, 10000);

        ws.onopen = async () => {
          if (connectTimeoutRef.current) {
            clearTimeout(connectTimeoutRef.current);
            connectTimeoutRef.current = null;
          }
          const AudioCtx =
            window.AudioContext ||
            (window as unknown as { webkitAudioContext: typeof AudioContext })
              .webkitAudioContext;
          const actx = new AudioCtx();
          ctxRef.current = actx;
          const blob = new Blob([WORKLET_CODE], {
            type: "application/javascript",
          });
          const url = URL.createObjectURL(blob);
          try {
            await actx.audioWorklet.addModule(url);
          } finally {
            URL.revokeObjectURL(url);
          }
          const source = actx.createMediaStreamSource(stream);
          const node = new AudioWorkletNode(actx, "stt-processor", {
            processorOptions: { sampleRate: actx.sampleRate },
          });
          nodeRef.current = node;
          node.port.onmessage = (e) => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(e.data);
            }
          };
          source.connect(node);
          setListening(true);
          isListeningRef.current = true;
        };

        ws.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data);
            if (data.text) {
              finalText = data.text;
              if (!hasStarted) {
                hasStarted = true;
                onSpeechStart?.();
              }
              if (data.isFinal) {
                const dispatched = finalText;
                finalText = "";
                hasStarted = false;
                onFinal(dispatched);
                if (!continuous) {
                  ws.close();
                  setListening(false);
                  isListeningRef.current = false;
                }
              } else {
                onInterim?.(finalText);
              }
            }
          } catch (err) {
            console.error("WS error", err);
          }
        };

        ws.onerror = () => {
          if (ws.readyState === WebSocket.CONNECTING) {
            setErrorMsg("Connection to speech server failed.");
          }
        };

        ws.onclose = () => {
          if (connectTimeoutRef.current) {
            clearTimeout(connectTimeoutRef.current);
            connectTimeoutRef.current = null;
          }
          setListening(false);
          isListeningRef.current = false;
          cleanup();
        };
      } catch (err: any) {
        if (connectTimeoutRef.current) {
          clearTimeout(connectTimeoutRef.current);
          connectTimeoutRef.current = null;
        }
        setListening(false);
        isListeningRef.current = false;
        let msg = "Microphone error: " + err.message;
        if (err.name === "NotAllowedError") msg = "Microphone access blocked.";
        setErrorMsg(msg);
      }
    },
    [supported, cleanup]
  );

  const isListening = useCallback(() => isListeningRef.current || listening, [listening]);
  useEffect(() => () => stop(true), [stop]);
  return { supported, listening, isListening, errorMsg, start, stop };
}

export function useAudioPlayer() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const resolveRef = useRef<
    ((val: { success: boolean; autoplayBlocked?: boolean; interrupted?: boolean }) => void) | null
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
    (blob: Blob): Promise<{ success: boolean; autoplayBlocked?: boolean; interrupted?: boolean }> => {
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
            audio.error?.code === 4 || (e as any).name === "NotAllowedError";
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
              err.name === "NotAllowedError" || err.name === "AbortError";
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