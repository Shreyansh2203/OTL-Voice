import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MicIcon, SendIcon, SpeakerIcon, StopIcon } from './icons';
describe('icons', () => {
  it('renders MicIcon', () => {
    const { container } = render(<MicIcon />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });
  it('renders SendIcon', () => {
    const { container } = render(<SendIcon />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });
  it('renders SpeakerIcon', () => {
    const { container } = render(<SpeakerIcon />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });
  it('renders StopIcon', () => {
    const { container } = render(<StopIcon />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });
});