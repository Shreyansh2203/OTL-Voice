import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LoginView from './LoginView';
import * as api from '../../api/client';

vi.mock('../../api/client', () => ({ login: vi.fn() }));

describe('LoginView', () => {
  beforeEach(() => {
    vi.mocked(api.login).mockReset();
  });

  it('renders a local, asset-free login experience', () => {
    const { container } = render(<LoginView onLogin={vi.fn()} />);

    expect(
      screen.getByRole('heading', { name: 'Welcome back' })
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Person number')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(container.querySelectorAll('img')).toHaveLength(0);
    expect(container.innerHTML).not.toMatch(/https?:\/\//i);
  });

  it('submits the visible employee credentials', async () => {
    const onLogin = vi.fn();
    const identity = {
      username: '7',
      fullName: 'Mala Kumari',
      employeeId: '7',
    };
    vi.mocked(api.login).mockResolvedValue(identity);
    render(<LoginView onLogin={onLogin} />);

    fireEvent.change(screen.getByLabelText('Person number'), {
      target: { value: '7' },
    });
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'secret' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Sign in/i }));

    expect(api.login).toHaveBeenCalledWith('7', 'secret');
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(identity));
  });

  it('shows authentication errors without completing login', async () => {
    const onLogin = vi.fn();
    vi.mocked(api.login).mockRejectedValue(new Error('Invalid credentials'));
    render(<LoginView onLogin={onLogin} />);

    fireEvent.change(screen.getByLabelText('Person number'), {
      target: { value: '7' },
    });
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'wrong' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Sign in/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Invalid credentials'
    );
    expect(onLogin).not.toHaveBeenCalled();
  });

  it('does not expose unexpected error details', async () => {
    vi.mocked(api.login).mockRejectedValue('internal detail');
    render(<LoginView onLogin={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Person number'), {
      target: { value: '7' },
    });
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'secret' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Sign in/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-in failed.');
  });
});
