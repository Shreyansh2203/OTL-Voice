import { describe, expect, it } from 'vitest';
import {
  extractEntries,
  looksLikeTimesheetPayload,
  stripEntriesBlock,
  todayInAppTimezone,
} from './entries';

const validEntry = {
  employeeNumber: '7',
  employeeName: 'Mala Kumari',
  projectId: 'PRJ-1',
  projectNo: 'PA-1',
  projectName: 'Operations',
  workOrder: 'WO-9',
  taskId: 'TASK-1',
  taskDetails: 'Reviewed weekly payroll entries',
  hours: 2.5,
  date: '2026-09-25',
  startTime: '09:00',
  stopTime: '11:30',
  payrollTimeType: 'Regular',
  expenditureType: 'Project Expense',
  currencyCode: 'USD',
};

describe('entries utilities', () => {
  it('extracts a strict timesheet object from a fenced block', () => {
    const text = `Please review these entries.\n\n\`\`\`json\n${JSON.stringify({
      entries: [validEntry],
    })}\n\`\`\``;
    expect(extractEntries(text)).toEqual([validEntry]);
    expect(stripEntriesBlock(text)).toBe('Please review these entries.');
  });

  it('accepts raw JSON but rejects legacy arrays and extra fields', () => {
    expect(extractEntries(JSON.stringify({ entries: [validEntry] }))).toEqual([
      validEntry,
    ]);
    expect(extractEntries(JSON.stringify([validEntry]))).toBeNull();
    expect(
      extractEntries(
        JSON.stringify({ entries: [{ ...validEntry, taskName: 'legacy' }] })
      )
    ).toBeNull();
  });

  it('rejects malformed, empty, oversized, and invalid payloads', () => {
    expect(extractEntries('{"entries":[')).toBeNull();
    expect(extractEntries('{"entries":[]}')).toBeNull();
    expect(
      extractEntries(
        JSON.stringify({ entries: Array.from({ length: 101 }, () => validEntry) })
      )
    ).toBeNull();
    expect(
      extractEntries(
        JSON.stringify({
          entries: [{ ...validEntry, hours: 0.3, startTime: '09:00' }],
        })
      )
    ).toBeNull();
    expect(
      extractEntries(
        JSON.stringify({
          entries: [{ ...validEntry, date: '2026-02-30' }],
        })
      )
    ).toBeNull();
    expect(
      extractEntries(
        JSON.stringify({
          entries: [{ ...validEntry, stopTime: '08:59' }],
        })
      )
    ).toBeNull();
  });

  it('detects malformed payload cues for the manual fallback', () => {
    expect(looksLikeTimesheetPayload('{"entries":[')).toBe(true);
    expect(looksLikeTimesheetPayload('```json\n{}\n```')).toBe(true);
    expect(looksLikeTimesheetPayload('I can help with that.')).toBe(false);
  });

  it('uses the configured application timezone for today', () => {
    expect(todayInAppTimezone()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
