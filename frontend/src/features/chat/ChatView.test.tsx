import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ChatView from './ChatView';
import { updateLastAssistant } from '../../lib/chat';
import * as api from '../../api/client';
import * as voiceLib from '../../lib/voice';
import * as ociVoiceLib from '../../lib/oci_voice';
vi.mock('../../api/client', () => ({
  chatStream: vi.fn(),
  tts: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));
vi.mock('../../lib/voice', () => ({
  useAudioPlayer: vi.fn(() => ({
    play: vi.fn(),
    stop: vi.fn(),
  })),
  useSpeechInput: vi.fn(() => ({
    supported: true,
    listening: false,
    isListening: vi.fn(() => false),
    start: vi.fn(),
    stop: vi.fn(),
  })),
}));
vi.mock('../../lib/oci_voice', () => ({
  useWorkletAudioPlayer: vi.fn(() => ({
    play: vi.fn(),
    stop: vi.fn(),
  })),
  useOciSpeechInput: vi.fn(() => ({
    supported: true,
    listening: false,
    isListening: vi.fn(() => false),
    start: vi.fn(),
    stop: vi.fn(),
  })),
}));
vi.mock('../../lib/useGeminiLive', () => ({
  useGeminiLive: vi.fn(() => ({
    liveState: 'idle',
    errorMsg: null,
    transcript: '',
    toolCalls: [],
    isMuted: false,
    startSession: vi.fn(),
    stopSession: vi.fn(),
    toggleMute: vi.fn(),
    isActive: false,
  })),
}));
vi.mock('../timesheets/TimecardHistory', () => ({
  default: () => <div data-testid="timecard-history" />,
}));
describe('ChatView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });
  it('renders chat view and kicks off', async () => {
    vi.mocked(api.chatStream).mockImplementation(async (history, onEvent) => {
      onEvent({ delta: 'Hello' });
      onEvent({ done: true });
    });
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    expect(screen.getByText('Test')).toBeInTheDocument();
    await waitFor(() => {
      expect(api.chatStream).toHaveBeenCalled();
    });
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });
  it('switches to history tab and back to chat', async () => {
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    await waitFor(() => {
      expect(api.chatStream).toHaveBeenCalled();
    });
    const historyBtn = screen.getByText('History');
    fireEvent.click(historyBtn);
    expect(screen.getByTestId('timecard-history')).toBeInTheDocument();
    const chatBtn = screen.getByText('Assistant');
    fireEvent.click(chatBtn);
    expect(screen.queryByTestId('timecard-history')).not.toBeInTheDocument();
  });
  it('toggles voice', async () => {
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    await waitFor(() => {
      expect(api.chatStream).toHaveBeenCalled();
    });
    const voiceBtn = screen.getByText('Voice On');
    expect(screen.getByText(/Voice on/i)).toBeInTheDocument();
    fireEvent.click(voiceBtn);
    expect(screen.getByText(/Voice off/i)).toBeInTheDocument();
  });
  it('calls onLogout', async () => {
    const onLogout = vi.fn();
    render(
      <ChatView
        username="Test"
        onLogout={onLogout}
        onSessionExpired={vi.fn()}
      />
    );
    await waitFor(() => {
      expect(api.chatStream).toHaveBeenCalled();
    });
    fireEvent.click(screen.getByText('Sign out'));
    expect(onLogout).toHaveBeenCalled();
  });
  it('sends user message and handles stream response', async () => {
    vi.mocked(api.chatStream).mockImplementation(async (history, onEvent) => {
      if (history.some((m: any) => m.content === 'My message')) {
        onEvent({ delta: 'Response' });
        onEvent({ done: true });
      }
    });
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    await waitFor(() => {
      expect(api.chatStream).toHaveBeenCalled();
    });
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'My message' } });
    const sendBtn = screen.getByRole('button', { name: /send/i });
    fireEvent.click(sendBtn);
    expect(screen.getByText('My message')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('Response')).toBeInTheDocument();
    });
  });
  it('handles stream error properly', async () => {
    let mockOnEvent: any;
    vi.mocked(api.chatStream).mockImplementation((history, onEvent) => {
      mockOnEvent = onEvent;
      return new Promise<void>(() => {});
    });
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    await waitFor(() => {
      expect(api.chatStream).toHaveBeenCalled();
    });
    act(() => {
      mockOnEvent({ error: 'Failed!' });
    });
    await waitFor(() => {
      expect(screen.getByText('Sorry — Failed!')).toBeInTheDocument();
    });
  });
  it('handles API rejection 401', async () => {
    const onSessionExpired = vi.fn();
    vi.mocked(api.chatStream).mockRejectedValue(
      new api.ApiError(401, 'Unauthorized')
    );
    render(
      <ChatView
        username="Test"
        onLogout={vi.fn()}
        onSessionExpired={onSessionExpired}
      />
    );
    await waitFor(() => {
      expect(onSessionExpired).toHaveBeenCalled();
    });
  });
  it('handles general API rejection', async () => {
    vi.mocked(api.chatStream).mockRejectedValue(new Error('Network error'));
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    await waitFor(() => {
      expect(screen.getByText('Sorry — Network error')).toBeInTheDocument();
    });
  });
  it('does not speak if voice is off', async () => {
    vi.mocked(api.chatStream).mockImplementation(async (history, onEvent) => {
      onEvent({ delta: 'Hello' });
      onEvent({ done: true });
    });
    const play = vi.fn();
    vi.mocked(voiceLib.useAudioPlayer).mockReturnValue({
      play,
      stop: vi.fn(),
    } as any);
    vi.mocked(ociVoiceLib.useWorkletAudioPlayer).mockReturnValue({
      play,
      stop: vi.fn(),
    } as any);
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    const voiceBtn = screen.getByText('Voice On');
    fireEvent.click(voiceBtn);
    await waitFor(() => {
      expect(api.chatStream).toHaveBeenCalled();
    });
    expect(play).not.toHaveBeenCalled();
  });
  it('extracts entries block and renders ReviewPanel', async () => {
    vi.mocked(api.chatStream).mockImplementation(async (history, onEvent) => {
      onEvent({
        delta:
          'Here is your timecard:\n```json\n{"entries":[{"projectName":"Proj1", "taskName":"Task1", "hours":4}]}\n```',
      });
      onEvent({ done: true });
    });
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    await waitFor(() => {
      expect(screen.getByText('Proj1')).toBeInTheDocument();
      expect(screen.getByText('4')).toBeInTheDocument();
    });
  });
  it('handles missing assistant role when updating (branch coverage)', async () => {
    let mockOnEvent: any;
    vi.mocked(api.chatStream).mockImplementation(async (history, onEvent) => {
      mockOnEvent = onEvent;
      onEvent({ delta: 'Init' });
      onEvent({ done: true });
    });
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    await waitFor(() => expect(api.chatStream).toHaveBeenCalled());
    vi.mocked(api.chatStream).mockClear();

    vi.mocked(api.chatStream).mockImplementation((history, onEvent) => {
      mockOnEvent = onEvent;
      return new Promise<void>(() => {});
    });
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'Msg' } });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(api.chatStream).toHaveBeenCalled());
    act(() => {
      mockOnEvent({ delta: 'Some ' });
      mockOnEvent({ error: 'Oops' });
    });
    await waitFor(() => expect(screen.getByText(/Some/i)).toBeInTheDocument());
  });
  it('handles general string error', async () => {
    vi.mocked(api.chatStream).mockRejectedValue('String Error');
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    await waitFor(() =>
      expect(screen.getByText('Sorry — Connection error.')).toBeInTheDocument()
    );
  });
  it('handles barge-in interruption by stopping audio and active generation', async () => {
    let mockOnEvent: any;
    vi.mocked(api.chatStream).mockImplementation(
      async (history, onEvent, signal) => {
        mockOnEvent = onEvent;
        signal?.addEventListener('abort', () => {
          // aborted
        });
      }
    );
    const stopAudio = vi.fn();
    vi.mocked(voiceLib.useAudioPlayer).mockReturnValue({
      play: vi.fn(),
      stop: stopAudio,
    } as any);
    vi.mocked(ociVoiceLib.useWorkletAudioPlayer).mockReturnValue({
      play: vi.fn(),
      stop: stopAudio,
    } as any);
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    await waitFor(() => expect(api.chatStream).toHaveBeenCalled());

    act(() => {
      mockOnEvent({ delta: 'Assistant speaking text...' });
    });
    expect(screen.getByText('Assistant speaking text...')).toBeInTheDocument();

    // Trigger barge-in event
    act(() => {
      window.dispatchEvent(new CustomEvent('otl:barge-in'));
    });

    expect(stopAudio).toHaveBeenCalled();
  });

  it('stops mic when farewell is detected in assistant response', async () => {
    const stopMic = vi.fn();
    const micMock = {
      supported: true,
      listening: true,
      isListening: vi.fn(() => true),
      start: vi.fn(),
      stop: stopMic,
    };
    vi.mocked(voiceLib.useSpeechInput).mockReturnValue(micMock);
    vi.mocked(ociVoiceLib.useOciSpeechInput).mockReturnValue(micMock);
    vi.mocked(api.chatStream).mockImplementation(async (history, onEvent) => {
      onEvent({ delta: 'Goodbye! Have a great day.' });
      onEvent({ done: true });
    });
    render(
      <ChatView username="Test" onLogout={vi.fn()} onSessionExpired={vi.fn()} />
    );
    await waitFor(() => {
      expect(stopMic).toHaveBeenCalled();
    });
  });

  it('updateLastAssistant returns correctly when missing assistant message', () => {
    const messages = [{ role: 'user', content: 'hello' } as any];
    const next = updateLastAssistant(messages, 'test', false);
    expect(next).toEqual(messages);
  });
});
