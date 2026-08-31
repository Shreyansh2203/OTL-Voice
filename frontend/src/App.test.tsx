import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from './App';
import * as api from './api/client';
vi.mock('./api/client', () => ({
  getSession: vi.fn(),
  logout: vi.fn(),
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
describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
  it('shows LoginView on session error', async () => {
    vi.mocked(api.getSession).mockRejectedValue(new Error('fail'));
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('login-view')).toBeInTheDocument();
    });
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
  it('handles logout error gracefully', async () => {
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
      expect(screen.getByTestId('login-view')).toBeInTheDocument();
    });
  });
  it('handles session expired callback', async () => {
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
  });
});
