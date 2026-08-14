import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { extractEntries, stripEntriesBlock } from "../lib/entries";
import { useAudioPlayer } from "../lib/voice";
import type { ChatMessage } from "../types";
import Composer from "./Composer";
import MessageBubble from "./MessageBubble";
import ReviewPanel from "./ReviewPanel";
import TimecardHistory from "./TimecardHistory";
import { SpeakerIcon } from "./icons";

const KICKOFF = "Please begin the session now.";

/** Replace the content of the last assistant message (the streaming target). */
function updateLastAssistant(
  messages: ChatMessage[],
  content: string,
  streaming: boolean
): ChatMessage[] {
  const next = [...messages];
  for (let i = next.length - 1; i >= 0; i--) {
    if (next[i].role === "assistant") {
      next[i] = { ...next[i], content, streaming };
      break;
    }
  }
  return next;
}

export default function ChatView({
  username,
  onLogout,
  onSessionExpired,
}: {
  username: string;
  onLogout: () => void;
  onSessionExpired: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [voiceOn, setVoiceOn] = useState(true);
  const [viewTab, setViewTab] = useState<"chat" | "history">("chat");

  const player = useAudioPlayer();
  const voiceOnRef = useRef(voiceOn);
  voiceOnRef.current = voiceOn;
  const didInit = useRef(false);
  const scrollAnchor = useRef<HTMLDivElement | null>(null);

  const speak = useCallback(
    async (text: string) => {
      const clean = stripEntriesBlock(text);
      if (!clean) return;
      try {
        const blob = await api.tts(clean);
        await player.play(blob);
      } catch {
        /* TTS is best-effort; ignore failures */
      }
    },
    [player]
  );

  const runAssistant = useCallback(
    async (history: ChatMessage[]) => {
      setSending(true);
      player.stop();
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "", streaming: true },
      ]);

      let acc = "";
      let finalText = "";
      try {
        await api.chatStream(history, (ev) => {
          if (ev.delta) {
            acc += ev.delta;
            setMessages((prev) => updateLastAssistant(prev, acc, true));
          } else if (ev.error) {
            finalText = acc || `Sorry — ${ev.error}`;
            setMessages((prev) => updateLastAssistant(prev, finalText, false));
          } else if (ev.done) {
            finalText = acc;
            setMessages((prev) => updateLastAssistant(prev, acc, false));
          }
        });
        if (!finalText) {
          finalText = acc;
          setMessages((prev) => updateLastAssistant(prev, acc, false));
        }
      } catch (err) {
        if (err instanceof api.ApiError && err.status === 401) {
          onSessionExpired();
          return;
        }
        const msg = err instanceof Error ? err.message : "Connection error.";
        setMessages((prev) =>
          updateLastAssistant(prev, acc || `Sorry — ${msg}`, false)
        );
      } finally {
        setSending(false);
      }

      if (finalText && voiceOnRef.current) void speak(finalText);
    },
    [onSessionExpired, player, speak]
  );

  const sendUser = useCallback(
    (content: string) => {
      const history = [...messages, { role: "user", content } as ChatMessage];
      setMessages(history);
      void runAssistant(history);
    },
    [messages, runAssistant]
  );

  // Kick off the conversation once (guarded against StrictMode double-invoke).
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    const kickoff: ChatMessage = { role: "user", content: KICKOFF, hidden: true };
    setMessages([kickoff]);
    void runAssistant([kickoff]);
  }, [runAssistant]);

  // Auto-scroll to the newest content.
  useEffect(() => {
    scrollAnchor.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // The latest finished assistant message may carry a submittable payload.
  const lastFinalAssistant = [...messages]
    .reverse()
    .find((m) => m.role === "assistant" && !m.streaming);
  const entries = lastFinalAssistant
    ? extractEntries(lastFinalAssistant.content)
    : null;

  const visible = messages.filter((m) => !m.hidden);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand-mini">
          <img src="/favicon.svg" alt="" width={26} height={26} />
          <span>OTL Timesheet</span>
        </div>
        <div className="topbar-actions">
          <button
            className={`chip ${viewTab === "chat" ? "on" : ""}`}
            onClick={() => setViewTab("chat")}
          >
            Chat
          </button>
          <button
            className={`chip ${viewTab === "history" ? "on" : ""}`}
            onClick={() => setViewTab("history")}
          >
            History
          </button>
          <button
            className={`chip ${voiceOn ? "on" : ""}`}
            onClick={() => setVoiceOn((v) => !v)}
            title="Toggle spoken replies"
            aria-pressed={voiceOn}
          >
            <SpeakerIcon size={16} />
            <span>{voiceOn ? "Voice on" : "Voice off"}</span>
          </button>
          <span className="user muted" title={username}>
            {username}
          </span>
          <button className="ghost" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>

      <main className="transcript">
        {viewTab === "history" ? (
          <TimecardHistory onSessionExpired={onSessionExpired} />
        ) : (
          <>
            {visible.map((m, i) => (
              <MessageBubble key={i} message={m} onSpeak={speak} />
            ))}

            {entries && (
              <ReviewPanel entries={entries} onSessionExpired={onSessionExpired} />
            )}

            <div ref={scrollAnchor} />
          </>
        )}
      </main>

      <footer className="dock">
        <Composer disabled={sending || viewTab === "history"} onSend={sendUser} />
        <p className="hint muted small">
          The assistant collects employee, project, work order, task and hours,
          then submits to OTL. Say “submit” when you’re done.
        </p>
      </footer>
    </div>
  );
}
