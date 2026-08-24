import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { extractEntries, stripEntriesBlock } from "../lib/entries";
import { playMicStart, playMicStop } from "../lib/audio";
import { useAudioPlayer, useSpeechInput } from "../lib/voice";
import type { ChatMessage } from "../types";
import Composer from "./Composer";
import MessageBubble from "./MessageBubble";
import ReviewPanel from "./ReviewPanel";
import TimecardHistory from "./TimecardHistory";
import ProjectAssignments from "./ProjectAssignments";
import { SpeakerIcon } from "./icons";

const KICKOFF = "Please begin the session now.";

import { updateLastAssistant } from "../lib/chat";

/**
 * Properties for the ChatView component.
 */
export interface ChatViewProps {
  /** The username of the authenticated employee. */
  username: string;
  /** Callback fired when the user intentionally logs out. */
  onLogout: () => void;
  /** Callback fired when an API call indicates the session has expired. */
  onSessionExpired: () => void;
}

/**
 * The main chat interface orchestrating the voice interaction, SSE streaming, 
 * and timecard review presentation.
 * 
 * @param props - Component properties.
 */
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
  const [viewTab, setViewTab] = useState<"chat" | "history" | "projects">("chat");

  const player = useAudioPlayer();
  const mic = useSpeechInput();
  
  const voiceOnRef = useRef(voiceOn);
  useEffect(() => {
    voiceOnRef.current = voiceOn;
  }, [voiceOn]);
  
  const didInit = useRef(false);
  const scrollAnchor = useRef<HTMLDivElement | null>(null);

  const speak = useCallback(
    async (text: string): Promise<boolean> => {
      const clean = stripEntriesBlock(text);
      /* v8 ignore next */
      if (!clean) return false;
      try {
        const blob = await api.tts(clean);
        return await player.play(blob);
      } catch {
        /* TTS is best-effort; ignore failures */
        return false;
      }
    },
    [player]
  );

  const sendUserRef = useRef<((content: string) => void) | null>(null);

  // We define runAssistant first without depending on sendUser, breaking the cycle.
  // Actually, wait, let's keep runAssistant Ref instead.
  const runAssistantRef = useRef<((history: ChatMessage[]) => Promise<void>) | null>(null);

  const sendUser = useCallback(
    (content: string) => {
      // 1. If mic is open, STOP it explicitly
      // This prevents the onend handler from firing and re-submitting the text we are manually sending now.
      if (mic.isListening()) {
        mic.stop(true);
      }
      player.stop(); // Barge-in: stop TTS if user types or clicks send
      const historyForApi = [...messages, { role: "user", content } as ChatMessage];
      setMessages(historyForApi);
      setTimeout(() => runAssistantRef.current?.(historyForApi), 0);
    },
    [mic, player, messages]
  );

  useEffect(() => {
    sendUserRef.current = sendUser;
  }, [sendUser]);

  useEffect(() => {
    const onBargeIn = () => player.stop();
    window.addEventListener("otl:barge-in", onBargeIn);
    return () => window.removeEventListener("otl:barge-in", onBargeIn);
  }, [player]);

  const runAssistant = useCallback(
    async (history: ChatMessage[]) => {
      setSending(true);
      player.stop();
      // Leave mic open for barge-in if already listening, otherwise stop it
      // Actually, we should stop mic, then start it when bot starts speaking.
      mic.stop();
      
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "", streaming: true },
      ]);

      let acc = "";
      let finalText = "";
      let unvoicedAcc = "";
      
      let isPlaying = false;
      const sentenceQueue: string[] = [];
      const processQueue = async () => {
        if (isPlaying || sentenceQueue.length === 0) return;
        isPlaying = true;
        while (sentenceQueue.length > 0) {
          const sentence = sentenceQueue.shift()!;
          const finished = await speak(sentence);
          if (!finished) {
            // Barge-in or stopped! Clear queue
            sentenceQueue.length = 0;
            break;
          }
        }
        isPlaying = false;
      };

      try {
        await api.chatStream(history, (ev) => {
          if (ev.delta) {
            acc += ev.delta;
            setMessages((prev) => updateLastAssistant(prev, acc, true));
            
            // TTS Streaming Chunking: Avoid splitting on decimals (7.5, 1.0) or short abbreviations (Mr., WO., No., Dr.)
            unvoicedAcc += ev.delta;
            const match = unvoicedAcc.match(/^(.*?(?<!\b\d)(?<!\b(?:Mr|Mrs|Dr|WO|Proj|No|vs))[.?!])\s+(.*)$/is);
            if (match && voiceOnRef.current) {
               sentenceQueue.push(match[1]);
               unvoicedAcc = match[2];
               processQueue();
            }
          /* v8 ignore next 4 */
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
      // Play remaining TTS
      if (unvoicedAcc.trim() && voiceOnRef.current) {
         sentenceQueue.push(unvoicedAcc.trim());
         processQueue();
      }
      
      while (isPlaying || sentenceQueue.length > 0) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }

      const isFarewell = finalText.toLowerCase().includes("goodbye");

      if (finalText && voiceOnRef.current) {
        if (!isFarewell && mic.supported) {
          // Keep mic open, we already started it. If it stopped, restart.
          if (!mic.isListening()) {
             await playMicStart();
             // Wait briefly to prevent the mic from picking up the chime echo as "random words"
             await new Promise(resolve => setTimeout(resolve, 300));
             mic.start((spoken) => {
               playMicStop();
               sendUserRef.current?.(spoken);
             }, undefined, () => {
               const evt = new CustomEvent("otl:barge-in");
               window.dispatchEvent(evt);
             });
          }
        } else if (isFarewell) {
          mic.stop();
        }
      }
      
      // Auto-submit is handled by ReviewPanel component now.
    },
    [onSessionExpired, player, speak, mic]
  );

  useEffect(() => {
    runAssistantRef.current = runAssistant;
  }, [runAssistant]);

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

  // The latest assistant message may carry a submittable payload (even while streaming)
  const lastAssistant = [...messages]
    .reverse()
    .find((m) => m.role === "assistant");
  const entries = lastAssistant
    ? extractEntries(lastAssistant.content)
    : null;
    
  // Check if we reached final submission state
  const shouldAutoSubmit = lastAssistant
    ? (lastAssistant.content.includes("```json") || lastAssistant.content.includes("Submitting to OTL now."))
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
          >
            Assistant
          </button>
          <button
            className={`nav-item ${viewTab === "projects" ? "active" : ""}`}
            onClick={() => setViewTab("projects")}
          >
            Projects
          </button>
          <button
            className={`nav-item ${viewTab === "history" ? "active" : ""}`}
            onClick={() => setViewTab("history")}
          >
            History
          </button>
        </nav>

        <div className="sidebar-footer">
          <div className="nav-group-title">Settings</div>
          <button
            className={`nav-item ${voiceOn ? "active" : ""}`}
            onClick={() => setVoiceOn((v) => !v)}
            title="Toggle spoken replies"
            aria-pressed={voiceOn}
          >
            <SpeakerIcon size={16} />
            <span>{voiceOn ? "Voice On" : "Voice Off"}</span>
          </button>
          
          <div className="user-profile">
            <div className="avatar">{username.charAt(0).toUpperCase()}</div>
            <div className="user-info">
              <span className="user-name" title={username}>{username}</span>
              <button className="sign-out-btn" onClick={onLogout}>Sign out</button>
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
                  <MessageBubble key={i} message={m} />
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
                  disabled={sending || viewTab !== "chat"} 
                  onSend={sendUser} 
                  supported={mic.supported}
                  listening={mic.listening}
                  onStartMic={mic.start}
                  onStopMic={mic.stop}
                  errorMsg={mic.errorMsg}
                />
                <p className="hint muted small">
                  The assistant collects employee, project, work order, task and hours,
                  then submits to OTL. Say “submit” when you’re done.
                </p>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
