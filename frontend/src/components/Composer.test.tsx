import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Composer from './Composer';
import * as voiceLib from '../lib/voice';

vi.mock('../lib/voice', () => ({
  useSpeechInput: vi.fn(),
}));

describe('Composer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls onSend and clears input when sending a message', () => {
    vi.mocked(voiceLib.useSpeechInput).mockReturnValue({
      supported: true,
      listening: false,
      start: vi.fn(),
      stop: vi.fn(),
    });
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} />);
    
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    const sendButton = screen.getByRole('button', { name: /send/i });

    // Type a message
    fireEvent.change(textarea, { target: { value: 'Hello' } });
    expect(textarea).toHaveValue('Hello');

    // Click send
    fireEvent.click(sendButton);

    expect(mockSend).toHaveBeenCalledWith('Hello');
    expect(textarea).toHaveValue(''); // Input should be cleared
  });

  it('submits on Enter key (without shift)', () => {
    vi.mocked(voiceLib.useSpeechInput).mockReturnValue({
      supported: true,
      listening: false,
      start: vi.fn(),
      stop: vi.fn(),
    });
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} />);
    
    const textarea = screen.getByPlaceholderText(/Type or speak/i);

    fireEvent.change(textarea, { target: { value: 'Test enter' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    expect(mockSend).toHaveBeenCalledWith('Test enter');
  });

  it('does not send if input is empty or disabled', () => {
    vi.mocked(voiceLib.useSpeechInput).mockReturnValue({
      supported: true,
      listening: false,
      start: vi.fn(),
      stop: vi.fn(),
    });
    const mockSend = vi.fn();
    render(<Composer disabled={true} onSend={mockSend} />);
    
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    const sendButton = screen.getByRole('button', { name: /send/i });

    // Disabled test
    fireEvent.change(textarea, { target: { value: 'Hello' } });
    fireEvent.click(sendButton);
    expect(mockSend).not.toHaveBeenCalled();

    // Empty test
    render(<Composer disabled={false} onSend={mockSend} />);
    const activeTextarea = screen.getAllByPlaceholderText(/Type or speak/i)[1];
    fireEvent.change(activeTextarea, { target: { value: '   ' } });
    fireEvent.keyDown(activeTextarea, { key: 'Enter', shiftKey: false });
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('toggles microphone to start listening', () => {
    const start = vi.fn((cb) => cb('spoken text'));
    vi.mocked(voiceLib.useSpeechInput).mockReturnValue({
      supported: true,
      listening: false,
      start,
      stop: vi.fn(),
    });
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} />);
    
    const micBtn = screen.getByTitle('Speak');
    fireEvent.click(micBtn);
    
    expect(start).toHaveBeenCalled();
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    expect(textarea).toHaveValue('spoken text');
    
    // Test appending text
    start.mockImplementation((cb) => cb('more text'));
    fireEvent.click(micBtn);
    expect(textarea).toHaveValue('spoken text more text');
  });
  
  it('toggles microphone to stop listening', () => {
    const stop = vi.fn();
    vi.mocked(voiceLib.useSpeechInput).mockReturnValue({
      supported: true,
      listening: true,
      start: vi.fn(),
      stop,
    });
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} />);
    
    const micBtn = screen.getByTitle('Stop recording');
    fireEvent.click(micBtn);
    
    expect(stop).toHaveBeenCalled();
  });
  it('ignores other keys or shift+enter', () => {
    vi.mocked(voiceLib.useSpeechInput).mockReturnValue({
      supported: true,
      listening: false,
      start: vi.fn(),
      stop: vi.fn(),
    });
    const mockSend = vi.fn();
    render(<Composer disabled={false} onSend={mockSend} />);
    const textarea = screen.getByPlaceholderText(/Type or speak/i);
    fireEvent.change(textarea, { target: { value: 'Test' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
    fireEvent.keyDown(textarea, { key: 'a', shiftKey: false });
    expect(mockSend).not.toHaveBeenCalled();
  });
});
