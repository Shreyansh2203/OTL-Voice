import { getWsApiUrl } from '../api/client';

const WEBSOCKET_OPEN_TIMEOUT_MS = 10_000;

export class OciSpeechRecognition {
  continuous = false;
  interimResults = false;
  lang = 'en-US';
  maxAlternatives = 1;
  onspeechstart: (() => void) | null = null;
  onresult: ((event: unknown) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  closed = false;

  private ws: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private openTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = true;
  private hasEmittedStart = false;
  private finalParts: string[] = [];
  private lastFinalTranscript = '';

  start(): void {
    this.stopped = false;
    this.closed = false;
    this.hasEmittedStart = false;
    this.finalParts = [];
    this.lastFinalTranscript = '';
    this._init().catch((error: unknown) => {
      if (this.stopped) return;
      const name = error instanceof Error ? error.name : '';
      this.onerror?.({
        error: name === 'NotAllowedError' ? 'not-allowed' : 'network',
      });
      this._cleanup();
    });
  }

  stop(): void {
    this._cleanup();
  }

  abort(): void {
    this._cleanup();
  }

  private _cleanup(): void {
    const wasActive = !this.stopped;
    this.stopped = true;
    this.closed = true;
    if (this.openTimer) {
      clearTimeout(this.openTimer);
      this.openTimer = null;
    }
    if (this.workletNode) {
      this.workletNode.port.onmessage = null;
      this.workletNode.disconnect();
      this.workletNode = null;
    }
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    if (this.audioCtx) {
      void this.audioCtx.close().catch(() => undefined);
      this.audioCtx = null;
    }
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    if (wasActive) this.onend?.();
  }

  private async _init(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (this.stopped) {
      this._cleanup();
      return;
    }

    const AudioContextClass =
      window.AudioContext ||
      (window as typeof window & { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioContextClass) throw new Error('AudioContext is unavailable');
    this.audioCtx = new AudioContextClass({ sampleRate: 16_000 });
    await this.audioCtx.audioWorklet.addModule('/stt-processor.js');
    if (this.stopped) {
      this._cleanup();
      return;
    }

    const source = this.audioCtx.createMediaStreamSource(this.stream);
    this.workletNode = new AudioWorkletNode(this.audioCtx, 'stt-processor');
    source.connect(this.workletNode);
    this.workletNode.connect(this.audioCtx.destination);

    const ws = new WebSocket(getWsApiUrl('/stt/stream'));
    this.ws = ws;
    this.openTimer = setTimeout(() => {
      if (this.stopped || ws.readyState === WebSocket.OPEN) return;
      this.onerror?.({ error: 'network' });
      this._cleanup();
    }, WEBSOCKET_OPEN_TIMEOUT_MS);

    ws.onopen = () => {
      if (this.stopped) return;
      if (this.openTimer) clearTimeout(this.openTimer);
      this.openTimer = null;
      this.workletNode!.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (event.data instanceof ArrayBuffer && ws.readyState === WebSocket.OPEN) {
          ws.send(event.data);
        }
      };
    };

    ws.onmessage = (event: MessageEvent<string>) => {
      if (this.stopped) return;
      try {
        const data: unknown = JSON.parse(event.data);
        if (!data || typeof data !== 'object') return;
        const record = data as Record<string, unknown>;
        if (typeof record.isFinal !== 'boolean' || typeof record.text !== 'string') {
          return;
        }
        const transcript = record.text.trim();
        if (!transcript) return;
        if (!this.hasEmittedStart) {
          this.hasEmittedStart = true;
          this.onspeechstart?.();
        }
        if (record.isFinal && transcript !== this.lastFinalTranscript) {
          this.finalParts.push(transcript);
          this.lastFinalTranscript = transcript;
        }
        const finalResults = this.finalParts.map((finalTranscript) => ({
          0: { transcript: finalTranscript, confidence: 1 },
          isFinal: true,
        }));
        this.onresult?.({
          resultIndex: 0,
          results: record.isFinal
            ? finalResults
            : [
                ...finalResults,
                {
                  0: { transcript, confidence: 1 },
                  isFinal: false,
                },
              ],
        });
      } catch {
        return;
      }
    };

    ws.onerror = () => {
      if (this.stopped) return;
      this.onerror?.({ error: 'network' });
      this._cleanup();
    };

    ws.onclose = () => {
      if (this.stopped) return;
      this._cleanup();
    };
  }
}
