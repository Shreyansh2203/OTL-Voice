import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ErrorBoundary from './ErrorBoundary';

function ProblemChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('Test explosion');
  }
  return <div>Everything fine</div>;
}

describe('ErrorBoundary', () => {
  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <div>Hello World</div>
      </ErrorBoundary>
    );
    expect(screen.getByText('Hello World')).toBeInTheDocument();
  });

  it('catches render error and displays default fallback', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Application Error')).toBeInTheDocument();
    expect(screen.getByText('Test explosion')).toBeInTheDocument();
    consoleError.mockRestore();
  });

  it('renders custom fallback ReactNode', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary fallback={<div>Custom Error UI</div>}>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );
    expect(screen.getByText('Custom Error UI')).toBeInTheDocument();
    consoleError.mockRestore();
  });

  it('renders custom fallback render function and handles reset', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const onReset = vi.fn();
    render(
      <ErrorBoundary
        fallback={({ error, reset }) => (
          <div>
            <span>Error: {error.message}</span>
            <button onClick={reset}>Recover</button>
          </div>
        )}
        onReset={onReset}
      >
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );
    expect(screen.getByText('Error: Test explosion')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Recover'));
    expect(onReset).toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
