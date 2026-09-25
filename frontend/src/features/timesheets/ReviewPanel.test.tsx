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
  error?: string
): SubmitResultRow {
  return {
    index,
    ok,
    id: ok ? `record-${index}` : undefined,
    recordName: ok ? '2026-09-25' : '',
    error,
  };
}

describe('ReviewPanel', () => {
  beforeEach(() => {
    vi.mocked(api.submitTimecard).mockReset();
  });

  it('renders every editable response field and the daily total', () => {
    render(<ReviewPanel entries={[makeEntry()]} manual onSessionExpired={vi.fn()} />);

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
    ].forEach((label) => expect(screen.getByLabelText(label)).toBeInTheDocument());
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
    fireEvent.change(screen.getByLabelText('Hours'), { target: { value: '1.25' } });
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
      screen.getByRole('link', { name: /quarter, half, or whole-hour increments/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /Task details must be 80 characters or fewer/i })
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

  it('rotates requestId after an uncertain submission is edited', async () => {
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
    expect(editedId).not.toBe(originalId);
  });

  it('retries only failed rows while preserving their request IDs', async () => {
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
          resultRow(1, false, 'Oracle rejected this row'),
        ],
        submitted: 1,
        succeeded: 1,
        failed: 1,
      })
      .mockResolvedValueOnce({
        results: [resultRow(0, true)],
        submitted: 1,
        succeeded: 1,
        failed: 0,
      });
    render(<ReviewPanel entries={[first, second]} onSessionExpired={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));
    expect(await screen.findByText('Not Fully Confirmed')).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Retry failed entries' })
    );

    await waitFor(() => expect(api.submitTimecard).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.submitTimecard).mock.calls[1][0]).toHaveLength(1);
    expect(vi.mocked(api.submitTimecard).mock.calls[1][0][0].requestId).toBe(
      second.requestId
    );
    expect(
      await screen.findByText(/server confirmed 2 of 2 timecards/i)
    ).toBeInTheDocument();
  });

  it('exposes the session-expired path for a 401 response', async () => {
    const onSessionExpired = vi.fn();
    vi.mocked(api.submitTimecard).mockRejectedValue(
      new api.ApiError(401, 'Session expired')
    );
    render(<ReviewPanel entries={[makeEntry()]} onSessionExpired={onSessionExpired} />);

    fireEvent.click(screen.getByRole('button', { name: 'Approve & Submit' }));

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
  });

  it('adds and removes draft entries without losing existing values', () => {
    const onSessionExpired = vi.fn();
    const { rerender } = render(
      <ReviewPanel entries={[makeEntry()]} onSessionExpired={onSessionExpired} />
    );
    expect(screen.getByLabelText('Hours')).toHaveValue(2.5);

    fireEvent.click(screen.getByRole('button', { name: 'Add entry' }));
    expect(screen.getByText('Entry 2')).toBeInTheDocument();
    expect(screen.getAllByLabelText('Hours')[1]).toHaveValue(null);

    fireEvent.click(screen.getByRole('button', { name: 'Remove entry 2' }));
    expect(screen.queryByText('Entry 2')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Hours')).toHaveValue(2.5);

    rerender(
      <ReviewPanel entries={[makeEntry({ hours: 3.75 })]} onSessionExpired={onSessionExpired} />
    );
    expect(screen.getByLabelText('Hours')).toHaveValue(3.75);
  });
});
