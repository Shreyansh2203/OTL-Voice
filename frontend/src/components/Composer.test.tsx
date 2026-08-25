import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Composer from './Composer';
vi.mock('../lib/audio', () => ({
  playMicStart: vi.fn().mockResolvedValue(undefined),
  playMicStop: vi.fn()
}));
describe('Composer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  it('calls onSend and clears input when sending a message', () => {
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} supported={true} />);
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    const sendButton = screen.getByRole('button', { name: /send/i });
    fireEvent.change(textarea, { target: { value: 'Hello' } });
    expect(textarea).toHaveValue('Hello');
    fireEvent.click(sendButton);
    expect(mockSend).toHaveBeenCalledWith('Hello');
    expect(textarea).toHaveValue(''); 
  });
  it('does not call onSend if input is empty or whitespace', () => {
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} supported={true} />);
    const sendButton = screen.getByRole('button', { name: /send/i });
    fireEvent.click(sendButton);
    expect(mockSend).not.toHaveBeenCalled();
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    fireEvent.change(textarea, { target: { value: '   ' } });
    fireEvent.click(sendButton);
    expect(mockSend).not.toHaveBeenCalled();
  });
  it('calls onSend when Enter is pressed (without Shift)', () => {
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} supported={true} />);
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    fireEvent.change(textarea, { target: { value: 'Keyboard message' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    expect(mockSend).toHaveBeenCalledWith('Keyboard message');
    expect(textarea).toHaveValue('');
  });
  it('does not call onSend when Shift+Enter is pressed', () => {
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} supported={true} />);
    const activeTextarea = screen.getByPlaceholderText(/Type or speak/i);
    fireEvent.change(activeTextarea, { target: { value: 'Multiline\nmessage' } });
    fireEvent.keyDown(activeTextarea, { key: 'Enter', shiftKey: true });
    expect(mockSend).not.toHaveBeenCalled();
  });
  it('does not call onSend if disabled', () => {
    const mockSend = vi.fn();
    render(<Composer disabled={true} onSend={mockSend} supported={true} />);
    const activeTextarea = screen.getByPlaceholderText(/Type or speak/i);
    fireEvent.change(activeTextarea, { target: { value: '   ' } });
    fireEvent.keyDown(activeTextarea, { key: 'Enter', shiftKey: false });
    expect(mockSend).not.toHaveBeenCalled();
  });
  it('toggles microphone to start listening', async () => {
    let interimCb: any;
    let finalCb: any;
    const start = vi.fn((onFinal, onInterim) => {
      finalCb = onFinal;
      interimCb = onInterim;
    });
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} supported={true} listening={false} onStartMic={start} />);
    const micBtn = screen.getByTitle('Speak');
    fireEvent.click(micBtn);
    await waitFor(() => expect(start).toHaveBeenCalled());
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    act(() => {
      interimCb('spoken text');
    });
    expect(textarea).toHaveValue('spoken text');
    act(() => {
      finalCb('spoken text complete');
    });
    expect(mockSend).toHaveBeenCalledWith('spoken text complete');
    expect(textarea).toHaveValue('');
  });
  it('toggles microphone to stop listening', () => {
    const stop = vi.fn();
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} supported={true} listening={true} onStopMic={stop} />);
    const micBtn = screen.getByTitle('Stop recording');
    fireEvent.click(micBtn);
    expect(stop).toHaveBeenCalled();
  });
  it('renders dynamic placeholders based on voiceState', () => {
    const { rerender } = render(
      <Composer disabled={false} onSend={vi.fn()} supported={true} voiceState="speaking" />
    );
    expect(
      screen.getByPlaceholderText(/Assistant speaking… \(speak anytime to interrupt\)/i)
    ).toBeInTheDocument();

    rerender(
      <Composer disabled={false} onSend={vi.fn()} supported={true} voiceState="thinking" />
    );
    expect(screen.getByPlaceholderText(/Thinking… \(speak anytime\)/i)).toBeInTheDocument();

    rerender(
      <Composer disabled={false} onSend={vi.fn()} supported={true} listening={true} voiceState="listening" />
    );
    expect(
      screen.getByPlaceholderText(/Listening… Speak naturally or type…/i)
    ).toBeInTheDocument();
  });
  it('ignores other keys or shift+enter', () => {
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} supported={true} />);
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    fireEvent.change(textarea, { target: { value: 'Test' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
    fireEvent.keyDown(textarea, { key: 'a', shiftKey: false });
    expect(mockSend).not.toHaveBeenCalled();
  });
});