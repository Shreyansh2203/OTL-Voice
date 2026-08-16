import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import TimecardHistory from './TimecardHistory';
import * as api from '../api/client';

vi.mock('../api/client', () => ({
  listTimecards: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
}));

describe('TimecardHistory', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading state initially', () => {
    vi.mocked(api.listTimecards).mockReturnValue(new Promise(() => {}));
    render(<TimecardHistory onSessionExpired={vi.fn()} />);
    expect(screen.getByText('Loading timesheets from Oracle Fusion...')).toBeInTheDocument();
  });

  it('handles successful fetch with no items', async () => {
    vi.mocked(api.listTimecards).mockResolvedValue({ items: [] });
    render(<TimecardHistory onSessionExpired={vi.fn()} />);
    
    await waitFor(() => {
      expect(screen.getByText('No recent timesheets found.')).toBeInTheDocument();
    });
  });

  it('handles successful fetch with items', async () => {
    vi.mocked(api.listTimecards).mockResolvedValue({
      items: [
        {
          timeRecordEvent: [
            {
              startTime: '2023-10-10T10:00:00Z',
              eventStatus: 'APPROVED',
              measure: 8,
              timeRecordEventAttribute: [
                { attributeName: 'Comment', attributeValue: 'Test project' }
              ]
            }
          ]
        },
        {
          startTime: '2023-10-11T10:00:00Z',
          measure: 4,
          timeRecordEventAttribute: []
        },
        {
          measure: 2
        }
      ]
    });
    
    render(<TimecardHistory onSessionExpired={vi.fn()} />);
    
    await waitFor(() => {
      expect(screen.getByText('Test project')).toBeInTheDocument();
      expect(screen.getByText('APPROVED')).toBeInTheDocument();
      expect(screen.getByText('8')).toBeInTheDocument();
      expect(screen.getAllByText('N/A').length).toBeGreaterThan(0); // from second/third items
      expect(screen.getByText('Unknown Date')).toBeInTheDocument(); // from third item missing startTime
    });
  });

  it('handles successful fetch with no items array', async () => {
    vi.mocked(api.listTimecards).mockResolvedValue({}); // data without items
    render(<TimecardHistory onSessionExpired={vi.fn()} />);
    
    await waitFor(() => {
      expect(screen.getByText('No recent timesheets found.')).toBeInTheDocument();
    });
  });

  it('handles API error 401', async () => {
    const onSessionExpired = vi.fn();
    vi.mocked(api.listTimecards).mockRejectedValue(new api.ApiError(401, 'Unauthorized'));
    
    render(<TimecardHistory onSessionExpired={onSessionExpired} />);
    
    await waitFor(() => {
      expect(onSessionExpired).toHaveBeenCalled();
    });
  });

  it('handles general API error', async () => {
    vi.mocked(api.listTimecards).mockRejectedValue(new Error('Network error'));
    
    render(<TimecardHistory onSessionExpired={vi.fn()} />);
    
    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('handles string API error', async () => {
    vi.mocked(api.listTimecards).mockRejectedValue('String error');
    
    render(<TimecardHistory onSessionExpired={vi.fn()} />);
    
    await waitFor(() => {
      expect(screen.getByText('Failed to load timesheets')).toBeInTheDocument();
    });
  });

  it('aborts state update if component unmounts before resolve', async () => {
    let resolvePromise: any;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });
    vi.mocked(api.listTimecards).mockReturnValue(promise as any);
    
    const { unmount } = render(<TimecardHistory onSessionExpired={vi.fn()} />);
    
    unmount();
    resolvePromise({ items: [] });
    // If it didn't return early on !active, React would complain about updating unmounted component
  });
  
  it('aborts state update if component unmounts before reject', async () => {
    let rejectPromise: any;
    const promise = new Promise((_, reject) => {
      rejectPromise = reject;
    });
    vi.mocked(api.listTimecards).mockReturnValue(promise as any);
    
    const { unmount } = render(<TimecardHistory onSessionExpired={vi.fn()} />);
    
    unmount();
    rejectPromise(new Error('fail'));
    // If it didn't return early on !active, React would complain about updating unmounted component
  });
});
