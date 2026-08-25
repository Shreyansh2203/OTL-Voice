import { KeyboardEvent, useState, useRef, useEffect } from "react";
import { MicIcon, SendIcon, StopIcon } from "./icons";
import { playMicStart, playMicStop } from "../lib/audio";
export interface ComposerProps {
  disabled: boolean;
  onSend: (text: string) => void;
  supported?: boolean;
  listening?: boolean;
  onStartMic?: (
    onFinal: (spoken: string) => void,
    onInterim?: (spoken: string) => void,
    onSpeechStart?: () => void
  ) => void;
  onStopMic?: () => void;
  errorMsg?: string | null;
  voiceState?: "idle" | "listening" | "thinking" | "speaking";
}

export default function Composer({
  disabled,
  onSend,
  supported = false,
  listening = false,
  onStartMic,
  onStopMic,
  errorMsg = null,
  voiceState = "idle",
}: ComposerProps) {
  const [text, setText] = useState("");
  const textRef = useRef("");

  useEffect(() => {
    textRef.current = text;
  }, [text]);

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

  async function toggleMic() {
    if (listening) {
      playMicStop();
      onStopMic?.();
      return;
    }
    const playerStopEvent = new CustomEvent("otl:barge-in");
    window.dispatchEvent(playerStopEvent);
    await playMicStart();
    if (!(window as any).mockMic) {
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    const baseText = textRef.current ? textRef.current + " " : "";
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
        const evt = new CustomEvent("otl:barge-in");
        window.dispatchEvent(evt);
      }
    );
  }

  const getPlaceholder = () => {
    if (voiceState === "speaking") {
      return "Assistant speaking… (speak anytime to interrupt)";
    }
    if (voiceState === "thinking") {
      return "Thinking… (speak anytime)";
    }
    if (listening) {
      return "Listening… Speak naturally or type…";
    }
    return "Type or speak your reply…";
  };

  return (
    <div className="composer-wrapper">
      {errorMsg && (
        <div className="error small" style={{ marginBottom: 8, padding: "6px 12px" }}>
          {errorMsg}
        </div>
      )}
      <div
        className={`prompt-bar-container ${listening ? "listening" : ""} ${
          voiceState === "speaking" ? "speaking" : ""
        }`}
      >
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
            placeholder={getPlaceholder()}
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