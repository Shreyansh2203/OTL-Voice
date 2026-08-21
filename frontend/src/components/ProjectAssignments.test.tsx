import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import ProjectAssignments from './ProjectAssignments';
import * as api from '../api/client';
import { ApiError } from '../api/client';

vi.mock('../api/client', async (importActual) => {
  const actual = await importActual<typeof api>();
  return {
    ...actual,
    getAssignments: vi.fn(),
  };
});

const mockAssignments = {
  employeeId: '208',
  fullName: 'JESSY.BROWN',
  workOrders: [
    {
      workOrder: 'WO-101125',
      description: null,
      projects: [
        {
          projectId: '300000041112336',
          projectNo: 101125,
          projectName: 'ORA_Construction_0120',
          tasks: [
            { taskId: 1, taskDetails: 'Geo_Technical Testing' },
            { taskId: '1.1', taskDetails: 'Setting Bore holes' },
          ],
        },
      ],
    },
    {
      workOrder: 'WO-101109',
      description: null,
      projects: [
        {
          projectId: '300000040441345',
          projectNo: 101109,
          projectName: 'Project_Performance_Prev_date',
          tasks: [
            { taskId: 1, taskDetails: 'Resource' },
            { taskId: '1.1', taskDetails: 'Technician' },
          ],
        },
      ],
    },
  ],
};

describe('ProjectAssignments', () => {
  const mockOnSessionExpired = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a loading state initially', () => {
    vi.mocked(api.getAssignments).mockReturnValue(new Promise(() => {}));
    render(<ProjectAssignments onSessionExpired={mockOnSessionExpired} />);
    expect(screen.getByText(/loading your projects/i)).toBeInTheDocument();
  });

  it('renders project cards when assignments are loaded', async () => {
    vi.mocked(api.getAssignments).mockResolvedValue(mockAssignments);
    render(<ProjectAssignments onSessionExpired={mockOnSessionExpired} />);

    await waitFor(() => {
      expect(screen.getByText('My Projects')).toBeInTheDocument();
    });

    expect(screen.getByText('WO-101125')).toBeInTheDocument();
    expect(screen.getByText('ORA_Construction_0120')).toBeInTheDocument();
    expect(screen.getByText(/#101125/)).toBeInTheDocument();

    expect(screen.getByText('WO-101109')).toBeInTheDocument();
    expect(screen.getByText('Project_Performance_Prev_date')).toBeInTheDocument();
  });

  it('renders tasks within a project', async () => {
    vi.mocked(api.getAssignments).mockResolvedValue(mockAssignments);
    render(<ProjectAssignments onSessionExpired={mockOnSessionExpired} />);

    await waitFor(() => {
      expect(screen.getByText('Geo_Technical Testing')).toBeInTheDocument();
    });

    expect(screen.getByText('Setting Bore holes')).toBeInTheDocument();
    expect(screen.getByText('Resource')).toBeInTheDocument();
    expect(screen.getByText('Technician')).toBeInTheDocument();
  });

  it('shows "no projects" message when work orders are empty', async () => {
    vi.mocked(api.getAssignments).mockResolvedValue({
      employeeId: '3125',
      fullName: 'Dharmendra Kumar',
      workOrders: [],
    });
    render(<ProjectAssignments onSessionExpired={mockOnSessionExpired} />);

    await waitFor(() => {
      expect(screen.getByText(/no projects assigned/i)).toBeInTheDocument();
    });
  });

  it('shows error message on API failure', async () => {
    vi.mocked(api.getAssignments).mockRejectedValue(new ApiError(500, 'Internal Server Error'));
    render(<ProjectAssignments onSessionExpired={mockOnSessionExpired} />);

    await waitFor(() => {
      expect(screen.getByText(/error/i)).toBeInTheDocument();
    });
  });

  it('calls onSessionExpired on 401 error', async () => {
    vi.mocked(api.getAssignments).mockRejectedValue(new ApiError(401, 'Unauthorized'));
    render(<ProjectAssignments onSessionExpired={mockOnSessionExpired} />);

    await waitFor(() => {
      expect(mockOnSessionExpired).toHaveBeenCalled();
    });
  });
});
