import { KeyboardEvent, useState, useRef, useEffect } from "react";
import { MicIcon, SendIcon, StopIcon } from "../../components/ui/icons";
import VoiceOrb from "../../components/ui/VoiceOrb";
import { playMicStart, playMicStop } from "../../lib/audio";
import { useMicLevel } from "../../lib/useMicLevel";
export interface ComposerProps {
  disabled: boolean;
  onSend: (text: string, isVoice?: boolean) => void;
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
  handsFree?: boolean;
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
  handsFree = false,
  onRegisterTrigger,
}: ComposerProps) {
  const [text, setText] = useState("");
  const textRef = useRef("");
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const micSessionRef = useRef(0);
  const micActiveRef = useRef(false);
  const micLevel = useMicLevel();

  // A sentence that already sounds complete needs less confirmation silence
  // than one that trails off mid-thought — mirrors how a human listener
  // waits less after "...see you tomorrow." than after "...and then, um".
  const SILENCE_MS_COMPLETE = 900;
  const SILENCE_MS_TRAILING = 1800;
  const TERMINAL_PUNCTUATION = /[.?!]\s*$/;

  const updateText = (value: string) => {
    textRef.current = value;
    setText(value);
  };

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
    return () => {
      micSessionRef.current += 1;
      micActiveRef.current = false;
      clearSilenceTimer();
      micLevel.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!handsFree || errorMsg || !listening) clearSilenceTimer();
  }, [handsFree, errorMsg, listening]);

  const finishMic = () => {
    micSessionRef.current += 1;
    micActiveRef.current = false;
    clearSilenceTimer();
    onStopMicRef.current?.();
    micLevel.stop();
    void playMicStop();
  };

  function send() {
    clearSilenceTimer();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    if (listening || micActiveRef.current) {
      finishMic();
    }
    onSend(trimmed, false);
    updateText("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.nativeEvent.isComposing) return;
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
  const handsFreeRef = useRef(handsFree);

  useEffect(() => {
    listeningRef.current = listening;
    disabledRef.current = disabled;
    onStartMicRef.current = onStartMic;
    onStopMicRef.current = onStopMic;
    onSendRef.current = onSend;
    handsFreeRef.current = handsFree;
  });

  const toggleMic = () => {
    if (listeningRef.current || micActiveRef.current) {
      finishMic();
      return;
    }

    const playerStopEvent = new CustomEvent("otl:barge-in");
    window.dispatchEvent(playerStopEvent);
    void playMicStart();
    void micLevel.start();

    const baseDraft = textRef.current.trim();
    let acceptedDraft = baseDraft;
    const session = ++micSessionRef.current;
    micActiveRef.current = true;
    const isCurrent = () => micSessionRef.current === session && micActiveRef.current;

    // Adaptive end-of-speech wait: short once the sentence already sounds
    // finished, longer if the person trailed off mid-thought. This is a
    // closer approximation of how a person actually waits during a
    // conversation than a single fixed timeout.
    const resetSilenceTimer = () => {
      clearSilenceTimer();
      const draft = textRef.current.trim();
      const wait = TERMINAL_PUNCTUATION.test(draft) ? SILENCE_MS_COMPLETE : SILENCE_MS_TRAILING;
      silenceTimerRef.current = setTimeout(() => {
        if (!isCurrent()) return;
        const toSend = textRef.current.trim();
        if (toSend && !disabledRef.current) {
          finishMic();
          if (handsFreeRef.current) {
            onSendRef.current(toSend, true);
            updateText("");
          }
        }
      }, wait);
    };

    onStartMicRef.current?.(
      (finalTranscript) => {
        if (!isCurrent() || !finalTranscript) return;
        const fullSpoken = (baseDraft ? baseDraft + " " + finalTranscript : finalTranscript).trim();
        acceptedDraft = fullSpoken;
        updateText(fullSpoken);
        resetSilenceTimer();
      },
      (interimTranscript) => {
        if (!isCurrent()) return;
        const preview = (baseDraft ? baseDraft + " " + (interimTranscript || "") : (interimTranscript || "")).trim();
        updateText(interimTranscript ? preview : acceptedDraft);
        clearSilenceTimer();
      },
      () => {
        if (!isCurrent()) return;
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
      return () => onRegisterTrigger(() => {});
    }
  }, [onRegisterTrigger]);

  const getPlaceholder = () => {
    if (voiceState === "speaking") {
      return "Assistant speaking… Tap the mic to interrupt.";
    }
    if (voiceState === "thinking") {
      return "Thinking… Tap the mic to interrupt.";
    }
    if (listening) {
      return "Listening… Speak naturally or type…";
    }
    return "Type or speak your reply…";
  };

  const getStatusLabel = () => {
    if (voiceState === "speaking") return "Speaking";
    if (voiceState === "thinking") return "Thinking";
    if (listening) return "Listening";
    return null;
  };
  const statusLabel = getStatusLabel();

  return (
    <div className="composer-wrapper">
      {errorMsg && (
        <div className="error small" role="status" style={{ marginBottom: 8, padding: "6px 12px" }}>
          {errorMsg}
        </div>
      )}
      {statusLabel && (
        <div className="voice-status-row" role="status" aria-live="polite">
          <VoiceOrb state={voiceState} level={micLevel.level} size={12} />
          <span>{statusLabel}</span>
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
            onChange={(e) => {
              if (listening || micActiveRef.current) finishMic();
              updateText(e.target.value);
            }}
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
