import type { TimecardEntry } from "../types";

const FENCED_JSON = /```(?:json)?\s*(\{[\s\S]*?\})\s*```/;

/**
 * Pull the `entries` array out of an assistant message's fenced JSON block.
 * Mirrors the backend's extraction so the client can show a review panel.
 */
export function extractEntries(text: string): TimecardEntry[] | null {
  const match = FENCED_JSON.exec(text || "");
  if (!match) return null;
  try {
    const data = JSON.parse(match[1]);
    if (data && Array.isArray(data.entries) && data.entries.length > 0) {
      return data.entries as TimecardEntry[];
    }
  } catch {
    /* incomplete/invalid JSON (e.g. still streaming) */
  }
  return null;
}

/**
 * Text to show in the bubble: everything before the JSON block. The assistant's
 * closing line precedes the fenced payload, so we cut from the first fence.
 */
export function stripEntriesBlock(text: string): string {
  const fence = text.indexOf("```");
  return (fence === -1 ? text : text.slice(0, fence)).trim();
}
