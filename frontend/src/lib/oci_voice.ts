import { useCallback, useEffect, useRef, useState } from 'react';

export function useOciSpeechInput() {
  const [supported] = useState(true);
  const [listening, setListening] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const isListeningRef = useRef(false);
  
  const stop = useCallback(() => {
    isListeningRef.current = false;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    setListening(false);
  }, []);

  const start = useCallback(async (
    onFinal: (text: string) => void,
    onInterim?: (text: string) => void,
    onSpeechStart?: () => void,
    continuous = true
  ) => {
    stop();
    setErrorMsg(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/api/stt/stream`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      
      let finalTranscript = '';
      let hasStarted = false;
      let lastInterim = '';

      ws.onmessage = (ev) => {
        const data = JSON.parse(ev.data);
        if (!hasStarted && data.text) {
          hasStarted = true;
          onSpeechStart?.();
        }
        if (data.isFinal) {
          finalTranscript += (finalTranscript ? ' ' : '') + data.text;
          onFinal(finalTranscript.trim());
          hasStarted = false; // Reset so next utterance triggers onSpeechStart
          if (!continuous) stop();
        } else {
          lastInterim = data.text;
          onInterim?.((finalTranscript + (finalTranscript ? ' ' : '') + lastInterim).trim());
        }
      };

      ws.onerror = () => {
        setErrorMsg("WebSocket STT connection error.");
        stop();
      };

      ws.onclose = () => {
        stop();
      };

      await new Promise<void>((resolve, reject) => {
        if (ws.readyState === WebSocket.OPEN) return resolve();
        const timer = setTimeout(() => reject(new Error("Timeout connecting to STT WebSocket")), 5000);
        ws.onopen = () => {
          clearTimeout(timer);
          resolve();
        };
        const oldClose = ws.onclose;
        ws.onclose = (e) => {
          clearTimeout(timer);
          if (oldClose) oldClose.call(ws, e);
          reject(new Error("WebSocket closed before connecting."));
        };
      });

      const audioCtx = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioCtx;
      await audioCtx.audioWorklet.addModule('/stt-processor.js');
      
      const source = audioCtx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(audioCtx, 'stt-processor', {
        processorOptions: { sampleRate: audioCtx.sampleRate }
      });
      
      node.port.onmessage = (e) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(e.data);
        }
      };
      
      source.connect(node);
      node.connect(audioCtx.destination);
      
      isListeningRef.current = true;
      setListening(true);
    } catch (err: any) {
      if (wsRef.current === null) return; // User manually stopped the connection
      setErrorMsg(err.message || 'Microphone error.');
      stop();
    }
  }, [stop]);

  useEffect(() => {
    return stop;
  }, [stop]);

  return { supported, listening, errorMsg, start, stop };
}
