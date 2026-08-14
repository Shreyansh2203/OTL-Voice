import type { ChatEvent } from "../types";

/**
 * Read a `text/event-stream` response body and invoke `onEvent` for each
 * `data:` frame (parsed as JSON). POST-based SSE can't use `EventSource`
 * (GET-only), so we parse the stream ourselves.
 */
export async function readSse(
  response: Response,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  if (!response.body) throw new Error("No response body to stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      // Frames are separated by a blank line ("\n\n").
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const rawLine of frame.split("\n")) {
          const line = rawLine.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            onEvent(JSON.parse(payload) as ChatEvent);
          } catch {
            /* ignore malformed frame */
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
