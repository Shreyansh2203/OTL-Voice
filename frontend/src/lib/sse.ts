import type { ChatEvent } from '../types';
export interface SseEvent {
  type: string;
  data: ChatEvent;
  id?: string;
  retry?: number;
}
export async function readSse(
  response: Response,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  if (!response.body) throw new Error('No response body to stream.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        let _eventType = 'message',
          _eventId: string | undefined,
          _retryMs: number | undefined;
        void _eventType;
        void _eventId;
        void _retryMs;
        for (const rawLine of frame.split('\n')) {
          const line = rawLine.trim();
          if (!line || line.startsWith(':')) continue;
          if (line.startsWith('event:')) {
            void (_eventType = line.slice(6).trim());
            continue;
          }
          if (line.startsWith('id:')) {
            void (_eventId = line.slice(3).trim());
            continue;
          }
          if (line.startsWith('retry:')) {
            const retryVal = parseInt(line.slice(6).trim(), 10);
            if (!isNaN(retryVal)) void (_retryMs = retryVal);
            continue;
          }
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            const eventData = JSON.parse(payload) as ChatEvent;
            onEvent(eventData);
          } catch (err) {
            console.warn(
              '[SSE] Failed to parse frame:',
              err,
              'payload:',
              payload.slice(0, 100)
            );
          }
        }
        if (_retryMs !== undefined) {
          // handled elsewhere
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
