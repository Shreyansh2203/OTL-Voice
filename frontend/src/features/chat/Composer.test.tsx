import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import Composer from './Composer';
vi.mock('../../lib/audio', () => ({
  playMicStart: vi.fn().mockResolvedValue(undefined),
  playMicStop: vi.fn(),
}));
describe('Composer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => vi.useRealTimers());
  it('calls onSend and clears input when sending a message', () => {
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} supported={true} />);
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    const sendButton = screen.getByRole('button', { name: /send/i });
    fireEvent.change(textarea, { target: { value: 'Hello' } });
    expect(textarea).toHaveValue('Hello');
    fireEvent.click(sendButton);
    expect(mockSend).toHaveBeenCalledWith('Hello', false);
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
    expect(mockSend).toHaveBeenCalledWith('Keyboard message', false);
    expect(textarea).toHaveValue('');
  });
  it('does not call onSend when Shift+Enter is pressed', () => {
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} supported={true} />);
    const activeTextarea = screen.getByPlaceholderText(/Type or speak/i);
    fireEvent.change(activeTextarea, {
      target: { value: 'Multiline\nmessage' },
    });
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
    vi.useFakeTimers();
    let interimCb: any;
    let finalCb: any;
    const start = vi.fn((onFinal, onInterim) => {
      finalCb = onFinal;
      interimCb = onInterim;
    });
    const mockSend = vi.fn();
    render(
      <Composer
        disabled={false}
        onSend={mockSend}
        supported={true}
        listening={false}
        handsFree={true}
        onStartMic={start}
      />
    );
    const micBtn = screen.getByTitle('Speak');
    fireEvent.click(micBtn);
    expect(start).toHaveBeenCalled();
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    act(() => {
      interimCb('spoken text');
    });
    expect(textarea).toHaveValue('spoken text');
    act(() => {
      finalCb('spoken text complete');
    });
    expect(textarea).toHaveValue('spoken text complete');
    act(() => {
      vi.advanceTimersByTime(2600);
    });
    expect(mockSend).toHaveBeenCalledWith('spoken text complete', true);
    expect(textarea).toHaveValue('');
    vi.useRealTimers();
  });
  it('toggles microphone to stop listening', () => {
    const stop = vi.fn();
    const mockSend = vi.fn();
    render(
      <Composer
        disabled={false}
        onSend={mockSend}
        supported={true}
        listening={true}
        onStopMic={stop}
      />
    );
    const micBtn = screen.getByTitle('Stop recording');
    fireEvent.click(micBtn);
    expect(stop).toHaveBeenCalled();
  });
  it('renders dynamic placeholders based on voiceState', () => {
    const { rerender } = render(
      <Composer
        disabled={false}
        onSend={vi.fn()}
        supported={true}
        voiceState="speaking"
      />
    );
    expect(
      screen.getByPlaceholderText(
        /Assistant speaking… Tap the mic to interrupt/i
      )
    ).toBeInTheDocument();

    rerender(
      <Composer
        disabled={false}
        onSend={vi.fn()}
        supported={true}
        voiceState="thinking"
      />
    );
    expect(
      screen.getByPlaceholderText(/Thinking… Tap the mic to interrupt/i)
    ).toBeInTheDocument();

    rerender(
      <Composer
        disabled={false}
        onSend={vi.fn()}
        supported={true}
        listening={true}
        voiceState="listening"
      />
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

  it('stops after a final phrase and leaves it for review if handsFree is false, but wait, now it always sends on handsFree=true', () => {
    let final: any;
    const send = vi.fn();
    const stop = vi.fn();
    // Test with handsFree=false so it does NOT auto-submit on silence even if triggered manually
    render(<Composer disabled={false} supported handsFree={false} onSend={send} onStopMic={stop} 
      onStartMic={(onFinal) => { final = onFinal; }} />);
      
    fireEvent.click(screen.getByTitle('Speak'));
    expect(final).toBeDefined();
    
    act(() => final('Hello world.'));
    act(() => vi.advanceTimersByTime(1000));
    
    expect(screen.getByRole('textbox')).toHaveValue('Hello world.');
    expect(send).not.toHaveBeenCalled();
  });

  it('ignores late dictation after Send and after editing the draft', () => {
    let final: any;
    const send = vi.fn();
    const stop = vi.fn();
    render(<Composer disabled={false} supported onSend={send} onStopMic={stop}
      onStartMic={(onFinal) => { final = onFinal; }} />);
      
    fireEvent.click(screen.getByTitle('Speak'));
    act(() => final('Part one.'));
    
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Part one manually edited.' } });
    
    act(() => final('Late echo.'));
    
    fireEvent.click(screen.getByRole('Send'));
    expect(send).toHaveBeenCalledWith('Part one manually edited.', false);
  });

  it('removes a withdrawn interim guess and cancels hands-free sending', () => {
    let final: any, interim: any;
    const stop = vi.fn();
    const send = vi.fn();
    // Use an auto-trigger to test this so we don't send on manual stop
    render(<Composer disabled={false} supported handsFree onSend={send} onStopMic={stop}
      onStartMic={(onFinal, onInterim) => { final = onFinal; interim = onInterim; }} />);
      
    fireEvent.click(screen.getByTitle('Speak')); // Start mic manually
    act(() => final('Two hours')); // final with no punctuation = 1800ms
    act(() => interim('Two hours random noise'));
    act(() => interim(''));
    act(() => vi.advanceTimersByTime(2500));
    
    expect(screen.getByRole('textbox')).toHaveValue('Two hours');
    expect(send).not.toHaveBeenCalled();
  });

  it('manual Stop sends the draft immediately if handsFree is true', () => {
    let final: any;
    const stop = vi.fn();
    const send = vi.fn();
    render(<Composer disabled={false} supported handsFree onSend={send} onStopMic={stop}
      onStartMic={(onFinal) => { final = onFinal; }} />);
      
    fireEvent.click(screen.getByTitle('Speak'));
    act(() => final('Two hours'));
    fireEvent.click(screen.getByTitle('Speak')); // manual stop
    
    act(() => final('Unwanted words'));
    act(() => vi.advanceTimersByTime(2500));
    
    expect(stop).toHaveBeenCalledOnce();
    expect(screen.getByRole('textbox')).toHaveValue('');
    expect(send).toHaveBeenCalledWith('Two hours', false);
  });

  it('cancels a pending automatic send when hands-free is disabled', () => {
    vi.useFakeTimers();
    let final: (text: string) => void = () => {};
    const send = vi.fn();
    const props = { disabled: false, supported: true, onSend: send,
      onStartMic: (onFinal: (text: string) => void) => { final = onFinal; } };
    const { rerender } = render(<Composer {...props} handsFree />);
    fireEvent.click(screen.getByTitle('Speak'));
    act(() => final('Two hours'));
    rerender(<Composer {...props} handsFree={false} />);
    act(() => vi.advanceTimersByTime(2500));
    expect(send).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox')).toHaveValue('Two hours');
  });
});
