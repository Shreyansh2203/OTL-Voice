import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ReviewPanel from './ReviewPanel';
import * as api from '../api/client';
import { ApiError } from '../api/client';
describe('ReviewPanel', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });
  const mockEntries = [
    {
      employeeName: 'John',
      employeeNumber: '123',
      projectName: 'Proj A',
      projectNo: 'PA-1',
      workOrder: 'WO-1',
      taskDetails: 'Task 1',
      hours: '5'
    },
    {
      projectName: '',
      projectNo: undefined,
      workOrder: '',
      taskDetails: '',
      hours: undefined
    }
  ];
  it('renders entries and total hours', () => {
    const onSessionExpired = vi.fn();
    render(<ReviewPanel entries={mockEntries as any} onSessionExpired={onSessionExpired} />);
    expect(screen.getByText('2 entries • 5h total')).toBeDefined();
    expect(screen.getByText('Proj A')).toBeDefined();
  });
  it('submits successfully', async () => {
    const onSessionExpired = vi.fn();
    vi.spyOn(api, 'submitTimecard').mockResolvedValue({
      submitted: 2,
      succeeded: 1,
      failed: 1,
      results: [
        { index: 0, ok: true, recordNumber: '12345' },
        { index: 1, ok: false, error: 'Bad data' }
      ]
    });
    render(<ReviewPanel entries={mockEntries as any} onSessionExpired={onSessionExpired} />);
    const approveBtn = screen.getByText('Approve & Submit');
    fireEvent.click(approveBtn);
    expect(approveBtn.textContent).toBe('Approving…');
    expect(approveBtn).toHaveProperty('disabled', true);
    await waitFor(() => {
      expect(screen.getByText('1/2 submitted to OTL · 1 failed.')).toBeDefined();
    });
    expect(screen.getByText('✓ 12345')).toBeDefined();
    expect(screen.getByText('✗ Bad data')).toBeDefined();
  });
  it('handles general errors on submit', async () => {
    const onSessionExpired = vi.fn();
    vi.spyOn(api, 'submitTimecard').mockRejectedValue(new Error('Network Error'));
    render(<ReviewPanel entries={mockEntries as any} onSessionExpired={onSessionExpired} />);
    fireEvent.click(screen.getByText('Approve & Submit'));
    await waitFor(() => {
      expect(screen.getByText('Network Error')).toBeDefined();
    });
  });
  it('handles ApiError 401 on submit', async () => {
    const onSessionExpired = vi.fn();
    vi.spyOn(api, 'submitTimecard').mockRejectedValue(new ApiError(401, 'Unauthorized'));
    render(<ReviewPanel entries={mockEntries as any} onSessionExpired={onSessionExpired} />);
    fireEvent.click(screen.getByText('Approve & Submit'));
    await waitFor(() => {
      expect(onSessionExpired).toHaveBeenCalled();
    });
  });
  it('handles empty results properly', async () => {
    const onSessionExpired = vi.fn();
    vi.spyOn(api, 'submitTimecard').mockResolvedValue({
      submitted: 2,
      succeeded: 2,
      failed: 0,
      results: [
        { index: 0, ok: true },
        { index: 1, ok: false }
      ]
    });
    render(<ReviewPanel entries={mockEntries as any} onSessionExpired={onSessionExpired} />);
    fireEvent.click(screen.getByText('Approve & Submit'));
    await waitFor(() => {
      expect(screen.getByText('2/2 submitted to OTL.')).toBeDefined();
    });
  });
  it('handles general string reject on submit', async () => {
    const onSessionExpired = vi.fn();
    vi.spyOn(api, 'submitTimecard').mockRejectedValue('String Error');
    render(<ReviewPanel entries={mockEntries as any} onSessionExpired={onSessionExpired} />);
    fireEvent.click(screen.getByText('Approve & Submit'));
    await waitFor(() => {
      expect(screen.getByText('Submission failed.')).toBeDefined();
    });
  });
});