import { useCallback, useEffect, useRef, useState } from "react";

const WORKLET_CODE = `
class STTProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = [];
  }
  process(inputs) {
    const input = inputs[0];
    if (input.length > 0) {
      const channelData = input[0];
      // simple 3:1 decimation (48k -> 16k)
      for (let i = 0; i < channelData.length; i += 3) {
         let sum = channelData[i];
         let count = 1;
         if (i+1 < channelData.length) { sum+=channelData[i+1]; count++; }
         if (i+2 < channelData.length) { sum+=channelData[i+2]; count++; }
         const val = Math.max(-1, Math.min(1, sum/count));
         this.buffer.push(val * 0x7FFF);
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
  const [supported] = useState(() => !!navigator.mediaDevices?.getUserMedia && !!window.AudioContext);
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
         const actx = new AudioContext({ sampleRate: 48000 });
         ctxRef.current = actx;
         
         const blob = new Blob([WORKLET_CODE], { type: "application/javascript" });
         const url = URL.createObjectURL(blob);
         await actx.audioWorklet.addModule(url);
         URL.revokeObjectURL(url);
         
         const source = actx.createMediaStreamSource(stream);
         const node = new AudioWorkletNode(actx, "stt-processor");
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
