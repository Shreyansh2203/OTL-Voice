import { KeyboardEvent, useState } from "react";
import { useSpeechInput } from "../lib/voice";
import { MicIcon, SendIcon, StopIcon } from "./icons";

/**
 * Properties for the Composer component.
 */
export interface ComposerProps {
  /** If true, the input field and send button are disabled. */
  disabled: boolean;
  /** Callback fired when the user submits a message. */
  onSend: (text: string) => void;
}

/**
 * A chat input component supporting both text typing and microphone voice dictation 
 * via the Web Speech API.
 * 
 * @param props - Component properties.
 */
export default function Composer({
  disabled,
  onSend,
}: ComposerProps) {
  const [text, setText] = useState("");
  const { supported, listening, start, stop } = useSpeechInput();

  function send() {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function toggleMic() {
    if (listening) {
      stop();
      return;
    }
    start((spoken) => setText((prev) => (prev ? prev + " " : "") + spoken));
  }

  return (
    <div className={`prompt-bar-container ${listening ? "listening" : ""}`}>
      <div className="prompt-bar">
        {supported && (
          <button
            type="button"
            className={`icon-btn mic ${listening ? "active" : ""}`}
            onClick={toggleMic}
            title={listening ? "Stop recording" : "Speak"}
            aria-label={listening ? "Stop recording" : "Speak"}
          >
            {listening ? <StopIcon /> : <MicIcon />}
          </button>
        )}

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={listening ? "Listening…" : "Type or speak your reply…"}
          rows={1}
          disabled={disabled}
        />

        <button
          type="button"
          className="icon-btn send"
          onClick={send}
          disabled={disabled || !text.trim()}
          title="Send"
          aria-label="Send"
        >
          <SendIcon />
        </button>
      </div>
    </div>
  );
}
