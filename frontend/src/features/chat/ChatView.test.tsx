import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatView from './ChatView';
import * as api from '../../api/client';
import * as voiceLib from '../../lib/voice';
import type { ChatEvent, TimecardEntry } from '../../types';

vi.mock('../../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/client')>();
  return {
    ...original,
    chatStream: vi.fn(),
    tts: vi.fn(),
    getHealthOtl: vi.fn(),
    getAssignments: vi.fn(),
    listTimecards: vi.fn(),
    submitTimecard: vi.fn(),
  };
});

vi.mock('../../lib/audio', () => ({
  playThinkingCue: vi.fn(async () => {}),
}));

vi.mock('../../lib/voice', () => ({
  useAudioPlayer: vi.fn(),
  useSpeechInput: vi.fn(),
}));

const playerStop = vi.fn();
const micStop = vi.fn();
const micStart = vi.fn(async () => {});

const validEntry: TimecardEntry = {
  employeeNumber: '7',
  employeeName: 'Mala Kumari',
  projectId: 'PRJ-1',
  projectNo: 'PA-1',
  projectName: 'Operations',
  workOrder: 'WO-9',
  taskId: 'TASK-1',
  taskDetails: 'Reviewed weekly payroll entries',
  hours: 2.5,
  date: '2026-09-25',
  startTime: '09:00',
  stopTime: '11:30',
  payrollTimeType: 'Regular',
  expenditureType: 'Regular Time',
  currencyCode: 'USD',
};

function doneOnly() {
  return vi
    .mocked(api.chatStream)
    .mockImplementation(async (_history, onEvent) => {
      onEvent({ done: true } as ChatEvent);
    });
}

describe('ChatView', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('otl_voice_on', 'false');
    vi.mocked(api.chatStream).mockReset();
    vi.mocked(api.tts).mockReset().mockResolvedValue(new Blob());
    vi.mocked(api.getHealthOtl)
      .mockReset()
      .mockResolvedValue({ ok: true, username: '7' });
    vi.mocked(api.getAssignments).mockReset().mockResolvedValue({
      employeeId: '7',
      fullName: 'Mala Kumari',
      workOrders: [],
    });
    vi.mocked(api.listTimecards).mockReset().mockResolvedValue({ items: [] });
    vi.mocked(api.submitTimecard).mockReset();
    playerStop.mockReset();
    micStop.mockReset();
    micStart.mockClear();
    vi.mocked(voiceLib.useAudioPlayer).mockReturnValue({
      play: vi.fn(async () => ({ success: true })),
      stop: playerStop,
      playing: false,
    });
    vi.mocked(voiceLib.useSpeechInput).mockReturnValue({
      supported: true,
      listening: false,
      isListening: () => false,
      errorMsg: null,
      notice: null,
      browserSpeechFallbackAvailable: false,
      useBrowserSpeechFallback: vi.fn(),
      start: micStart,
      stop: micStop,
    });
    doneOnly();
  });

  it('streams a user reply and renders it without spoken audio when voice is off', async () => {
    vi.mocked(api.chatStream).mockImplementation(
      async (history, onEvent) => {
        if (history.some((message) => message.content === 'My message')) {
          onEvent({ delta: 'Response from the assistant' });
          onEvent({ done: true });
        }
      }
    );
    render(
      <ChatView
        username="7"
        onLogout={vi.fn()}
        onSessionExpired={vi.fn()}
      />
    );
    await waitFor(() => expect(api.chatStream).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByRole('textbox', { name: /message/i }), {
      target: { value: 'My message' },
    });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(screen.getByText('My message')).toBeInTheDocument();
    expect(await screen.findByText('Response from the assistant')).toBeInTheDocument();
    expect(api.tts).not.toHaveBeenCalled();
  });

  it('opens the complete manual form when assistant JSON is malformed', async () => {
    vi.mocked(api.chatStream).mockImplementation(
      async (history, onEvent) => {
        if (history.some((message) => message.content === 'Capture')) {
          onEvent({
            delta: 'I could not finalize this.\n```json\n{"entries":[\n```',
          });
          onEvent({ done: true });
        }
      }
    );
    render(
      <ChatView
        username="Test User"
        employeeNumber="7"
        onLogout={vi.fn()}
        onSessionExpired={vi.fn()}
      />
    );
    await waitFor(() => expect(api.chatStream).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByRole('textbox', { name: /message/i }), {
      target: { value: 'Capture' },
    });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(
      await screen.findByText(/did not return a valid timesheet payload/i)
    ).toBeInTheDocument();
    expect(
      await screen.findByRole('heading', { name: 'Manual Timesheet Review' })
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Employee number')).toHaveValue('7');
    expect(screen.getByLabelText('Employee name')).toHaveValue('Test User');
    const dateValue = (screen.getByLabelText('Date') as HTMLInputElement).value;
    expect(dateValue).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(screen.getByLabelText('Hours')).toHaveAttribute('step', '0.25');
  });

  it('renders a valid assistant payload as a fully editable review', async () => {
    vi.mocked(api.chatStream).mockImplementation(
      async (history, onEvent) => {
        if (history.some((message) => message.content === 'Record it')) {
          onEvent({
            delta: `Review before approval.\n\`\`\`json\n${JSON.stringify({
              entries: [validEntry],
            })}\n\`\`\``,
          });
          onEvent({ done: true });
        }
      }
    );
    render(
      <ChatView
        username="7"
        onLogout={vi.fn()}
        onSessionExpired={vi.fn()}
      />
    );
    await waitFor(() => expect(api.chatStream).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByRole('textbox', { name: /message/i }), {
      target: { value: 'Record it' },
    });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(await screen.findByText('Review Timesheet')).toBeInTheDocument();
    expect(screen.getByLabelText('Project number')).toHaveValue('PA-1');
    expect(screen.getByLabelText('Work order')).toHaveValue('WO-9');
    expect(screen.getByLabelText('Hours')).toHaveValue(2.5);
    expect(screen.getByLabelText('Stop time (optional)')).toHaveValue('11:30');
    expect(screen.getByLabelText('Payroll time type')).toHaveValue('Regular');
    expect(screen.getByLabelText('Expenditure type')).toHaveValue(
      'Regular Time'
    );
    expect(
      screen.queryByText(/The assistant did not return a valid timesheet payload/i)
    ).not.toBeInTheDocument();
  });

  it('restores an owner-scoped draft and history within persistence caps', async () => {
    const messages = Array.from({ length: 60 }, (_, index) => ({
      role: index % 2 === 0 ? ('user' as const) : ('assistant' as const),
      content: `message-${index}-${'x'.repeat(3000)}`,
    }));
    localStorage.setItem(
      'otl_conversation_v1',
      JSON.stringify({ owner: '7', messages, draft: 'd'.repeat(12000) })
    );

    render(
      <ChatView
        username="7"
        onLogout={vi.fn()}
        onSessionExpired={vi.fn()}
      />
    );

    expect(screen.getByRole('textbox', { name: /message/i })).toHaveValue(
      'd'.repeat(10000)
    );
    expect(api.chatStream).not.toHaveBeenCalled();
    await waitFor(() => {
      const stored = localStorage.getItem('otl_conversation_v1');
      expect(stored).not.toBeNull();
      expect(stored!.length).toBeLessThanOrEqual(65536);
      const parsed = JSON.parse(stored!);
      expect(parsed.messages.length).toBeLessThanOrEqual(50);
      expect(parsed.draft).toBe('d'.repeat(10000));
      expect(parsed.messages.at(-1)?.content).toContain('message-59');
    });
  });

  it('resets the persisted conversation before starting a new one', async () => {
    localStorage.setItem(
      'otl_conversation_v1',
      JSON.stringify({
        owner: '7',
        messages: [{ role: 'user', content: 'old private message' }],
        draft: 'old draft',
      })
    );
    render(
      <ChatView
        username="7"
        onLogout={vi.fn()}
        onSessionExpired={vi.fn()}
      />
    );
    expect(screen.getByText('old private message')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /new conversation/i }));

    await waitFor(() => {
      const parsed = JSON.parse(
        localStorage.getItem('otl_conversation_v1') || '{}'
      );
      expect(parsed.draft).toBe('');
      expect(
        parsed.messages?.some((message: { content: string }) =>
          message.content.includes('old private message')
        )
      ).toBe(false);
    });
    expect(screen.queryByText('old private message')).not.toBeInTheDocument();
    await waitFor(() => expect(api.chatStream).toHaveBeenCalledTimes(1));
  });

  it('clears persisted state only after confirmed logout', async () => {
    const onLogout = vi.fn(async () => {});
    localStorage.setItem(
      'otl_conversation_v1',
      JSON.stringify({ owner: '7', messages: [], draft: 'private' })
    );
    render(
      <ChatView
        username="7"
        onLogout={onLogout}
        onSessionExpired={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    await waitFor(() => expect(onLogout).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(localStorage.getItem('otl_conversation_v1')).toBeNull()
    );
  });

  it('keeps the session visible when logout cannot be confirmed', async () => {
    const onLogout = vi.fn(async () => {
      throw new Error('offline');
    });
    localStorage.setItem(
      'otl_conversation_v1',
      JSON.stringify({ owner: '7', messages: [], draft: 'private' })
    );
    render(
      <ChatView
        username="7"
        onLogout={onLogout}
        onSessionExpired={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    expect(await screen.findByText(/sign out could not be confirmed/i)).toBeInTheDocument();
    expect(
      localStorage.getItem('otl_conversation_v1')
    ).not.toBeNull();
  });

  it('aborts streams and releases audio, microphone, and TTS resources on unmount', async () => {
    let streamSignal: AbortSignal | undefined;
    vi.mocked(api.chatStream).mockImplementation(
      (_history, _onEvent, signal) =>
        new Promise<void>((resolve) => {
          streamSignal = signal;
          signal?.addEventListener('abort', () => resolve());
        })
    );
    const { unmount } = render(
      <ChatView
        username="7"
        onLogout={vi.fn()}
        onSessionExpired={vi.fn()}
      />
    );
    await waitFor(() => expect(streamSignal).toBeDefined());

    unmount();

    expect(streamSignal?.aborted).toBe(true);
    expect(playerStop).toHaveBeenCalled();
    expect(micStop).toHaveBeenCalledWith(true);
  });

  it('clears local state when health reports an expired session', async () => {
    const onSessionExpired = vi.fn();
    vi.mocked(api.getHealthOtl).mockRejectedValue(
      new api.ApiError(401, 'Session expired')
    );
    localStorage.setItem(
      'otl_conversation_v1',
      JSON.stringify({ owner: '7', messages: [], draft: 'private' })
    );
    render(
      <ChatView
        username="7"
        onLogout={vi.fn()}
        onSessionExpired={onSessionExpired}
      />
    );

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem('otl_conversation_v1')).toBeNull();
  });
});
