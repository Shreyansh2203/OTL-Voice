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
  onRegisterTrigger?: (trigger: () => void) => void;
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
  onRegisterTrigger,
}: ComposerProps) {
  const [text, setText] = useState("");
  const textRef = useRef("");
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
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  const listeningRef = useRef(listening);
  const disabledRef = useRef(disabled);
  const onStartMicRef = useRef(onStartMic);
  const onStopMicRef = useRef(onStopMic);
  const onSendRef = useRef(onSend);

  useEffect(() => {
    listeningRef.current = listening;
    disabledRef.current = disabled;
    onStartMicRef.current = onStartMic;
    onStopMicRef.current = onStopMic;
    onSendRef.current = onSend;
  });

  const toggleMic = () => {
    if (listeningRef.current) {
      clearSilenceTimer();
      void playMicStop();
      onStopMicRef.current?.();
      const current = textRef.current.trim();
      if (current && !disabledRef.current) {
        onSendRef.current(current);
        setText("");
      }
      return;
    }

    const playerStopEvent = new CustomEvent("otl:barge-in");
    window.dispatchEvent(playerStopEvent);
    void playMicStart();

    const baseDraft = textRef.current.trim();

    const resetSilenceTimer = () => {
      clearSilenceTimer();
      silenceTimerRef.current = setTimeout(() => {
        const toSend = textRef.current.trim();
        if (toSend && !disabledRef.current) {
          void playMicStop();
          onStopMicRef.current?.();
          onSendRef.current(toSend);
          setText("");
        }
      }, 2000);
    };

    onStartMicRef.current?.(
      (finalTranscript) => {
        if (!finalTranscript) return;
        const fullSpoken = (baseDraft ? baseDraft + " " + finalTranscript : finalTranscript).trim();
        setText(fullSpoken);
        resetSilenceTimer();
      },
      (interimTranscript) => {
        const preview = (baseDraft ? baseDraft + " " + (interimTranscript || "") : (interimTranscript || "")).trim();
        if (preview) {
          setText(preview);
        }
        clearSilenceTimer();
      },
      () => {
        const evt = new CustomEvent("otl:barge-in");
        window.dispatchEvent(evt);
      }
    );
  };

  const toggleMicRef = useRef(toggleMic);
  useEffect(() => {
    toggleMicRef.current = toggleMic;
  });

  useEffect(() => {
    if (onRegisterTrigger) {
      onRegisterTrigger(() => {
        if (!listeningRef.current && !disabledRef.current) {
          toggleMicRef.current();
        }
      });
    }
  }, [onRegisterTrigger]);

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