import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import {
  MicIcon,
  SendIcon,
  SpeakerIcon,
  StopIcon,
  MessageSquareIcon,
  FolderIcon,
  HistoryIcon,
  SparklesIcon,
  CheckIcon,
  ChevronDownIcon,
  SearchIcon,
  BoltIcon,
} from './icons';
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
  it('renders navigation and action icons', () => {
    const { container: c1 } = render(<MessageSquareIcon />);
    expect(c1.querySelector('svg')).toBeInTheDocument();
    const { container: c2 } = render(<FolderIcon />);
    expect(c2.querySelector('svg')).toBeInTheDocument();
    const { container: c3 } = render(<HistoryIcon />);
    expect(c3.querySelector('svg')).toBeInTheDocument();
    const { container: c4 } = render(<SparklesIcon />);
    expect(c4.querySelector('svg')).toBeInTheDocument();
    const { container: c5 } = render(<CheckIcon />);
    expect(c5.querySelector('svg')).toBeInTheDocument();
    const { container: c6 } = render(<ChevronDownIcon />);
    expect(c6.querySelector('svg')).toBeInTheDocument();
    const { container: c7 } = render(<SearchIcon />);
    expect(c7.querySelector('svg')).toBeInTheDocument();
    const { container: c8 } = render(<BoltIcon />);
    expect(c8.querySelector('svg')).toBeInTheDocument();
  });
});
