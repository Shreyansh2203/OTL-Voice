import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ThinkingState from './ThinkingState';
describe('ThinkingState', () => {
  it('renders without reasoning', () => {
    const { container } = render(<ThinkingState />);
    expect(screen.getByText('Thinking...')).toBeDefined();
    const loader = container.querySelector('.thinking-loader') as HTMLElement;
    expect(loader.style.cursor).toBe('default');
  });
  it('renders with reasoning and expands on click', () => {
    const { container } = render(<ThinkingState reasoning="some reasoning" />);
    const loader = container.querySelector('.thinking-loader') as HTMLElement;
    expect(loader.style.cursor).toBe('pointer');
    expect(screen.queryByText('some reasoning')).toBeNull();
    fireEvent.click(loader);
    expect(screen.getByText('some reasoning')).toBeDefined();
    fireEvent.click(loader);
    expect(screen.queryByText('some reasoning')).toBeNull();
  });
});