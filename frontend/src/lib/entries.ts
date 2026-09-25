import type { TimecardEntry } from '../types';

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export const APP_TIMEZONE =
  import.meta.env.VITE_APP_TIMEZONE?.trim() || browserTimezone();
export const MAX_ENTRY_HOURS = 24;
export const MAX_DAILY_HOURS = 24;
export const HOUR_INCREMENT = 0.25;

const MAX_PARSED_ENTRIES = 100;
const ENTRY_FIELDS = new Set([
  'employeeNumber',
  'employeeName',
  'projectId',
  'projectNo',
  'projectName',
  'workOrder',
  'taskId',
  'taskDetails',
  'hours',
  'date',
  'startTime',
  'stopTime',
  'payrollTimeType',
  'expenditureType',
  'currencyCode',
]);
const REQUIRED_TEXT_FIELDS = [
  'employeeNumber',
  'employeeName',
  'projectId',
  'projectNo',
  'projectName',
  'workOrder',
  'taskDetails',
] as const;
const OPTIONAL_TEXT_FIELDS = [
  'taskId',
  'startTime',
  'stopTime',
  'payrollTimeType',
  'expenditureType',
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isValidDate(value: unknown): value is string {
  if (!isNonEmptyString(value) || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

function isValidTime(value: unknown): value is string {
  if (!isNonEmptyString(value)) return false;
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  return !!match && Number(match[1]) <= 23 && Number(match[2]) <= 59;
}

function hasValidTimes(value: Record<string, unknown>): boolean {
  const startTime = value.startTime;
  const stopTime = value.stopTime;
  if (startTime === undefined && stopTime === undefined) return true;
  if (!isValidTime(startTime) || !isValidTime(stopTime)) return false;
  const startMinutes = Number(startTime.slice(0, 2)) * 60 + Number(startTime.slice(3));
  const stopMinutes = Number(stopTime.slice(0, 2)) * 60 + Number(stopTime.slice(3));
  const hours = value.hours;
  if (typeof hours !== 'number') return false;
  return stopMinutes > startMinutes && stopMinutes - startMinutes === hours * 60;
}

function isValidEntry(value: unknown): value is TimecardEntry {
  if (!isRecord(value)) return false;
  if (Object.keys(value).some((field) => !ENTRY_FIELDS.has(field))) return false;
  if (!REQUIRED_TEXT_FIELDS.every((field) => isNonEmptyString(value[field]))) {
    return false;
  }
  if (typeof value.taskDetails !== 'string' || value.taskDetails.length > 80) {
    return false;
  }
  if (!OPTIONAL_TEXT_FIELDS.every((field) => value[field] === undefined || isNonEmptyString(value[field]))) {
    return false;
  }
  if (
    typeof value.hours !== 'number' ||
    !Number.isFinite(value.hours) ||
    value.hours <= 0 ||
    value.hours > MAX_ENTRY_HOURS
  ) {
    return false;
  }
  if (Math.round(value.hours / HOUR_INCREMENT) * HOUR_INCREMENT !== value.hours) {
    return false;
  }
  if (!isValidDate(value.date) || value.currencyCode !== 'USD') return false;
  return hasValidTimes(value);
}

function parseCandidate(candidate: string): TimecardEntry[] | null {
  const trimmed = candidate.trim();
  if (!trimmed) return null;
  try {
    const data: unknown = JSON.parse(trimmed);
    if (
      !isRecord(data) ||
      Object.keys(data).length !== 1 ||
      !Array.isArray(data.entries)
    ) {
      return null;
    }
    if (data.entries.length === 0 || data.entries.length > MAX_PARSED_ENTRIES) {
      return null;
    }
    return data.entries.every(isValidEntry) ? (data.entries as TimecardEntry[]) : null;
  } catch {
    return null;
  }
}

function candidateBlocks(text: string): string[] {
  const trimmed = text.trim();
  const candidates = [trimmed];
  const fencePattern = /```(?:json\s*)?([\s\S]*?)```/gi;
  for (const match of trimmed.matchAll(fencePattern)) {
    candidates.push(match[1]);
  }
  const tildePattern = /~~~(?:json\s*)?([\s\S]*?)~~~/gi;
  for (const match of trimmed.matchAll(tildePattern)) {
    candidates.push(match[1]);
  }
  return candidates;
}

export function extractEntries(text: string): TimecardEntry[] | null {
  if (!text?.trim()) return null;
  for (const candidate of candidateBlocks(text)) {
    const entries = parseCandidate(candidate);
    if (entries) return entries;
  }
  return null;
}

export function looksLikeTimesheetPayload(text: string): boolean {
  const value = text?.trim() || '';
  return (
    /```|~~~/.test(value) ||
    /^[{[]/.test(value) ||
    /["']entries["']\s*:/.test(value)
  );
}

export function stripEntriesBlock(text: string): string {
  const value = text || '';
  const fenced = value
    .replace(/```(?:json\s*)?[\s\S]*?```/gi, '')
    .replace(/~~~(?:json\s*)?[\s\S]*?~~~/gi, '')
    .trim();
  if (fenced) return fenced;
  const fenceIndex = value.search(/```|~~~/);
  if (fenceIndex >= 0) return value.slice(0, fenceIndex).trim();
  if (/^[{[]/.test(value.trim())) return '';
  return value.trim();
}

export function formatDateInAppTimezone(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: APP_TIMEZONE,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(date);
    const values = Object.fromEntries(
      parts.map((part) => [part.type, part.value])
    );
    return `${values.year}-${values.month}-${values.day}`;
  } catch {
    return date.toISOString().slice(0, 10);
  }
}

export function todayInAppTimezone(): string {
  return formatDateInAppTimezone(new Date());
}
