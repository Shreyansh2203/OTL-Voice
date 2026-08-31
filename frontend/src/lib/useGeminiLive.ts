import { useCallback, useEffect, useRef, useState } from 'react';

export type LiveVoiceState =
  'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking';

export interface ToolExecutionEvent {
  id?: string;
  name: string;
  response: Record<string, unknown>;
}

export function useGeminiLive() {
  const [liveState, setLiveState] = useState<LiveVoiceState>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<string>('');
  const [toolCalls, setToolCalls] = useState<ToolExecutionEvent[]>([]);
  const [isMuted, setIsMuted] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recorderNodeRef = useRef<AudioWorkletNode | null>(null);
  const playerNodeRef = useRef<AudioWorkletNode | null>(null);
  const isSessionActiveRef = useRef(false);
  const isMutedRef = useRef(false);

  useEffect(() => {
    isMutedRef.current = isMuted;
  }, [isMuted]);

  const stopSession = useCallback(() => {
    isSessionActiveRef.current = false;
    setLiveState('idle');

    if (recorderNodeRef.current) {
      try {
        recorderNodeRef.current.disconnect();
      } catch {
        // ignore
      }
      recorderNodeRef.current = null;
    }

    if (playerNodeRef.current) {
      try {
        playerNodeRef.current.port.postMessage({ type: 'flush' });
        playerNodeRef.current.disconnect();
      } catch {
        // ignore
      }
      playerNodeRef.current = null;
    }

    if (mediaStreamRef.current) {
      try {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      } catch {
        // ignore
      }
      mediaStreamRef.current = null;
    }

    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      try {
        audioCtxRef.current.close().catch(() => {});
      } catch {
        // ignore
      }
      audioCtxRef.current = null;
    }

    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
    }
  }, []);

  const startSession = useCallback(async () => {
    stopSession();
    setErrorMsg(null);
    setLiveState('connecting');
    setTranscript('');
    setToolCalls([]);
    isSessionActiveRef.current = true;

    try {
      // 1. Microphone setup with hardware AEC
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      mediaStreamRef.current = stream;

      // 2. Audio Context & Worklets
      const AudioContextClass =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      const ctx = new AudioContextClass();
      audioCtxRef.current = ctx;

      if (ctx.state === 'suspended') {
        await ctx.resume();
      }

      await ctx.audioWorklet.addModule('/audio/pcm_recorder_processor.js');
      await ctx.audioWorklet.addModule('/audio/pcm_player_processor.js');

      // Player Worklet
      const playerNode = new AudioWorkletNode(ctx, 'pcm-player-processor');
      playerNode.port.onmessage = (e) => {
        if (e.data?.type === 'empty') {
          if (isSessionActiveRef.current) {
            setLiveState('listening');
          }
        }
      };
      playerNode.connect(ctx.destination);
      playerNodeRef.current = playerNode;

      // 3. Connect Live WebSocket
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/api/voice/live`;
      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        if (isSessionActiveRef.current) {
          setLiveState('listening');
        }
      };

      ws.onmessage = (event) => {
        if (typeof event.data === 'string') {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'barge_in') {
              playerNodeRef.current?.port.postMessage({ type: 'flush' });
              setLiveState('listening');
            } else if (data.type === 'tool_executed' && data.calls) {
              setToolCalls((prev) => [...prev, ...data.calls]);
            } else if (data.text) {
              setTranscript((prev) => prev + ' ' + data.text);
            } else if (data.error) {
              setErrorMsg(data.error);
            }
          } catch {
            // ignore non-json
          }
        } else if (event.data instanceof ArrayBuffer) {
          // Received PCM audio data (24kHz 16-bit PCM from Gemini)
          setLiveState('speaking');
          const int16Array = new Int16Array(event.data);
          const float32Array = new Float32Array(int16Array.length);
          for (let i = 0; i < int16Array.length; i++) {
            float32Array[i] = int16Array[i] / 32768;
          }
          playerNodeRef.current?.port.postMessage(
            {
              type: 'push',
              buffer: float32Array.buffer,
            },
            [float32Array.buffer]
          );
        }
      };

      ws.onerror = () => {
        setErrorMsg(
          'Live Voice connection error. Check your network or API keys.'
        );
        stopSession();
      };

      ws.onclose = () => {
        if (isSessionActiveRef.current) {
          stopSession();
        }
      };

      // 4. Connect Microphone to Recorder Worklet
      const source = ctx.createMediaStreamSource(stream);
      const recorderNode = new AudioWorkletNode(ctx, 'pcm-recorder-processor', {
        processorOptions: { sampleRate: ctx.sampleRate },
      });
      recorderNodeRef.current = recorderNode;

      recorderNode.port.onmessage = (e) => {
        if (
          !isSessionActiveRef.current ||
          ws.readyState !== WebSocket.OPEN ||
          isMutedRef.current
        ) {
          return;
        }
        const msg = e.data;
        if (msg && msg.buffer) {
          if (msg.isVoiceActive && liveState === 'speaking') {
            // Client-side instant acoustic interruption
            playerNodeRef.current?.port.postMessage({ type: 'flush' });
            setLiveState('listening');
          }
          ws.send(msg.buffer);
        } else if (msg instanceof ArrayBuffer) {
          ws.send(msg);
        }
      };

      source.connect(recorderNode);
      recorderNode.connect(ctx.destination);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(`Could not start live voice session: ${msg}`);
      stopSession();
    }
  }, [liveState, stopSession]);

  const toggleMute = useCallback(() => {
    setIsMuted((prev) => !prev);
  }, []);

  useEffect(() => {
    return () => stopSession();
  }, [stopSession]);

  return {
    liveState,
    errorMsg,
    transcript,
    toolCalls,
    isMuted,
    startSession,
    stopSession,
    toggleMute,
    isActive: liveState !== 'idle',
  };
}
