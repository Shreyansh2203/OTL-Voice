import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { motion } from 'motion/react';
import * as api from '../../api/client';
import {
  HOUR_INCREMENT,
  MAX_DAILY_HOURS,
  MAX_ENTRY_HOURS,
  todayInAppTimezone,
} from '../../lib/entries';
import type { SubmitResponse, TimecardEntry } from '../../types';

export interface ReviewPanelProps {
  entries: TimecardEntry[];
  onSessionExpired: () => void;
  title?: string;
  description?: string;
  manual?: boolean;
}

type EntryField = keyof TimecardEntry;
type FieldErrors = Record<string, string>;

function createRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = Math.floor(Math.random() * 16);
    const value = char === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

function newEntry(): TimecardEntry {
  return {
    requestId: createRequestId(),
    date: todayInAppTimezone(),
    currencyCode: 'USD',
  };
}

function normalizeEntry(entry: TimecardEntry): TimecardEntry {
  const optional = (value: unknown) => {
    const text = typeof value === 'string' ? value.trim() : '';
    return text || undefined;
  };
  return {
    requestId: entry.requestId || createRequestId(),
    employeeNumber: optional(entry.employeeNumber),
    employeeName: optional(entry.employeeName),
    projectId: optional(entry.projectId),
    projectNo:
      typeof entry.projectNo === 'number'
        ? entry.projectNo
        : optional(entry.projectNo),
    projectName: optional(entry.projectName),
    workOrder: optional(entry.workOrder),
    taskId:
      typeof entry.taskId === 'number' ? entry.taskId : optional(entry.taskId),
    taskDetails: optional(entry.taskDetails),
    hours: typeof entry.hours === 'number' ? entry.hours : Number.NaN,
    date: optional(entry.date),
    startTime: optional(entry.startTime),
    stopTime: optional(entry.stopTime),
    payrollTimeType: optional(entry.payrollTimeType),
    expenditureType: optional(entry.expenditureType),
    currencyCode: optional(entry.currencyCode)?.toUpperCase(),
  };
}

function isValidDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

function isValidTime(value: string): boolean {
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  if (!match) return false;
  return Number(match[1]) <= 23 && Number(match[2]) <= 59;
}

function validateEntry(entry: TimecardEntry, index: number): FieldErrors {
  const errors: FieldErrors = {};
  const required: Array<[EntryField, string]> = [
    ['employeeNumber', 'Employee number is required.'],
    ['employeeName', 'Employee name is required.'],
    ['projectNo', 'Project number is required.'],
    ['projectName', 'Project name is required.'],
    ['workOrder', 'Work order is required.'],
    ['taskDetails', 'Task details are required.'],
    ['date', 'Date is required.'],
    ['currencyCode', 'Currency is required.'],
  ];
  required.forEach(([field, message]) => {
    const value = entry[field];
    if (value === undefined || value === null || String(value).trim() === '') {
      errors[`${index}-${field}`] = message;
    }
  });
  if (entry.taskDetails && entry.taskDetails.trim().length > 80) {
    errors[`${index}-taskDetails`] =
      'Task details must be 80 characters or fewer.';
  }
  if (entry.date && !isValidDate(entry.date)) {
    errors[`${index}-date`] = 'Enter a real date in YYYY-MM-DD format.';
  }
  (['startTime', 'stopTime'] as const).forEach((field) => {
    if (entry[field] && !isValidTime(entry[field] as string)) {
      errors[`${index}-${field}`] = 'Enter a valid 24-hour time in HH:MM format.';
    }
  });
  if (entry.stopTime && !entry.startTime) {
    errors[`${index}-stopTime`] = 'Stop time requires a start time.';
  }
  if (
    entry.startTime &&
    entry.stopTime &&
    isValidTime(entry.startTime) &&
    isValidTime(entry.stopTime) &&
    typeof entry.hours === 'number' &&
    Number.isFinite(entry.hours)
  ) {
    const [startHour, startMinute] = entry.startTime.split(':').map(Number);
    const [stopHour, stopMinute] = entry.stopTime.split(':').map(Number);
    const startTotal = startHour * 60 + startMinute;
    const stopTotal = stopHour * 60 + stopMinute;
    if (stopTotal <= startTotal) {
      errors[`${index}-stopTime`] =
        'Stop time must be later than start time on the same day.';
    } else if (stopTotal - startTotal !== entry.hours * 60) {
      errors[`${index}-stopTime`] =
        'Stop time must exactly match start time plus the entered hours.';
    }
  }
  if (
    entry.hours === undefined ||
    !Number.isFinite(entry.hours) ||
    entry.hours <= 0
  ) {
    errors[`${index}-hours`] = 'Hours must be a number greater than zero.';
  } else if (entry.hours > MAX_ENTRY_HOURS) {
    errors[`${index}-hours`] =
      `Hours cannot exceed ${MAX_ENTRY_HOURS} for one entry.`;
  } else if (
    Math.round(entry.hours / HOUR_INCREMENT) * HOUR_INCREMENT !== entry.hours
  ) {
    errors[`${index}-hours`] =
      'Hours must use quarter, half, or whole-hour increments.';
  }
  if (
    entry.currencyCode &&
    !/^[A-Z]{3}$/.test(entry.currencyCode.trim().toUpperCase())
  ) {
    errors[`${index}-currencyCode`] = 'Currency must be a three-letter code.';
  }
  if (!entry.requestId) {
    errors[`${index}-requestId`] = 'A request key is required.';
  }
  return errors;
}

interface EditableFieldProps {
  id: string;
  label: string;
  error?: string;
  className?: string;
  children: ReactNode;
}

function EditableField({ id, label, error, className = '', children }: EditableFieldProps) {
  return (
    <div className={`review-field ${className}`.trim()}>
      <label htmlFor={id}>{label}</label>
      {children}
      {error && (
        <span className="field-error" id={`${id}-error`} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export default function ReviewPanel(props: ReviewPanelProps) {
  return (
    <ReviewPanelContent
      key={`${props.manual ? 'manual' : 'model'}:${JSON.stringify(props.entries)}`}
      {...props}
    />
  );
}

function ReviewPanelContent({
  entries,
  onSessionExpired,
  title = 'Review Timesheet',
  description = 'Check every field before approving. The server performs final validation.',
}: ReviewPanelProps) {
  const [draftEntries, setDraftEntries] = useState<TimecardEntry[]>(() =>
    entries.map((entry) => ({
      ...newEntry(),
      ...entry,
      requestId: entry.requestId || createRequestId(),
    }))
  );
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SubmitResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const rotatedAfterErrorRef = useRef(new Set<string>());
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const activeEntries = useMemo(
    () => draftEntries.map(normalizeEntry),
    [draftEntries]
  );
  const totalHours = activeEntries.reduce(
    (sum, entry) => sum + (Number.isFinite(entry.hours) ? (entry.hours ?? 0) : 0),
    0
  );
  const locked = result !== null;

  const updateEntry = (index: number, field: EntryField, value: string) => {
    setError(null);
    setDraftEntries((current) =>
      current.map((entry, entryIndex) => {
        if (entryIndex !== index) return entry;
        const next = {
          ...entry,
          [field]:
            field === 'hours'
              ? value.trim() === ''
                ? Number.NaN
                : Number(value)
              : value,
        } as TimecardEntry;
        if (
          error &&
          entry.requestId &&
          !rotatedAfterErrorRef.current.has(entry.requestId)
        ) {
          next.requestId = createRequestId();
          rotatedAfterErrorRef.current.add(entry.requestId);
        }
        return next;
      })
    );
    setErrors((current) => {
      const key = `${index}-${field}`;
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  const addEntry = () => {
    setResult(null);
    setError(null);
    setErrors({});
    setDraftEntries((current) => [...current, newEntry()]);
  };

  const removeEntry = (index: number) => {
    setResult(null);
    setError(null);
    setErrors({});
    setDraftEntries((current) =>
      current.length === 1 ? [newEntry()] : current.filter((_, i) => i !== index)
    );
  };

  const submit = useCallback(async () => {
    if (locked || busy) return;
    const nextErrors = activeEntries.reduce<FieldErrors>(
      (all, entry, index) => ({ ...all, ...validateEntry(entry, index) }),
      {}
    );
    const hoursByDate = new Map<string, number>();
    activeEntries.forEach((entry, index) => {
      if (!entry.date || !Number.isFinite(entry.hours)) return;
      const nextTotal = (hoursByDate.get(entry.date) || 0) + (entry.hours ?? 0);
      hoursByDate.set(entry.date, nextTotal);
      if (nextTotal > MAX_DAILY_HOURS) {
        nextErrors[`${index}-hours`] =
          `Combined hours for ${entry.date} cannot exceed ${MAX_DAILY_HOURS}.`;
      }
    });
    setErrors(nextErrors);
    const firstError = Object.keys(nextErrors)[0];
    if (firstError) {
      const [index, field] = firstError.split('-');
      document.getElementById(`${Number(index) + 1}-${field}`)?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    setSubmitAttempted(true);
    try {
      const response = await api.submitTimecard(activeEntries);
      if (mountedRef.current) setResult(response);
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof api.ApiError && err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(
        err instanceof Error
          ? err.message
          : 'The server did not confirm submission. Retry safely.'
      );
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  }, [activeEntries, busy, locked, onSessionExpired]);

  const retryFailed = useCallback(async () => {
    if (!result || result.failed === 0 || busy) return;
    const failedIndices = result.results
      .filter((row) => !row.ok)
      .map((row) => row.index);
    setBusy(true);
    setError(null);
    try {
      const retry = await api.submitTimecard(
        failedIndices.map((index) => activeEntries[index])
      );
      if (!mountedRef.current) return;
      const replacements = new Map(
        retry.results.map((row) => {
          const targetIndex = failedIndices[row.index];
          return [
            targetIndex,
            targetIndex === undefined ? row : { ...row, index: targetIndex },
          ];
        })
      );
      setResult((current) => {
        if (!current) return current;
        const merged = current.results.map(
          (row) => replacements.get(row.index) || row
        );
        return {
          ...current,
          submitted: current.submitted + retry.submitted,
          succeeded: merged.filter((row) => row.ok).length,
          failed: merged.filter((row) => !row.ok).length,
          results: merged,
        };
      });
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof api.ApiError && err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(
        err instanceof Error ? err.message : 'The retry was not confirmed.'
      );
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  }, [activeEntries, busy, onSessionExpired, result]);

  const errorItems = Object.entries(errors);
  const confirmed =
    !!result && result.results.length > 0 && result.failed === 0;
  const badge = result
    ? confirmed
      ? 'Server Confirmed'
      : 'Not Fully Confirmed'
    : 'Awaiting Approval';
  const heading = result
    ? confirmed
      ? 'Submission Confirmed'
      : 'Submission Not Completed'
    : title;

  return (
    <section className="approval-card" aria-busy={busy} aria-label={title}>
      <div className="approval-head">
        <div className="approval-title">
          <span
            className={`approval-badge ${result ? (confirmed ? 'confirmed' : 'failed') : ''}`}
          >
            {badge}
          </span>
          <h3>{heading}</h3>
        </div>
        <span className="approval-meta">
          {activeEntries.length} {activeEntries.length === 1 ? 'entry' : 'entries'} ·{' '}
          {totalHours}h total
        </span>
        <p className="approval-description">{description}</p>
      </div>

      {errorItems.length > 0 && (
        <div className="validation-summary" role="alert" tabIndex={-1}>
          <strong>Correct {errorItems.length === 1 ? 'this field' : 'these fields'} before submitting:</strong>
          <ul>
            {errorItems.map(([key, message]) => {
              const [index, field] = key.split('-');
              const entryNumber = Number(index) + 1;
              return (
                <li key={key}>
                  <a href={`#${entryNumber}-${field}`}>
                    Entry {entryNumber}: {message}
                  </a>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="review-entry-list">
        {activeEntries.map((entry, index) => {
          const entryNumber = index + 1;
          const field = (name: EntryField) => `${entryNumber}-${name}`;
          const fieldProps = (name: EntryField) => ({
            id: field(name),
            error: errors[field(name)],
          });
          return (
            <fieldset className="review-entry" key={entry.requestId}>
              <legend>Entry {entryNumber}</legend>
              <div className="review-field-grid">
                <EditableField label="Employee name" {...fieldProps('employeeName')}>
                  <input
                    id={field('employeeName')}
                    value={entry.employeeName ?? ''}
                    onChange={(event) => updateEntry(index, 'employeeName', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('employeeName')]}
                    aria-describedby={errors[field('employeeName')] ? `${field('employeeName')}-error` : undefined}
                    autoComplete="name"
                  />
                </EditableField>
                <EditableField label="Employee number" {...fieldProps('employeeNumber')}>
                  <input
                    id={field('employeeNumber')}
                    value={entry.employeeNumber ?? ''}
                    onChange={(event) => updateEntry(index, 'employeeNumber', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('employeeNumber')]}
                    aria-describedby={errors[field('employeeNumber')] ? `${field('employeeNumber')}-error` : undefined}
                  />
                </EditableField>
                <EditableField label="Project number" {...fieldProps('projectNo')}>
                  <input
                    id={field('projectNo')}
                    value={entry.projectNo ?? ''}
                    onChange={(event) => updateEntry(index, 'projectNo', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('projectNo')]}
                    aria-describedby={errors[field('projectNo')] ? `${field('projectNo')}-error` : undefined}
                  />
                </EditableField>
                <EditableField label="Project name" {...fieldProps('projectName')}>
                  <input
                    id={field('projectName')}
                    value={entry.projectName ?? ''}
                    onChange={(event) => updateEntry(index, 'projectName', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('projectName')]}
                    aria-describedby={errors[field('projectName')] ? `${field('projectName')}-error` : undefined}
                  />
                </EditableField>
                <EditableField label="Work order" {...fieldProps('workOrder')}>
                  <input
                    id={field('workOrder')}
                    value={entry.workOrder ?? ''}
                    onChange={(event) => updateEntry(index, 'workOrder', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('workOrder')]}
                    aria-describedby={errors[field('workOrder')] ? `${field('workOrder')}-error` : undefined}
                  />
                </EditableField>
                <EditableField label="Project ID (optional)" {...fieldProps('projectId')}>
                  <input
                    id={field('projectId')}
                    value={entry.projectId ?? ''}
                    onChange={(event) => updateEntry(index, 'projectId', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('projectId')]}
                    aria-describedby={errors[field('projectId')] ? `${field('projectId')}-error` : undefined}
                  />
                </EditableField>
                <EditableField label="Task ID (optional)" {...fieldProps('taskId')}>
                  <input
                    id={field('taskId')}
                    value={entry.taskId ?? ''}
                    onChange={(event) => updateEntry(index, 'taskId', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('taskId')]}
                    aria-describedby={errors[field('taskId')] ? `${field('taskId')}-error` : undefined}
                  />
                </EditableField>
                <EditableField label="Date" {...fieldProps('date')}>
                  <input
                    id={field('date')}
                    type="date"
                    value={entry.date ?? ''}
                    onChange={(event) => updateEntry(index, 'date', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('date')]}
                    aria-describedby={errors[field('date')] ? `${field('date')}-error` : undefined}
                  />
                </EditableField>
                <EditableField label="Start time (optional)" {...fieldProps('startTime')}>
                  <input
                    id={field('startTime')}
                    type="time"
                    value={entry.startTime ?? ''}
                    onChange={(event) => updateEntry(index, 'startTime', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('startTime')]}
                    aria-describedby={errors[field('startTime')] ? `${field('startTime')}-error` : undefined}
                  />
                </EditableField>
                <EditableField label="Stop time (optional)" {...fieldProps('stopTime')}>
                  <input
                    id={field('stopTime')}
                    type="time"
                    value={entry.stopTime ?? ''}
                    onChange={(event) => updateEntry(index, 'stopTime', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('stopTime')]}
                    aria-describedby={errors[field('stopTime')] ? `${field('stopTime')}-error` : undefined}
                  />
                </EditableField>
                <EditableField label="Hours" {...fieldProps('hours')}>
                  <div className="hour-stepper">
                    <button
                      type="button"
                      className="hour-stepper-btn"
                      onClick={() =>
                        updateEntry(
                          index,
                          'hours',
                          String(
                            Math.min(
                              MAX_ENTRY_HOURS,
                              Math.max(
                                HOUR_INCREMENT,
                                (entry.hours || 0) - HOUR_INCREMENT
                              )
                            )
                          )
                        )
                      }
                      disabled={locked || busy}
                      aria-label={`Decrease hours for entry ${entryNumber}`}
                    >
                      −
                    </button>
                    <input
                      id={field('hours')}
                      type="number"
                      min={HOUR_INCREMENT}
                      max={MAX_ENTRY_HOURS}
                      step={HOUR_INCREMENT}
                      inputMode="decimal"
                      value={Number.isFinite(entry.hours) ? entry.hours : ''}
                      onChange={(event) => updateEntry(index, 'hours', event.target.value)}
                      disabled={locked || busy}
                      aria-invalid={!!errors[field('hours')]}
                      aria-describedby={errors[field('hours')] ? `${field('hours')}-error` : undefined}
                    />
                    <button
                      type="button"
                      className="hour-stepper-btn"
                      onClick={() =>
                        updateEntry(
                          index,
                          'hours',
                          String(
                            Math.min(
                              MAX_ENTRY_HOURS,
                              (entry.hours || 0) + HOUR_INCREMENT
                            )
                          )
                        )
                      }
                      disabled={locked || busy}
                      aria-label={`Increase hours for entry ${entryNumber}`}
                    >
                      +
                    </button>
                  </div>
                </EditableField>
                <EditableField label="Payroll time type" {...fieldProps('payrollTimeType')}>
                  <input
                    id={field('payrollTimeType')}
                    value={entry.payrollTimeType ?? ''}
                    onChange={(event) => updateEntry(index, 'payrollTimeType', event.target.value)}
                    disabled={locked || busy}
                    list={`${entryNumber}-payroll-options`}
                  />
                  <datalist id={`${entryNumber}-payroll-options`}>
                    <option value="Regular" />
                    <option value="Overtime" />
                    <option value="Extended Day Overtime" />
                    <option value="Shift Differential" />
                    <option value="Holiday" />
                    <option value="Sick" />
                    <option value="Vacation" />
                    <option value="Unpaid Leave" />
                  </datalist>
                </EditableField>
                <EditableField label="Expenditure type" {...fieldProps('expenditureType')}>
                  <input
                    id={field('expenditureType')}
                    value={entry.expenditureType ?? ''}
                    onChange={(event) => updateEntry(index, 'expenditureType', event.target.value)}
                    disabled={locked || busy}
                    list={`${entryNumber}-expenditure-options`}
                  />
                  <datalist id={`${entryNumber}-expenditure-options`}>
                    <option value="Professional Services" />
                    <option value="Regular Time" />
                    <option value="Dev" />
                  </datalist>
                </EditableField>
                <EditableField label="Currency code" {...fieldProps('currencyCode')}>
                  <input
                    id={field('currencyCode')}
                    value={entry.currencyCode ?? ''}
                    onChange={(event) => updateEntry(index, 'currencyCode', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('currencyCode')]}
                    aria-describedby={errors[field('currencyCode')] ? `${field('currencyCode')}-error` : undefined}
                    maxLength={3}
                  />
                </EditableField>
                <EditableField className="review-field-wide" label="Task details" {...fieldProps('taskDetails')}>
                  <textarea
                    id={field('taskDetails')}
                    value={entry.taskDetails ?? ''}
                    onChange={(event) => updateEntry(index, 'taskDetails', event.target.value)}
                    disabled={locked || busy}
                    aria-invalid={!!errors[field('taskDetails')]}
                    aria-describedby={errors[field('taskDetails')] ? `${field('taskDetails')}-error` : undefined}
                    maxLength={80}
                    rows={2}
                  />
                </EditableField>
              </div>
              {activeEntries.length > 1 && (
                <button
                  type="button"
                  className="btn btn-secondary review-remove-entry"
                  onClick={() => removeEntry(index)}
                  disabled={busy}
                >
                  Remove entry {entryNumber}
                </button>
              )}
            </fieldset>
          );
        })}
      </div>

      {error && (
        <div className="error" role="alert">
          {error}
          {submitAttempted && !result && (
            <span className="small"> No submission is being reported as successful. Retrying unchanged entries reuses the same request key.</span>
          )}
        </div>
      )}

      {result ? (
        <>
          <div className={`result ${result.failed ? 'warn' : 'ok'}`} aria-live="polite">
            <strong>
              Server confirmed {result.succeeded} of {result.results.length}{' '}
              timecards
              {result.failed ? ` · ${result.failed} not completed` : ''}.
            </strong>
            {result.failed > 0 && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={retryFailed}
                disabled={busy}
              >
                {busy ? 'Retrying…' : 'Retry failed entries'}
              </button>
            )}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Entry</th>
                  <th>Project</th>
                  <th>Date</th>
                  <th className="num">Hours</th>
                  <th>Server status</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((row) => {
                  const entry = activeEntries[row.index];
                  return (
                    <tr key={`${row.index}-${entry?.requestId}`}>
                      <td className="muted">{row.index + 1}</td>
                      <td>
                        {entry?.projectName || '—'}
                        {entry?.projectNo != null && (
                          <span className="muted small"> ({entry.projectNo})</span>
                        )}
                      </td>
                      <td>{entry?.date || '—'}</td>
                      <td className="num">{entry?.hours ?? '—'}</td>
                      <td>
                        {row.ok ? (
                          <span className="status-ok">
                            ✓ {row.recordNumber || 'Created'}
                          </span>
                        ) : (
                          <span className="status-fail">
                            ✗ {row.error || 'Failed'}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="approval-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={addEntry}
            disabled={busy}
          >
            Add entry
          </button>
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="btn-approve"
            onClick={() => void submit()}
            disabled={busy}
          >
            {busy
              ? 'Submitting…'
              : submitAttempted
                ? 'Retry submission safely'
                : 'Approve & Submit'}
          </motion.button>
        </div>
      )}
    </section>
  );
}
