import type { ChatMessage } from "../types";

/** Replace the content of the last assistant message (the streaming target). */
export function updateLastAssistant(
  messages: ChatMessage[],
  content: string,
  streaming: boolean
): ChatMessage[] {
  const next = [...messages];
  for (let i = next.length - 1; i >= 0; i--) {
    if (next[i].role === "assistant") {
      next[i] = { ...next[i], content, streaming };
      return next;
    }
  }
  return next;
}