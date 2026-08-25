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
  const speak = useCallback(
    async (text: string): Promise<boolean> => {
      const clean = stripEntriesBlock(text);
      if (!clean) return false;
      try {
        const blob = await api.tts(clean);
        const result = await player.play(blob);
        return typeof result === 'boolean' ? result : result.success;
      } catch {
        return false;
      }
    },
    [player]
  );
  const sendUserRef = useRef<((content: string) => void) | null>(null);
  const runAssistantRef = useRef<((history: ChatMessage[]) => Promise<void>) | null>(null);
  const sendUser = useCallback(
    (content: string) => {
      if (mic.isListening()) {
        mic.stop(true);
      }
      player.stop(); 
      const historyForApi = [...messagesRef.current, { role: "user", content } as ChatMessage];
      setMessages(historyForApi);
      setTimeout(() => runAssistantRef.current?.(historyForApi), 0);
    },
    [mic, player]
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
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "", streaming: true },
      ]);
      let acc = "";
      let finalText = "";
      let unvoicedAcc = "";
      let isPlaying = false;
      const sentenceQueue: string[] = [];
      const MAX_QUEUE_SIZE = 50; 
      let queuePaused = false;
      const processQueue = async () => {
        if (isPlaying || sentenceQueue.length === 0) return;
        isPlaying = true;
        while (sentenceQueue.length > 0) {
          const sentence = sentenceQueue.shift()!;
          const finished = await speak(sentence);
          if (!finished) {
            sentenceQueue.length = 0;
            break;
          }
        }
        isPlaying = false;
        if (queuePaused && sentenceQueue.length < MAX_QUEUE_SIZE / 2) {
          queuePaused = false;
        }
      };
      try {
        await api.chatStream(history, (ev) => {
          if (ev.delta) {
            acc += ev.delta;
            setMessages((prev) => updateLastAssistant(prev, acc, true));
            unvoicedAcc += ev.delta;
            const match = unvoicedAcc.match(/^(.*?(?<!\b\d)(?<!\b(?:Mr|Mrs|Dr|WO|Proj|No|vs))[.?!])\s+(.*)$/is);
            if (match && voiceOnRef.current) {
               const pushToQueue = async () => {
                 while (sentenceQueue.length >= MAX_QUEUE_SIZE) {
                   queuePaused = true;
                   await new Promise((resolve) => setTimeout(resolve, 50));
                 }
                 sentenceQueue.push(match[1]);
                 processQueue();
               };
               pushToQueue();
               unvoicedAcc = match[2];
            }
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
          if (!mic.isListening()) {
             await playMicStart();
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
    },
    [onSessionExpired, player, speak, mic]
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
  const lastAssistant = [...messages]
    .reverse()
    .find((m) => m.role === "assistant");
  const entries = lastAssistant
    ? extractEntries(lastAssistant.content)
    : null;
  const shouldAutoSubmit = lastAssistant
    ? (!lastAssistant.streaming && 
       (lastAssistant.content.includes("```json") || lastAssistant.content.includes("Submitting to OTL now.")))
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
