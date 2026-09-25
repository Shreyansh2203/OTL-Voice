import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OciSpeechRecognition } from './ociSpeech';

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;
  readyState = FakeWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  sent: Array<ArrayBuffer> = [];
  constructor(public url: string) {}
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }
  receive(data: string) {
    this.onmessage?.({ data } as MessageEvent<string>);
  }
  send(data: ArrayBuffer) {
    this.sent.push(data);
  }
  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close'));
  }
}

const trackStop = vi.fn();

function installBrowserMocks() {
  const stream = { getTracks: () => [{ stop: trackStop }] } as unknown as MediaStream;
  const getUserMedia = vi.fn().mockResolvedValue(stream);
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  });
  const source = { connect: vi.fn() };
  const close = vi.fn().mockResolvedValue(undefined);
  const audioContext = {
    audioWorklet: { addModule: vi.fn().mockResolvedValue(undefined) },
    createMediaStreamSource: vi.fn(() => source),
    destination: {},
    close,
  };
  Object.defineProperty(window, 'AudioContext', {
    configurable: true,
    value: function AudioContext() {
      return audioContext;
    },
  });
  const worklet = {
    port: { onmessage: null as ((event: MessageEvent<ArrayBuffer>) => void) | null },
    connect: vi.fn(),
    disconnect: vi.fn(),
  };
  Object.defineProperty(window, 'AudioWorkletNode', {
    configurable: true,
    value: function AudioWorkletNode() {
      return worklet;
    },
  });
  const sockets: FakeWebSocket[] = [];
  class Socket extends FakeWebSocket {
    constructor(url: string) {
      super(url);
      sockets.push(this);
    }
  }
  Object.defineProperty(window, 'WebSocket', {
    configurable: true,
    value: Socket,
  });
  return { sockets, stream, getUserMedia, audioContext, worklet, source };
}

describe('OciSpeechRecognition', () => {
  let browser: ReturnType<typeof installBrowserMocks>;

  beforeEach(() => {
    trackStop.mockClear();
    browser = installBrowserMocks();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('streams interim and final transcripts and cleans up exactly once', async () => {
    const recognition = new OciSpeechRecognition();
    const onspeechstart = vi.fn();
    const onresult = vi.fn();
    const onerror = vi.fn();
    const onend = vi.fn();
    recognition.onspeechstart = onspeechstart;
    recognition.onresult = onresult;
    recognition.onerror = onerror;
    recognition.onend = onend;

    recognition.start();
    await vi.waitFor(() => expect(browser.sockets).toHaveLength(1));
    const socket = browser.sockets[0];
    socket.open();
    const buffer = new ArrayBuffer(4);
    browser.worklet.port.onmessage?.({
      data: buffer,
    } as MessageEvent<ArrayBuffer>);
    expect(socket.sent).toEqual([buffer]);

    socket.receive('not json');
    socket.receive(JSON.stringify({ isFinal: false, text: '' }));
    socket.receive(JSON.stringify({ isFinal: false, text: 'interim' }));
    socket.receive(JSON.stringify({ isFinal: true, text: 'final' }));
    socket.receive(JSON.stringify({ isFinal: true, text: 'final' }));
    expect(onspeechstart).toHaveBeenCalledTimes(1);
    expect(onresult).toHaveBeenCalledTimes(3);
    expect(onerror).not.toHaveBeenCalled();

    recognition.stop();
    recognition.stop();
    expect(trackStop).toHaveBeenCalledTimes(1);
    expect(browser.worklet.disconnect).toHaveBeenCalledTimes(1);
    expect(browser.audioContext.close).toHaveBeenCalledTimes(1);
    expect(onend).toHaveBeenCalledTimes(1);
  });

  it('maps microphone permission and websocket failures to cleanup errors', async () => {
    browser.getUserMedia.mockRejectedValueOnce(
      Object.assign(new Error('denied'), { name: 'NotAllowedError' })
    );
    const denied = new OciSpeechRecognition();
    const deniedError = vi.fn();
    denied.onerror = deniedError;
    denied.start();
    await vi.waitFor(() => expect(deniedError).toHaveBeenCalledWith({ error: 'not-allowed' }));
    denied.stop();

    browser.getUserMedia.mockResolvedValue(browser.stream);
    const failed = new OciSpeechRecognition();
    const failedError = vi.fn();
    const failedEnd = vi.fn();
    failed.onerror = failedError;
    failed.onend = failedEnd;
    failed.start();
    await vi.waitFor(() => expect(browser.sockets).toHaveLength(1));
    browser.sockets[0].onerror?.(new Event('error'));
    expect(failedError).toHaveBeenCalledWith({ error: 'network' });
    expect(failedEnd).toHaveBeenCalledTimes(1);
  });

  it('times out a websocket that never opens', async () => {
    vi.useFakeTimers();
    const recognition = new OciSpeechRecognition();
    const onerror = vi.fn();
    const onend = vi.fn();
    recognition.onerror = onerror;
    recognition.onend = onend;
    recognition.start();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(onerror).toHaveBeenCalledWith({ error: 'network' });
    expect(onend).toHaveBeenCalledTimes(1);
  });

  it('does not initialize audio after a pending microphone request is stopped', async () => {
    let resolveStream: ((stream: MediaStream) => void) | undefined;
    browser.getUserMedia.mockImplementationOnce(
      () => new Promise<MediaStream>((resolve) => {
        resolveStream = resolve;
      })
    );
    const recognition = new OciSpeechRecognition();
    const onend = vi.fn();
    recognition.onend = onend;
    recognition.start();
    recognition.stop();
    resolveStream?.(browser.stream);
    await Promise.resolve();
    expect(browser.audioContext.audioWorklet.addModule).not.toHaveBeenCalled();
    expect(onend).toHaveBeenCalledTimes(1);
  });
});
