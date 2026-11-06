import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ReviewPanel from './ReviewPanel';
import * as api from '../../api/client';
import type { SubmitResultRow, TimecardEntry } from '../../types';

vi.mock('../../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/client')>();
  return { ...original, submitTimecard: vi.fn() };
});

function makeEntry(overrides: Partial<TimecardEntry> = {}): TimecardEntry {
  return {
    requestId: 'request-1',
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
    expenditureType: 'Regular Time',
    currencyCode: 'USD',
    ...overrides,
  };
}

function resultRow(
  index: number,
  ok: boolean,
  error?: string,
  extra: Partial<SubmitResultRow> = {}
): SubmitResultRow {
  return {
    index,
    ok,
    ...(ok
      ? { id: 9000 + index, recordNumber: `REC-${index + 1}` }
      : { error }),
    ...extra,
  };
}

describe('ReviewPanel', () => {
  beforeEach(() => {
    vi.mocked(api.submitTimecard).mockReset();
  });

  it('renders every editable response field and the daily total', () => {
    render(
      <ReviewPanel entries={[makeEntry()]} manual onSessionExpired={vi.fn()} />
    );

    expect(screen.getByText('Review Timesheet')).toBeInTheDocument();
    expect(screen.getByText(/1 entry · 2\.5h total/)).toBeInTheDocument();
    [
      'Employee name',
      'Employee number',
      'Project ID (optional)',
      'Project number',
      'Project name',
      'Work order',
      'Task ID (optional)',
      'Task details',
      'Hours',
      'Date',
      'Start time (optional)',
      'Stop time (optional)',
      'Payroll time type',
      'Expenditure type',
      'Currency code',
    ].forEach((label) =>
      expect(screen.getByLabelText(label)).toBeInTheDocument()
    );
    expect(screen.getByLabelText('Hours')).toHaveAttribute('max', '24');
    expect(screen.getByLabelText('Hours')).toHaveAttribute('step', '0.25');
  });

  it('submits all edited fields and supports quarter-hour values', async () => {
    const entry = makeEntry();
    vi.mocked(api.submitTimecard).mockResolvedValue({
      results: [resultRow(0, true)],
      submitted: 1,
      succeeded: 1,
      failed: 0,
    });
    render(<ReviewPanel entries={[entry]} manual onSessionExpired={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Employee name'), {
      target: { value: 'Updated Employee' },
    });
    fireEvent.change(screen.getByLabelText('Project number'), {
      target: { value: 'PA-42' },
    });
    fireEvent.change(screen.getByLabelText('Work order'), {
      target: { value: 'WO-42' },
    });
    fireEvent.change(screen.getByLabelText('Task details'), {
      target: { value: 'Corrected task' },
    });
    fireEvent.change(screen.getByLabelText('Hours'), {
      target: { value: '1.25' },
    });
    fireEvent.change(screen.getByLabelText('Date'), {
      target: { value: '2026-09-26' },
    });
    fireEvent.change(screen.getByLabelText('Start time (optional)'), {
      target: { value: '13:15' },
    });
    fireEvent.change(screen.getByLabelText('Stop time (optional)'), {
      target: { value: '14:30' },
    });
    fireEvent.change(screen.getByLabelText('Payroll time type'), {
      target: { value: 'Overtime' },
    });
    fireEvent.change(screen.getByLabelText('Expenditure type'), {
      target: { value: 'Professional Services' },
    });
    fireEvent.change(screen.getByLabelText('Currency code'), {
      target: { value: 'usd' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));

    await waitFor(() => expect(api.submitTimecard).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.submitTimecard).mock.calls[0][0][0]).toMatchObject({
      employeeName: 'Updated Employee',
      projectNo: 'PA-42',
      workOrder: 'WO-42',
      taskDetails: 'Corrected task',
      hours: 1.25,
      date: '2026-09-26',
      startTime: '13:15',
      stopTime: '14:30',
      payrollTimeType: 'Overtime',
      expenditureType: 'Professional Services',
      currencyCode: 'USD',
    });
    expect(
      await screen.findByText(/server confirmed 1 of 1 timecards/i)
    ).toBeInTheDocument();
  });

  it('blocks invalid dates, hours, task text, and incoherent time ranges', () => {
    const entry = makeEntry({
      date: '2026-02-30',
      hours: 0.3,
      startTime: '10:00',
      stopTime: '11:00',
      taskDetails: 'x'.repeat(81),
    });
    render(<ReviewPanel entries={[entry]} onSessionExpired={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));

    expect(
      screen.getByRole('link', { name: /real date in YYYY-MM-DD format/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', {
        name: /quarter, half, or whole-hour increments/i,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', {
        name: /Task details must be 80 characters or fewer/i,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', {
        name: /Stop time must exactly match start time plus the entered hours/i,
      })
    ).toBeInTheDocument();
    expect(api.submitTimecard).not.toHaveBeenCalled();
  });

  it('reuses the same requestId for an unedited uncertain retry', async () => {
    const entry = makeEntry();
    vi.mocked(api.submitTimecard)
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce({
        results: [resultRow(0, true)],
        submitted: 1,
        succeeded: 1,
        failed: 0,
      });
    render(<ReviewPanel entries={[entry]} manual onSessionExpired={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));
    expect(await screen.findByText('Network error')).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Retry submission safely' })
    );

    await waitFor(() => expect(api.submitTimecard).toHaveBeenCalledTimes(2));
    const firstRequestId = vi.mocked(api.submitTimecard).mock.calls[0][0][0]
      .requestId;
    const retryRequestId = vi.mocked(api.submitTimecard).mock.calls[1][0][0]
      .requestId;
    expect(firstRequestId).toBe(entry.requestId);
    expect(retryRequestId).toBe(firstRequestId);
    expect(
      await screen.findByText(/server confirmed 1 of 1 timecards/i)
    ).toBeInTheDocument();
  });

  it('keeps the same requestId when an uncertain submission is edited', async () => {
    const entry = makeEntry();
    vi.mocked(api.submitTimecard)
      .mockRejectedValueOnce(new Error('Network error'))
      .mockImplementationOnce(async () => ({
        results: [resultRow(0, true)],
        submitted: 1,
        succeeded: 1,
        failed: 0,
      }));
    render(<ReviewPanel entries={[entry]} manual onSessionExpired={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));
    await screen.findByText('Network error');
    fireEvent.change(screen.getByLabelText('Employee name'), {
      target: { value: 'Changed after timeout' },
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Retry submission safely' })
    );

    await waitFor(() => expect(api.submitTimecard).toHaveBeenCalledTimes(2));
    const originalId = vi.mocked(api.submitTimecard).mock.calls[0][0][0]
      .requestId;
    const editedId = vi.mocked(api.submitTimecard).mock.calls[1][0][0]
      .requestId;
    // A new key is a new idempotency key with no stored record, so the server
    // would write Oracle a second time for a row that may already exist.
    expect(editedId).toBe(originalId);
  });

  it('resubmits only failed rows under new request keys after confirmation', async () => {
    const first = makeEntry({ requestId: 'request-1' });
    const second = makeEntry({
      requestId: 'request-2',
      taskId: 'TASK-2',
      taskDetails: 'Second task',
    });
    vi.mocked(api.submitTimecard)
      .mockResolvedValueOnce({
        results: [
          resultRow(0, true),
          resultRow(1, false, 'Oracle rejected this row', {
            status: 400,
            code: undefined,
          }),
        ],
        submitted: 2,
        succeeded: 1,
        failed: 1,
      })
      .mockResolvedValueOnce({
        results: [resultRow(0, true)],
        submitted: 1,
        succeeded: 1,
        failed: 0,
      });
    render(
      <ReviewPanel entries={[first, second]} onSessionExpired={vi.fn()} />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));
    expect(await screen.findByText('Not Fully Confirmed')).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Submit 1 stored result again' })
    );
    fireEvent.click(
      screen.getByRole('button', {
        name: /Issue a new request key and submit/,
      })
    );

    await waitFor(() => expect(api.submitTimecard).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.submitTimecard).mock.calls[1][0]).toHaveLength(1);
    expect(
      vi.mocked(api.submitTimecard).mock.calls[1][0][0].requestId
    ).not.toBe(second.requestId);
    expect(
      await screen.findByText(/server confirmed 2 of 2 timecards/i)
    ).toBeInTheDocument();
  });

  it('retries a retryable failure under the same request key', async () => {
    const entry = makeEntry({ requestId: 'request-1' });
    vi.mocked(api.submitTimecard)
      .mockResolvedValueOnce({
        results: [
          resultRow(0, false, 'Oracle Cloud is temporarily unavailable.', {
            status: 500,
            code: 'oracle_unavailable',
          }),
        ],
        submitted: 1,
        succeeded: 0,
        failed: 1,
      })
      .mockResolvedValueOnce({
        results: [resultRow(0, true)],
        submitted: 1,
        succeeded: 1,
        failed: 0,
      });
    render(<ReviewPanel entries={[entry]} onSessionExpired={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));
    await screen.findByText('Not Fully Confirmed');
    fireEvent.click(
      screen.getByRole('button', { name: 'Retry entry 1 with the same key' })
    );

    await waitFor(() => expect(api.submitTimecard).toHaveBeenCalledTimes(2));
    // Rotating the key here is the duplicate-timecard risk, so it must not.
    expect(vi.mocked(api.submitTimecard).mock.calls[1][0][0].requestId).toBe(
      entry.requestId
    );
    expect(
      await screen.findByText(/server confirmed 1 of 1 timecards/i)
    ).toBeInTheDocument();
  });

  it('keeps a failed row editable and removable while confirmed rows stay frozen', async () => {
    const first = makeEntry({ requestId: 'request-1' });
    const second = makeEntry({
      requestId: 'request-2',
      taskId: 'TASK-2',
      taskDetails: 'Second task',
    });
    vi.mocked(api.submitTimecard).mockResolvedValue({
      results: [
        resultRow(0, true),
        resultRow(1, false, 'Oracle rejected this row', { status: 400 }),
      ],
      submitted: 2,
      succeeded: 1,
      failed: 1,
    });
    render(
      <ReviewPanel entries={[first, second]} onSessionExpired={vi.fn()} />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));
    await screen.findByText('Not Fully Confirmed');

    const hours = screen.getAllByLabelText('Hours');
    expect(hours[0]).toBeDisabled();
    expect(hours[1]).toBeEnabled();
    expect(
      screen.queryByRole('button', { name: 'Remove entry 1' })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Remove entry 2' })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/keeps this request key’s result for 24 hours/i)
    ).toBeInTheDocument();
  });

  it('clears a lone failed entry so a bad row is never a dead end', async () => {
    vi.mocked(api.submitTimecard).mockResolvedValue({
      results: [resultRow(0, false, 'Oracle is down')],
      submitted: 1,
      succeeded: 0,
      failed: 1,
    });
    render(<ReviewPanel entries={[makeEntry()]} onSessionExpired={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));
    await screen.findByText('Not Fully Confirmed');
    expect(screen.getByLabelText('Hours')).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Clear entry 1' }));

    expect(screen.queryByText('Not Fully Confirmed')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Hours')).toHaveValue(null);
    expect(
      screen.getByRole('button', { name: 'Retry submission safely' })
    ).toBeEnabled();
  });

  it('reports a replayed server result instead of a fresh Oracle write', async () => {
    vi.mocked(api.submitTimecard).mockResolvedValue({
      results: [
        resultRow(0, false, 'Oracle rejected this row', {
          status: 400,
          replayed: true,
        }),
      ],
      submitted: 1,
      succeeded: 0,
      failed: 1,
    });
    render(<ReviewPanel entries={[makeEntry()]} onSessionExpired={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));

    await screen.findByText('Not Fully Confirmed');
    expect(
      screen.getByText(/replayed from the server’s stored result/i)
    ).toBeInTheDocument();
  });

  it('exposes the session-expired path for a 401 response', async () => {
    const onSessionExpired = vi.fn();
    vi.mocked(api.submitTimecard).mockRejectedValue(
      new api.ApiError(401, 'Session expired')
    );
    render(
      <ReviewPanel
        entries={[makeEntry()]}
        onSessionExpired={onSessionExpired}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
  });

  it('adds and removes draft entries without losing existing values', () => {
    const onSessionExpired = vi.fn();
    const { rerender } = render(
      <ReviewPanel
        entries={[makeEntry()]}
        onSessionExpired={onSessionExpired}
      />
    );
    expect(screen.getByLabelText('Hours')).toHaveValue(2.5);

    fireEvent.click(screen.getByRole('button', { name: 'Add entry' }));
    expect(screen.getByText('Entry 2')).toBeInTheDocument();
    expect(screen.getAllByLabelText('Hours')[1]).toHaveValue(null);

    fireEvent.click(screen.getByRole('button', { name: 'Remove entry 2' }));
    expect(screen.queryByText('Entry 2')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Hours')).toHaveValue(2.5);

    rerender(
      <ReviewPanel
        entries={[makeEntry({ hours: 3.75 })]}
        onSessionExpired={onSessionExpired}
      />
    );
    expect(screen.getByLabelText('Hours')).toHaveValue(3.75);
  });
});
