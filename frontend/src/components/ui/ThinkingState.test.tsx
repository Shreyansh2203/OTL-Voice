import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ThinkingState from './ThinkingState';
describe('ThinkingState', () => {
  it('renders without reasoning and exposes no expander', () => {
    const { container } = render(<ThinkingState />);
    expect(screen.getByText('Thinking...')).toBeDefined();
    const loader = container.querySelector('.thinking-loader') as HTMLElement;
    expect(loader.style.cursor).toBe('default');
    expect(loader.tagName).toBe('DIV');
    expect(screen.queryByRole('button')).toBeNull();
  });
  it('renders with reasoning and expands on click', () => {
    const { container } = render(<ThinkingState reasoning="some reasoning" />);
    const loader = container.querySelector('.thinking-loader') as HTMLElement;
    expect(screen.queryByText('some reasoning')).toBeNull();
    fireEvent.click(loader);
    expect(screen.getByText('some reasoning')).toBeDefined();
    fireEvent.click(loader);
    expect(screen.queryByText('some reasoning')).toBeNull();
  });
  it('exposes the expander as a keyboard-reachable button with its state', () => {
    render(<ThinkingState reasoning="some reasoning" />);
    const toggle = screen.getByRole('button', { name: /thinking/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    const traceId = toggle.getAttribute('aria-controls');
    expect(traceId).toBeTruthy();

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const trace = document.getElementById(traceId!);
    expect(trace).toHaveTextContent('some reasoning');
  });
});
