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
  }
  process(inputs) {
    const input = inputs[0];
    if (input.length > 0) {
      const channelData = input[0];
      // 1st-order IIR low-pass filter to prevent aliasing
      const alpha = Math.min(1.0, Math.max(0.1, 16000 / this.inputSampleRate));
      
      for (let i = 0; i < channelData.length; i++) {
         this.lastVal = this.lastVal + alpha * (channelData[i] - this.lastVal);
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
  const [supported] = useState(() => !!navigator.mediaDevices?.getUserMedia && !!(window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext));
  const [listening, setListening] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const manualStopRef = useRef(false);

  const cleanup = useCallback(() => {
    if (nodeRef.current) {
        nodeRef.current.disconnect();
        nodeRef.current = null;
    }
    if (ctxRef.current && ctxRef.current.state !== "closed") {
      ctxRef.current.close().catch(() => {});
      ctxRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
  }, []);

  const stop = useCallback((cancel = false) => {
    manualStopRef.current = cancel;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
       wsRef.current.send(new Uint8Array(0));
       if (cancel) {
          wsRef.current.close();
       }
    }
    cleanup();
    setListening(false);
  }, [cleanup]);

  const start = useCallback(async (
    onFinal: (text: string) => void,
    onInterim?: (text: string) => void,
    onSpeechStart?: () => void
  ) => {
    setErrorMsg(null);
    if (!supported) return;
    
    cleanup();
    if (wsRef.current) wsRef.current.close();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/api/stt/stream`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      let finalText = "";
      let hasStarted = false;
      let silenceTimer: ReturnType<typeof setTimeout> | null = null;

      const resetSilenceTimeout = () => {
        if (silenceTimer) clearTimeout(silenceTimer);
        silenceTimer = setTimeout(() => {
          stop(false);
        }, 10000);
      };

      ws.onopen = async () => {
         const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
         const actx = new AudioCtx();
         ctxRef.current = actx;
         
         const blob = new Blob([WORKLET_CODE], { type: "application/javascript" });
         const url = URL.createObjectURL(blob);
         await actx.audioWorklet.addModule(url);
         URL.revokeObjectURL(url);
         
         const source = actx.createMediaStreamSource(stream);
         const node = new AudioWorkletNode(actx, "stt-processor", {
            processorOptions: { sampleRate: actx.sampleRate }
         });
         nodeRef.current = node;
         
         node.port.onmessage = (e) => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(e.data);
                if (!hasStarted) {
                   hasStarted = true;
                   onSpeechStart?.();
                }
            }
         };
         
         source.connect(node);
         node.connect(actx.destination);
         setListening(true);
         resetSilenceTimeout();
      };

      ws.onmessage = (e) => {
         try {
            const data = JSON.parse(e.data);
            if (data.text) {
               finalText = data.text;
               if (data.isFinal) {
                  onFinal(finalText);
                  ws.close();
                  cleanup();
                  setListening(false);
                  if (silenceTimer) clearTimeout(silenceTimer);
               } else {
                  onInterim?.(finalText);
                  resetSilenceTimeout(); // Reset timer only when actual speech is recognized
               }
            }
         } catch(err) {
             console.error("WS error", err);
         }
      };

      ws.onerror = () => {
         setErrorMsg("Connection to speech server failed.");
         stop(true);
      };
      
      ws.onclose = () => {
         stop(true);
      };
      
    } catch (err: any) {
      setListening(false);
      let msg = "Microphone error: " + err.message;
      if (err.name === "NotAllowedError") msg = "Microphone access blocked.";
      setErrorMsg(msg);
    }
  }, [supported, cleanup, stop]);

  const isListening = useCallback(() => listening, [listening]);
  useEffect(() => () => stop(true), [stop]);

  return { supported, listening, isListening, errorMsg, start, stop };
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
