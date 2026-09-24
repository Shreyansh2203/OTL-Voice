import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from '@testing-library/react';
import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
} from 'vitest';
import App from './App';
import * as api from './api/client';
vi.mock('./api/client', () => ({
  getSession: vi.fn(),
  logout: vi.fn(),
  refreshSession: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));
vi.mock('./features/auth/LoginView', () => ({
  default: ({ onLogin }: { onLogin: (u: any) => void }) => (
    <div data-testid="login-view">
      <button onClick={() => onLogin({ username: 'user', fullName: 'User' })}>
        Simulate Login
      </button>
    </div>
  ),
}));
vi.mock('./features/chat/ChatView', () => ({
  default: ({ onLogout, onSessionExpired }: any) => (
    <div data-testid="chat-view">
      <button onClick={onLogout}>Simulate Logout</button>
      <button onClick={onSessionExpired}>Simulate Expire</button>
    </div>
  ),
}));
vi.mock('./components/ui/NeuralTunnel', () => ({
  default: () => <div data-testid="mock-neural-tunnel" />,
  NeuralTunnel: () => <div data-testid="mock-neural-tunnel" />,
}));
describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.refreshSession).mockResolvedValue();
  });
  afterEach(() => {
    vi.useRealTimers();
  });
  it('shows loading initially and then LoginView if no session', async () => {
    vi.mocked(api.getSession).mockResolvedValue(null);
    render(<App />);
    expect(screen.getByLabelText('Loading')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('login-view')).toBeInTheDocument();
    });
  });
  it('shows ChatView if session exists', async () => {
    vi.mocked(api.getSession).mockResolvedValue({
      username: '1',
      fullName: 'User',
      employeeId: '1',
    });
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('chat-view')).toBeInTheDocument();
    });
  });
  it('shows a retry state on a session verification error', async () => {
    vi.mocked(api.getSession).mockRejectedValue(new Error('fail'));
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Unable to verify your session'
      );
    });
    expect(screen.queryByTestId('login-view')).not.toBeInTheDocument();
  });
  it('preserves the current session on a transient refresh error', async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, 'random').mockReturnValue(0);
    vi.mocked(api.getSession).mockResolvedValue({
      username: '1',
      fullName: 'User',
      employeeId: '1',
    });
    vi.mocked(api.refreshSession).mockRejectedValue(new Error('offline'));
    render(<App />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.getByTestId('chat-view')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15 * 60 * 1000);
    });
    expect(api.refreshSession).toHaveBeenCalled();
    expect(screen.getByTestId('chat-view')).toBeInTheDocument();
  });
  it('handles login callback', async () => {
    vi.mocked(api.getSession).mockResolvedValue(null);
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('login-view')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Simulate Login'));
    await waitFor(() => {
      expect(screen.getByTestId('chat-view')).toBeInTheDocument();
    });
  });
  it('handles logout callback', async () => {
    vi.mocked(api.getSession).mockResolvedValue({
      username: '1',
      fullName: 'User',
      employeeId: '1',
    });
    vi.mocked(api.logout).mockResolvedValue();
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('chat-view')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Simulate Logout'));
    await waitFor(() => {
      expect(screen.getByTestId('login-view')).toBeInTheDocument();
    });
  });
  it('preserves the session when logout fails', async () => {
    vi.mocked(api.getSession).mockResolvedValue({
      username: '1',
      fullName: 'User',
      employeeId: '1',
    });
    vi.mocked(api.logout).mockRejectedValue(new Error('fail'));
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('chat-view')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Simulate Logout'));
    await waitFor(() => {
      expect(api.logout).toHaveBeenCalled();
    });
    expect(screen.getByTestId('chat-view')).toBeInTheDocument();
    expect(screen.queryByTestId('login-view')).not.toBeInTheDocument();
  });
  it('handles session expired callback', async () => {
    localStorage.setItem('otl_session', 'expired');
    vi.mocked(api.getSession).mockResolvedValue({
      username: '1',
      fullName: 'User',
      employeeId: '1',
    });
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('chat-view')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Simulate Expire'));
    await waitFor(() => {
      expect(screen.getByTestId('login-view')).toBeInTheDocument();
    });
    expect(localStorage.getItem('otl_session')).toBeNull();
  });
});
