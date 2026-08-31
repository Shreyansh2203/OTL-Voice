import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import MessageBubble from './MessageBubble';
import type { ChatMessage } from '../../types';
describe('MessageBubble', () => {
  it('renders user message correctly', () => {
    const message: ChatMessage = { role: 'user', content: 'Hello there' };
    render(<MessageBubble message={message} />);
    expect(screen.getByText('Hello there')).toBeInTheDocument();
  });
  it('renders assistant message and markdown correctly', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: '**Bold text**',
    };
    render(<MessageBubble message={message} />);
    const strongElement = screen.getByText('Bold text');
    expect(strongElement.tagName).toBe('STRONG');
  });
  it('renders assistant message with links correctly', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: '[Google](https://google.com)',
    };
    render(<MessageBubble message={message} />);
    const linkElement = screen.getByText('Google');
    expect(linkElement.tagName).toBe('A');
    expect(linkElement).toHaveAttribute('target', '_blank');
  });
  it('renders tool calls', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: 'I will run a tool',
      toolCalls: [{ name: 'myTool', state: 'running' }],
    };
    render(<MessageBubble message={message} />);
    expect(screen.getByText('myTool')).toBeInTheDocument();
  });
  it('renders thinking state', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: '',
      thinking: true,
      reasoning: 'I am thinking',
    };
    render(<MessageBubble message={message} />);
    expect(screen.getByText('Thinking...')).toBeInTheDocument();
  });
  it('renders streaming state with caret', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: 'In progress',
      streaming: true,
    };
    const { container } = render(<MessageBubble message={message} />);
    expect(container.querySelector('.caret')).toBeInTheDocument();
  });
  it('renders streaming state without content', () => {
    const message: ChatMessage = {
      role: 'assistant',
      content: '',
      streaming: true,
    };
    render(<MessageBubble message={message} />);
    expect(screen.getByText('…')).toBeInTheDocument();
  });
});
