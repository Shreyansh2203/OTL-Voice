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
  const accumulatedRef = useRef("");
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    textRef.current = text;
  }, [text]);

  const clearSilenceTimer = () => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  };

  useEffect(() => {
    return () => clearSilenceTimer();
  }, []);

  function send() {
    clearSilenceTimer();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    if (listening) {
      onStopMic?.();
    }
    onSend(trimmed);
    setText("");
    accumulatedRef.current = "";
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  async function toggleMic() {
    if (listening) {
      clearSilenceTimer();
      void playMicStop();
      onStopMic?.();
      const current = textRef.current.trim();
      if (current && !disabled) {
        onSend(current);
        setText("");
        accumulatedRef.current = "";
      }
      return;
    }

    const playerStopEvent = new CustomEvent("otl:barge-in");
    window.dispatchEvent(playerStopEvent);
    void playMicStart();

    accumulatedRef.current = textRef.current ? textRef.current.trim() + " " : "";

    const resetSilenceTimer = () => {
      clearSilenceTimer();
      silenceTimerRef.current = setTimeout(() => {
        const toSend = textRef.current.trim();
        if (toSend && !disabled) {
          void playMicStop();
          onStopMic?.();
          onSend(toSend);
          setText("");
          accumulatedRef.current = "";
        }
      }, 2500);
    };

    onStartMic?.(
      (finalChunk) => {
        if (!finalChunk) return;
        const currentAcc = (accumulatedRef.current + " " + finalChunk).trim();
        accumulatedRef.current = currentAcc + " ";
        setText(currentAcc);
        resetSilenceTimer();
      },
      (interimChunk) => {
        const fullPreview = (accumulatedRef.current + (interimChunk || "")).trim();
        setText(fullPreview);
        clearSilenceTimer();
      },
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