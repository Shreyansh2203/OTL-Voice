import type { TimecardEntry } from "../types";
const FENCED_JSON = /```(?:json)?\s*(\{[\s\S]*?\})\s*```/;
export function extractEntries(text: string): TimecardEntry[] | null {
  const match = FENCED_JSON.exec(text || "");
  if (!match) return null;
  try {
    const data = JSON.parse(match[1]);
    if (data && Array.isArray(data.entries) && data.entries.length > 0) {
      return data.entries as TimecardEntry[];
    }
  } catch {
  }
  return null;
}
export function stripEntriesBlock(text: string): string {
  const fence = text.indexOf("```");
  return (fence === -1 ? text : text.slice(0, fence)).trim();
}