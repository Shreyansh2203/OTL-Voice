import { KeyboardEvent, useState } from "react";
import { MicIcon, SendIcon, StopIcon } from "./icons";

/**
 * Properties for the Composer component.
 */
export interface ComposerProps {
  /** If true, the input field and send button are disabled. */
  disabled: boolean;
  /** Callback fired when the user submits a message. */
  onSend: (text: string) => void;
  
  // Microphone props hoisted to parent
  supported?: boolean;
  listening?: boolean;
  onStartMic?: (
    onFinal: (spoken: string) => void,
    onInterim?: (spoken: string) => void,
    onSpeechStart?: () => void
  ) => void;
  onStopMic?: () => void;
  errorMsg?: string | null;
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
  supported = false,
  listening = false,
  onStartMic,
  onStopMic,
  errorMsg = null,
}: ComposerProps) {
  const [text, setText] = useState("");

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
      onStopMic?.();
      return;
    }

    // Immediately stop any playing TTS when the user explicitly clicks the mic,
    // otherwise the newly opened mic might pick up the TTS audio as "random words".
    const playerStopEvent = new CustomEvent("otl:barge-in");
    window.dispatchEvent(playerStopEvent);

    const baseText = text ? text + " " : "";
    onStartMic?.(
      (spoken) => {
        const finalStr = (baseText + spoken).trim();
        setText("");
        if (finalStr) {
          onSend(finalStr);
        }
      },
      (spoken) => setText(baseText + spoken),
      () => {
        // Barge-in: also stop any playing audio immediately when speech is detected
        const evt = new CustomEvent("otl:barge-in");
        window.dispatchEvent(evt);
      }
    );
  }

  return (
    <div className="composer-wrapper">
      {errorMsg && (
        <div className="error small" style={{ marginBottom: 8, padding: '6px 12px' }}>
          {errorMsg}
        </div>
      )}
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
    </div>
  );
}
