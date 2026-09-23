import { getWsApiUrl } from '../api/client';

export class OciSpeechRecognition {
  continuous = false;
  interimResults = false;
  lang = 'en-US';
  maxAlternatives = 1;

  onspeechstart: (() => void) | null = null;
  onresult: ((event: any) => void) | null = null;
  onerror: ((event: any) => void) | null = null;
  onend: (() => void) | null = null;

  private ws: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private stopped = true;
  private hasEmittedStart = false;

  start() {
    this.stopped = false;
    this.hasEmittedStart = false;
    this._init().catch((e) => {
      if (this.stopped) return;
      this.onerror?.({
        error: e.name === 'NotAllowedError' ? 'not-allowed' : 'network',
      });
      this._cleanup();
    });
  }

  stop() {
    this._cleanup();
  }

  abort() {
    this._cleanup();
  }

  private _cleanup() {
    this.stopped = true;
    if (this.workletNode) {
      this.workletNode.disconnect();
      this.workletNode = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    if (this.audioCtx) {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.onend?.();
  }

  private async _init() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (this.stopped) return this._cleanup();

    this.audioCtx = new (window.AudioContext ||
      (window as any).webkitAudioContext)({
      sampleRate: 16000,
    });

    await this.audioCtx.audioWorklet.addModule('/stt-processor.js');
    if (this.stopped) return this._cleanup();

    const source = this.audioCtx.createMediaStreamSource(this.stream);
    this.workletNode = new AudioWorkletNode(this.audioCtx, 'stt-processor');
    source.connect(this.workletNode);
    this.workletNode.connect(this.audioCtx.destination); // Keep Safari worklet alive

    const wsUrl = getWsApiUrl('/stt/stream');
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      if (this.stopped) return;
      this.workletNode!.port.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) {
          if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(e.data);
          }
        }
      };
    };

    this.ws.onmessage = (e) => {
      if (this.stopped) return;
      try {
        const data = JSON.parse(e.data);
        if (data.isFinal !== undefined && data.text) {
          if (!this.hasEmittedStart) {
            this.hasEmittedStart = true;
            this.onspeechstart?.();
          }
          const event = {
            results: {
              length: 1,
              0: {
                0: { transcript: data.text, confidence: 1.0 },
                isFinal: data.isFinal,
              },
            },
          };
          this.onresult?.(event);
        }
      } catch {
        // ignore JSON parse errors
      }
    };

    this.ws.onerror = () => {
      if (this.stopped) return;
      this.onerror?.({ error: 'network' });
    };

    this.ws.onclose = () => {
      if (this.stopped) return;
      this._cleanup();
    };
  }
}
