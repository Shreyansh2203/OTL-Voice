import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import LiveVoiceModal from './LiveVoiceModal';

describe('LiveVoiceModal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <LiveVoiceModal
        isOpen={false}
        liveState="idle"
        errorMsg={null}
        transcript=""
        toolCalls={[]}
        isMuted={false}
        onToggleMute={vi.fn()}
        onClose={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders correctly when open in listening state', () => {
    const onToggleMute = vi.fn();
    const onClose = vi.fn();

    render(
      <LiveVoiceModal
        isOpen={true}
        liveState="listening"
        errorMsg={null}
        transcript="Hello, how can I help?"
        toolCalls={[{ name: 'submit_timecard', response: { status: 'ok' } }]}
        isMuted={false}
        onToggleMute={onToggleMute}
        onClose={onClose}
      />
    );

    expect(screen.getByText(/GEMINI LIVE MULTIMODAL/i)).toBeInTheDocument();
    expect(screen.getByText(/Listening…/i)).toBeInTheDocument();
    expect(screen.getByText('Hello, how can I help?')).toBeInTheDocument();
    expect(screen.getByText('Logged Timecard to OTL')).toBeInTheDocument();

    const muteBtn = screen.getByRole('button', { name: /Mute microphone/i });
    fireEvent.click(muteBtn);
    expect(onToggleMute).toHaveBeenCalledTimes(1);

    const endBtn = screen.getByRole('button', {
      name: /End conversation session/i,
    });
    fireEvent.click(endBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders error message when present', () => {
    render(
      <LiveVoiceModal
        isOpen={true}
        liveState="speaking"
        errorMsg="Connection timeout."
        transcript=""
        toolCalls={[]}
        isMuted={true}
        onToggleMute={vi.fn()}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Connection timeout.');
    expect(screen.getByText('Microphone Muted')).toBeInTheDocument();
  });

  it('closes modal on Escape key press', () => {
    const onClose = vi.fn();
    render(
      <LiveVoiceModal
        isOpen={true}
        liveState="listening"
        errorMsg={null}
        transcript=""
        toolCalls={[]}
        isMuted={false}
        onToggleMute={vi.fn()}
        onClose={onClose}
      />
    );
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
