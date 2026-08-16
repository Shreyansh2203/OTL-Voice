import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ThinkingState from './ThinkingState';

describe('ThinkingState', () => {
  it('renders without reasoning', () => {
    const { container } = render(<ThinkingState />);
    expect(screen.getByText('Thinking...')).toBeDefined();
    // Default cursor is expected when no reasoning
    const loader = container.querySelector('.thinking-loader') as HTMLElement;
    expect(loader.style.cursor).toBe('default');
  });

  it('renders with reasoning and expands on click', () => {
    const { container } = render(<ThinkingState reasoning="some reasoning" />);
    const loader = container.querySelector('.thinking-loader') as HTMLElement;
    expect(loader.style.cursor).toBe('pointer');
    
    // Initially not expanded
    expect(screen.queryByText('some reasoning')).toBeNull();
    
    // Click to expand
    fireEvent.click(loader);
    expect(screen.getByText('some reasoning')).toBeDefined();
    
    // Click to collapse
    fireEvent.click(loader);
    expect(screen.queryByText('some reasoning')).toBeNull();
  });
});
