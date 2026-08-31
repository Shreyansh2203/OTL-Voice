import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ToolChip from './ToolChip';
describe('ToolChip', () => {
  it('renders running state', () => {
    const { container } = render(
      <ToolChip tool={{ id: '1', name: 'myTool', status: 'running' }} />
    );
    expect(screen.getByText('myTool')).toBeDefined();
    expect(container.querySelector('.running')).toBeDefined();
    expect(container.querySelector('circle')).toBeDefined();
  });
  it('renders completed state', () => {
    const { container } = render(
      <ToolChip tool={{ id: '2', name: 'myTool', status: 'completed' }} />
    );
    expect(container.querySelector('.completed')).toBeDefined();
    expect(container.querySelector('polyline')).toBeDefined();
  });
  it('renders failed state', () => {
    const { container } = render(
      <ToolChip tool={{ id: '3', name: 'myTool', status: 'failed' }} />
    );
    expect(container.querySelector('.failed')).toBeDefined();
    expect(container.querySelector('line')).toBeDefined();
  });
});
