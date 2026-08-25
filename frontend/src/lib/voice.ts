import { useCallback, useEffect, useRef, useState } from "react";

const WORKLET_CODE = `
class STTProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.buffer = [];
    this.inputSampleRate = options?.processorOptions?.sampleRate || 16000;
    this.targetSampleRate = 16000;
    this.ratio = this.inputSampleRate / this.targetSampleRate;
    this.sampleAcc = 0;
    this.lastVal = 0;
    const fc = this.targetSampleRate / 2;
    this.alpha = 1 / (1 + (2 * Math.PI * fc) / this.inputSampleRate);
  }
  process(inputs) {
    const input = inputs[0];
    if (input && input.length > 0) {
      const channelData = input[0];
      if (!channelData) return true;
      if (this.inputSampleRate === 16000) {
        const out = new Int16Array(channelData.length);
        for (let i = 0; i < channelData.length; i++) {
          const s = Math.max(-1, Math.min(1, channelData[i]));
          out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        this.port.postMessage(out.buffer, [out.buffer]);
      } else {
        for (let i = 0; i < channelData.length; i++) {
          this.lastVal = this.lastVal + this.alpha * (channelData[i] - this.lastVal);
          this.sampleAcc += 1;
          if (this.sampleAcc >= this.ratio) {
            this.sampleAcc -= this.ratio;
            const s = Math.max(-1, Math.min(1, this.lastVal));
            this.buffer.push(s < 0 ? s * 0x8000 : s * 0x7fff);
          }
        }
        if (this.buffer.length >= 1024) {
          const out = new Int16Array(this.buffer);
          this.port.postMessage(out.buffer, [out.buffer]);
          this.buffer = [];
        }
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
  const audioDisconnectRef = useRef<(() => void) | null>(null);
  const isCleaningUpRef = useRef(false);
  const isListeningRef = useRef(false);

  const cleanup = useCallback(() => {
    if (isCleaningUpRef.current) return;
    isCleaningUpRef.current = true;
    if (audioDisconnectRef.current) {
      try {
        audioDisconnectRef.current();
      } catch (e) {
        void e;
      }
      audioDisconnectRef.current = null;
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
      setListening(true);
      isListeningRef.current = true;

      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // ignore
        }
      }
      try {
        let hasStarted = false;
        let lastFinal = "";

        // OCI Speech STT 16kHz PCM WebSocket streaming
        const AudioCtx =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext })
            .webkitAudioContext;
        let actx: AudioContext;
        try {
          actx = new AudioCtx({ sampleRate: 16000 });
        } catch {
          actx = new AudioCtx();
        }
        ctxRef.current = actx;
        if (actx.state === "suspended") {
          await actx.resume();
        }

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

        const onAudioChunk = (data: ArrayBuffer) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(data);
          }
        };

        // Try AudioWorklet first, then fall back cleanly to ScriptProcessorNode
        let workletLoaded = false;
        if (actx.audioWorklet) {
          try {
            await actx.audioWorklet.addModule("/stt-processor.js");
            workletLoaded = true;
          } catch {
            try {
              const blob = new Blob([WORKLET_CODE], {
                type: "application/javascript",
              });
              const url = URL.createObjectURL(blob);
              await actx.audioWorklet.addModule(url);
              workletLoaded = true;
            } catch {
              workletLoaded = false;
            }
          }
        }

        const source = actx.createMediaStreamSource(stream);
        const muteGain = actx.createGain();
        muteGain.gain.value = 0;
        let activeWorklet: AudioWorkletNode | null = null;
        let activeScriptNode: ScriptProcessorNode | null = null;

        if (workletLoaded) {
          try {
            activeWorklet = new AudioWorkletNode(actx, "stt-processor", {
              processorOptions: { sampleRate: actx.sampleRate },
            });
            activeWorklet.port.onmessage = (e) => onAudioChunk(e.data);
            source.connect(activeWorklet);
            activeWorklet.connect(muteGain);
            muteGain.connect(actx.destination);
          } catch {
            workletLoaded = false;
          }
        }

        if (!workletLoaded) {
          const bufferSize = 4096;
          activeScriptNode = actx.createScriptProcessor(bufferSize, 1, 1);
          if (actx.sampleRate === 16000) {
            activeScriptNode.onaudioprocess = (e) => {
              const channelData = e.inputBuffer.getChannelData(0);
              const pcm = new Int16Array(channelData.length);
              for (let i = 0; i < channelData.length; i++) {
                const s = Math.max(-1, Math.min(1, channelData[i]));
                pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
              }
              onAudioChunk(pcm.buffer);
            };
          } else {
            const inputSampleRate = actx.sampleRate;
            const targetSampleRate = 16000;
            const ratio = inputSampleRate / targetSampleRate;
            let sampleAcc = 0;
            let lastVal = 0;
            const fc = targetSampleRate / 2;
            const alpha = 1 / (1 + (2 * Math.PI * fc) / inputSampleRate);
            let pcmBuffer: number[] = [];

            activeScriptNode.onaudioprocess = (e) => {
              const channelData = e.inputBuffer.getChannelData(0);
              for (let i = 0; i < channelData.length; i++) {
                lastVal = lastVal + alpha * (channelData[i] - lastVal);
                sampleAcc += 1;
                if (sampleAcc >= ratio) {
                  sampleAcc -= ratio;
                  const s = Math.max(-1, Math.min(1, lastVal));
                  pcmBuffer.push(s < 0 ? s * 0x8000 : s * 0x7fff);
                }
              }
              if (pcmBuffer.length >= 1024) {
                const out = new Int16Array(pcmBuffer);
                onAudioChunk(out.buffer);
                pcmBuffer = [];
              }
            };
          }

          source.connect(activeScriptNode);
          activeScriptNode.connect(muteGain);
          muteGain.connect(actx.destination);
        }

        audioDisconnectRef.current = () => {
          try {
            activeWorklet?.disconnect();
          } catch (e) {
            void e;
          }
          try {
            activeScriptNode?.disconnect();
          } catch (e) {
            void e;
          }
          try {
            source.disconnect();
          } catch (e) {
            void e;
          }
          try {
            muteGain.disconnect();
          } catch (e) {
            void e;
          }
        };

        ws.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data);
            if (data.text) {
              const text = data.text;
              if (!hasStarted) {
                hasStarted = true;
                onSpeechStart?.();
              }
              if (data.isFinal) {
                const dispatched = text.trim();
                if (dispatched && dispatched !== lastFinal) {
                  lastFinal = dispatched;
                  hasStarted = false;
                  onFinal(dispatched);
                }
                if (!continuous) {
                  ws.close();
                  setListening(false);
                  isListeningRef.current = false;
                }
              } else {
                onInterim?.(text);
              }
            }
          } catch (err) {
            console.error("WS error", err);
          }
        };

        ws.onerror = (e) => {
          console.warn("WebSocket error on STT stream:", e);
        };
      } catch (err: any) {
        setListening(false);
        isListeningRef.current = false;
        let msg = "Microphone error: " + err.message;
        if (err.name === "NotAllowedError") msg = "Microphone access blocked. Please allow mic in browser settings.";
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