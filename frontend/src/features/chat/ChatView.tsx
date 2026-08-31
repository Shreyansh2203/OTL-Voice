import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../../api/client";
import { updateLastAssistant } from "../../lib/chat";
import { extractEntries, stripEntriesBlock } from "../../lib/entries";
import { useAudioPlayer, useSpeechInput } from "../../lib/voice";
import type { ChatMessage } from "../../types";
import { SpeakerIcon } from "../../components/ui/icons";
import { useGeminiLive } from "../../lib/useGeminiLive";
import { ProjectAssignments, ReviewPanel, TimecardHistory } from "../timesheets";
import Composer from "./Composer";
import LiveVoiceModal from "./LiveVoiceModal";
import MessageBubble from "./MessageBubble";

const KICKOFF = "Please begin the session now.";

export interface ChatViewProps {
  username: string;
  onLogout: () => void;
  onSessionExpired: () => void;
}
export default function ChatView({
  username,
  onLogout,
  onSessionExpired,
}: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [voiceOn, setVoiceOn] = useState(() => {
    const saved = localStorage.getItem("otl_voice_on");
    return saved !== null ? saved === "true" : true;
  });
  useEffect(() => {
    localStorage.setItem("otl_voice_on", String(voiceOn));
  }, [voiceOn]);
  const [viewTab, setViewTab] = useState<"chat" | "history" | "projects">("chat");
  const player = useAudioPlayer();
  const mic = useSpeechInput();
  const liveVoice = useGeminiLive();
  const voiceOnRef = useRef(voiceOn);
  useEffect(() => {
    voiceOnRef.current = voiceOn;
  }, [voiceOn]);
  const messagesRef = useRef<ChatMessage[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);
  const didInit = useRef(false);
  const scrollAnchor = useRef<HTMLDivElement | null>(null);

  // Conversational state refs
  const abortControllerRef = useRef<AbortController | null>(null);
  const interruptTokenRef = useRef<number>(0);
  const isPlayingRef = useRef<boolean>(false);
  const [voiceState, setVoiceState] = useState<"idle" | "listening" | "thinking" | "speaking">("idle");

  const handleBargeIn = useCallback(() => {
    // 1. Abort active assistant stream if any
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    // 2. Invalidate current turn token
    interruptTokenRef.current += 1;
    isPlayingRef.current = false;
    // 3. Stop audio playback immediately
    player.stop();
    setSending(false);
    // 5. Finalize any streaming assistant bubble
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === "assistant" && last.streaming) {
        return updateLastAssistant(prev, last.content, false);
      }
      return prev;
    });
    setVoiceState(mic.listening ? "listening" : "idle");
  }, [player, mic.listening]);

  const sendUserRef = useRef<((content: string, isVoice?: boolean) => void) | null>(null);
  const runAssistantRef = useRef<((history: ChatMessage[]) => Promise<void>) | null>(null);
  const composerMicTriggerRef = useRef<(() => void) | null>(null);
  const wasLastInputVoiceRef = useRef<boolean>(true);

  const sendUser = useCallback(
    (content: string, isVoice?: boolean) => {
      handleBargeIn();
      wasLastInputVoiceRef.current = !!isVoice;
      const cleanPrev = messagesRef.current.filter(
        (m) => m.content && m.content.trim().length > 0 && !m.content.startsWith("Sorry —")
      );
      const historyForApi = [...cleanPrev, { role: "user", content } as ChatMessage];
      setMessages(historyForApi);
      setTimeout(() => runAssistantRef.current?.(historyForApi), 0);
    },
    [handleBargeIn]
  );

  useEffect(() => {
    sendUserRef.current = sendUser;
  }, [sendUser]);

  useEffect(() => {
    const onBargeIn = () => handleBargeIn();
    window.addEventListener("otl:barge-in", onBargeIn);
    return () => window.removeEventListener("otl:barge-in", onBargeIn);
  }, [handleBargeIn]);

  const runAssistant = useCallback(
    async (history: ChatMessage[]) => {
      const thisToken = ++interruptTokenRef.current;
      setSending(true);
      setVoiceState("thinking");
      player.stop();

      const controller = new AbortController();
      abortControllerRef.current = controller;

      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "", streaming: true },
      ]);

      let acc = "";
      let finalText = "";
      let unvoicedAcc = "";
      
      interface QueuedAudio {
        id: number;
        text: string;
        blobPromise: Promise<Blob | null>;
      }
      
      const audioQueue: QueuedAudio[] = [];
      let itemCounter = 0;

      const enqueueChunk = (sentenceText: string) => {
        const clean = stripEntriesBlock(sentenceText).trim();
        if (!clean) return;

        const itemId = ++itemCounter;
        const blobPromise = (async () => {
          try {
            const res = await api.tts(clean);
            return res || null;
          } catch (err) {
            console.warn("TTS synthesis error for chunk:", clean, err);
            return null;
          }
        })();

        audioQueue.push({ id: itemId, text: clean, blobPromise });
        void processAudioQueue();
      };

      const processAudioQueue = async () => {
        if (isPlayingRef.current || audioQueue.length === 0) return;
        isPlayingRef.current = true;

        while (audioQueue.length > 0 && interruptTokenRef.current === thisToken) {
          const item = audioQueue.shift()!;
          if (interruptTokenRef.current !== thisToken) break;

          try {
            const blob = await item.blobPromise;
            if (!blob || interruptTokenRef.current !== thisToken) continue;

            setVoiceState("speaking");
            const result = await player.play(blob);
            const success = !result || result.success !== false;

            if (!success || interruptTokenRef.current !== thisToken) {
              audioQueue.length = 0;
              break;
            }
          } catch {
            // continue with next chunk on playback error
          }
        }

        isPlayingRef.current = false;
      };

      const cleanHistory = history.filter(
        (m) => m.content && m.content.trim().length > 0 && !m.content.startsWith("Sorry —")
      );

      try {
        await api.chatStream(
          cleanHistory,
          (ev) => {
            if (interruptTokenRef.current !== thisToken) return;
            if (ev.delta) {
              acc += ev.delta;
              setMessages((prev) => updateLastAssistant(prev, acc, true));
              unvoicedAcc += ev.delta;

              while (voiceOnRef.current && interruptTokenRef.current === thisToken) {
                const match = unvoicedAcc.match(/^([\s\S]*?(?:[.?!](?=\s|$|\n)|\n+))([\s\S]*)$/);
                if (!match || !match[1].trim()) break;

                const sentence = match[1].trim();
                unvoicedAcc = match[2];
                enqueueChunk(sentence);
              }
            } else if (ev.error) {
              finalText = acc || `Sorry — ${ev.error}`;
              setMessages((prev) => updateLastAssistant(prev, finalText, false));
            } else if (ev.done) {
              finalText = acc;
              setMessages((prev) => updateLastAssistant(prev, acc, false));
            }
          },
          controller.signal
        );

        if (interruptTokenRef.current !== thisToken) return;

        if (!finalText) {
          finalText = acc;
          setMessages((prev) => updateLastAssistant(prev, acc, false));
        }
      } catch (err) {
        if (interruptTokenRef.current !== thisToken) return;
        if (err instanceof api.ApiError && err.status === 401) {
          onSessionExpired();
          return;
        }
        const msg = err instanceof Error ? err.message : "Connection error.";
        setMessages((prev) =>
          updateLastAssistant(prev, acc || `Sorry — ${msg}`, false)
        );
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
        setSending(false);
      }

      if (interruptTokenRef.current !== thisToken) return;

      if (unvoicedAcc.trim() && voiceOnRef.current) {
        enqueueChunk(unvoicedAcc.trim());
        unvoicedAcc = "";
      }

      while (
        (isPlayingRef.current || audioQueue.length > 0) &&
        interruptTokenRef.current === thisToken
      ) {
        await new Promise((resolve) => setTimeout(resolve, 50));
      }

      const isFarewell =
        finalText.toLowerCase().includes("goodbye") ||
        finalText.toLowerCase().includes("have a great day") ||
        finalText.toLowerCase().includes("all done");

      if (isFarewell) {
        mic.stop();
        setVoiceState("idle");
      } else if (mic.supported && wasLastInputVoiceRef.current) {
        // Alexa / Google Assistant Hands-Free Dialogue Loop
        await new Promise((resolve) => setTimeout(resolve, 300));
        if (interruptTokenRef.current === thisToken) {
          composerMicTriggerRef.current?.();
        }
      } else if (mic.listening) {
        setVoiceState("listening");
      } else {
        setVoiceState("idle");
      }
    },
    [onSessionExpired, player, mic]
  );

  useEffect(() => {
    runAssistantRef.current = runAssistant;
  }, [runAssistant]);

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    const kickoff: ChatMessage = { role: "user", content: KICKOFF, hidden: true };
    setMessages([kickoff]);
    void runAssistantRef.current?.([kickoff]);
  }, []);

  useEffect(() => {
    scrollAnchor.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const startMicSession = useCallback(
    async (
      onFinal: (spoken: string) => void,
      onInterim?: (spoken: string) => void,
      onSpeechStart?: () => void
    ) => {
      handleBargeIn();
      setVoiceState("listening");
      await mic.start(
        (spoken) => {
          if (spoken.trim()) {
            onFinal(spoken.trim());
          }
        },
        onInterim,
        () => {
          handleBargeIn();
          onSpeechStart?.();
        },
        true
      );
    },
    [handleBargeIn, mic]
  );

  const stopMicSession = useCallback(() => {
    mic.stop();
    setVoiceState("idle");
  }, [mic]);

  const lastAssistant = [...messages]
    .reverse()
    .find((m) => m.role === "assistant");
  const entries = lastAssistant
    ? extractEntries(lastAssistant.content)
    : null;
  const shouldAutoSubmit = lastAssistant
    ? (!lastAssistant.streaming && lastAssistant.content.includes("```json"))
    : false;
  const visible = messages.filter((m) => !m.hidden);

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="brand-logo">
            <img src="/favicon.svg" alt="" width={22} height={22} />
          </div>
          <span className="brand-title">OTL Timesheet</span>
        </div>
        <nav className="sidebar-nav">
          <div className="nav-group-title">Menu</div>
          <button
            className={`nav-item ${viewTab === "chat" ? "active" : ""}`}
            onClick={() => setViewTab("chat")}
            aria-label="Navigate to Assistant chat"
            aria-current={viewTab === "chat" ? "page" : undefined}
          >
            Assistant
          </button>
          <button
            className={`nav-item ${viewTab === "projects" ? "active" : ""}`}
            onClick={() => setViewTab("projects")}
            aria-label="Navigate to Project Assignments"
            aria-current={viewTab === "projects" ? "page" : undefined}
          >
            Projects
          </button>
          <button
            className={`nav-item ${viewTab === "history" ? "active" : ""}`}
            onClick={() => setViewTab("history")}
            aria-label="Navigate to Timecard History"
            aria-current={viewTab === "history" ? "page" : undefined}
          >
            History
          </button>
        </nav>
        <div className="sidebar-footer">
          <div className="nav-group-title">Settings</div>
          <button
            className={`nav-item ${voiceOn ? "active" : ""}`}
            onClick={() => setVoiceOn((v) => !v)}
            aria-label={voiceOn ? "Disable voice responses" : "Enable voice responses"}
            aria-pressed={voiceOn}
          >
            <SpeakerIcon size={16} />
            <span>{voiceOn ? "Voice On" : "Voice Off"}</span>
          </button>
          <div className="user-profile">
            <div className="avatar">{username.charAt(0).toUpperCase()}</div>
            <div className="user-info">
              <span className="user-name" title={username}>{username}</span>
              <button className="sign-out-btn" onClick={onLogout} aria-label="Sign out of your account">Sign out</button>
            </div>
          </div>
        </div>
      </aside>
      <main className="workspace">
        <header className="workspace-header">
          <h2>
            {viewTab === "chat" ? "Assistant" : 
             viewTab === "projects" ? "Project Assignments" : 
             "Timecard History"}
          </h2>
          {viewTab === "chat" && (
            <button
              type="button"
              className="btn-live-voice"
              onClick={() => liveVoice.startSession()}
              aria-label="Open Gemini Live multimodal voice session"
            >
              <span className="live-dot" />
              <span>Gemini Live Voice</span>
            </button>
          )}
        </header>
        {viewTab === "history" ? (
          <div className="workspace-content scroll-y">
            <div className="workspace-inner">
              <TimecardHistory onSessionExpired={onSessionExpired} />
            </div>
          </div>
        ) : viewTab === "projects" ? (
          <div className="workspace-content scroll-y">
            <div className="workspace-inner">
              <ProjectAssignments onSessionExpired={onSessionExpired} />
            </div>
          </div>
        ) : (
          <div className="workspace-content chat-layout">
            <div className="transcript scroll-y">
              <div className="transcript-inner">
                {visible.map((m, i) => (
                  <MessageBubble key={`${m.role}-${i}-${m.content.slice(0, 20)}`} message={m} />
                ))}
                {entries && (
                  <ReviewPanel 
                    entries={entries} 
                    onSessionExpired={onSessionExpired}
                    autoSubmit={shouldAutoSubmit}
                  />
                )}
                <div ref={scrollAnchor} className="scroll-anchor" />
              </div>
            </div>
            <div className="dock">
              <div className="dock-inner">
                <Composer 
                  disabled={sending && !mic.listening || viewTab !== "chat"} 
                  onSend={sendUser} 
                  supported={mic.supported}
                  listening={mic.listening}
                  onStartMic={startMicSession}
                  onStopMic={stopMicSession}
                  errorMsg={mic.errorMsg}
                  voiceState={voiceState}
                  onRegisterTrigger={(trigger) => {
                    composerMicTriggerRef.current = trigger;
                  }}
                />
                <p className="hint muted small">
                  The assistant collects employee, project, work order, task and hours,
                  then submits to OTL. Speak naturally — tap the mic to start or stop continuous voice.
                </p>
              </div>
            </div>
          </div>
        )}
        <LiveVoiceModal
          isOpen={liveVoice.isActive}
          liveState={liveVoice.liveState}
          errorMsg={liveVoice.errorMsg}
          transcript={liveVoice.transcript}
          toolCalls={liveVoice.toolCalls}
          isMuted={liveVoice.isMuted}
          onToggleMute={liveVoice.toggleMute}
          onClose={liveVoice.stopSession}
        />
      </main>
    </div>
  );
}
