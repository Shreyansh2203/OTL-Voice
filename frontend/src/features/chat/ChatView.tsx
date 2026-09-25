import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import * as api from '../../api/client';
import { updateLastAssistant } from '../../lib/chat';
import {
  extractEntries,
  looksLikeTimesheetPayload,
  stripEntriesBlock,
  todayInAppTimezone,
} from '../../lib/entries';
import { playThinkingCue } from '../../lib/audio';
import { useAudioPlayer, useSpeechInput } from '../../lib/voice';
import type { ChatMessage, TimecardEntry } from '../../types';
import {
  ProjectAssignments,
  ReviewPanel,
  TimecardHistory,
} from '../timesheets';
import ChatShell, { type ChatTab, type OracleStatus } from './ChatShell';
import Composer from './Composer';
import MessageBubble from './MessageBubble';

const KICKOFF = 'Please begin the session now.';
const MAX_CHAT_MESSAGES = 50;
const MAX_PERSISTED_CHARS = 64_000;
const MAX_DRAFT_CHARS = 10_000;
const CONVERSATION_STORAGE_KEY = 'otl_conversation_v1';

interface StoredConversation {
  owner: string;
  messages: ChatMessage[];
  draft: string;
  error?: string;
}

function safeStoredMessages(value: unknown): ChatMessage[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(
      (message): message is Record<string, unknown> =>
        !!message &&
        typeof message === 'object' &&
        ((message as { role?: unknown }).role === 'user' ||
          (message as { role?: unknown }).role === 'assistant') &&
        typeof (message as { content?: unknown }).content === 'string'
    )
    .slice(-MAX_CHAT_MESSAGES)
    .map((message) => ({
      role: message.role as 'user' | 'assistant',
      content: String(message.content).slice(0, 10_000),
      hidden: message.hidden === true,
      streaming: false,
      thinking: false,
    }));
}

function loadConversation(owner: string): StoredConversation {
  const empty = { owner, messages: [], draft: '' };
  try {
    const raw = localStorage.getItem(CONVERSATION_STORAGE_KEY);
    if (!raw) return empty;
    const parsed: unknown = JSON.parse(raw);
    if (
      !parsed ||
      typeof parsed !== 'object' ||
      (parsed as { owner?: unknown }).owner !== owner
    ) {
      return empty;
    }
    const record = parsed as Record<string, unknown>;
    return {
      owner,
      messages: safeStoredMessages(record.messages),
      draft:
        typeof record.draft === 'string'
          ? record.draft.slice(0, MAX_DRAFT_CHARS)
          : '',
    };
  } catch {
    return {
      ...empty,
      error:
        'The saved conversation could not be read. Your current session is still available.',
    };
  }
}

function storeConversation(
  owner: string,
  messages: ChatMessage[],
  draft: string
): string | null {
  try {
    const cappedMessages = safeStoredMessages(messages);
    let stored: StoredConversation = {
      owner,
      messages: cappedMessages,
      draft: draft.slice(0, MAX_DRAFT_CHARS),
    };
    while (
      JSON.stringify(stored).length > MAX_PERSISTED_CHARS &&
      stored.messages.length > 1
    ) {
      stored = { ...stored, messages: stored.messages.slice(1) };
    }
    localStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(stored));
    return null;
  } catch {
    return 'This browser could not save the current draft and transcript. Copy important text before leaving.';
  }
}

function clearStoredConversation(): void {
  try {
    localStorage.removeItem(CONVERSATION_STORAGE_KEY);
  } catch {
    return;
  }
}

function createManualEntry(
  employeeNumber?: string,
  employeeName?: string
): TimecardEntry {
  return {
    employeeNumber: employeeNumber?.trim() || undefined,
    employeeName: employeeName?.trim() || undefined,
    date: todayInAppTimezone(),
    currencyCode: 'USD',
  };
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function loadVoicePreference(): boolean {
  try {
    const saved = localStorage.getItem('otl_voice_on');
    return saved === null ? true : saved === 'true';
  } catch {
    return true;
  }
}

export interface ChatViewProps {
  username: string;
  employeeNumber?: string;
  onLogout: () => Promise<void> | void;
  onSessionExpired: () => void;
}

export default function ChatView({
  username,
  employeeNumber,
  onLogout,
  onSessionExpired,
}: ChatViewProps) {
  const owner = employeeNumber || username;
  const [restored] = useState(() => loadConversation(owner));
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    restored.messages.length > 0
      ? restored.messages
      : [{ role: 'user', content: KICKOFF, hidden: true }]
  );
  const [draft, setDraft] = useState(restored.draft);
  const [storageError, setStorageError] = useState<string | null>(
    restored.error || null
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const persistenceError = actionError || storageError;
  const hasRestoredMessages = restored.messages.some(
    (message) => !message.hidden
  );
  const [restoredNotice, setRestoredNotice] = useState(
    hasRestoredMessages || restored.draft.length > 0
  );
  const [sending, setSending] = useState(false);
  const [voiceOn, setVoiceOn] = useState(loadVoicePreference);
  const [viewTab, setViewTab] = useState<ChatTab>('chat');
  const [oracleStatus, setOracleStatus] = useState<OracleStatus>('checking');
  const [voiceState, setVoiceState] = useState<
    'idle' | 'listening' | 'thinking' | 'speaking'
  >('idle');
  const [voiceNotice, setVoiceNotice] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [reviewEntries, setReviewEntries] = useState<TimecardEntry[] | null>(
    null
  );
  const [manualEntries, setManualEntries] = useState<TimecardEntry[]>(() => [
    createManualEntry(employeeNumber, username),
  ]);
  const [omittedMessages, setOmittedMessages] = useState(0);
  const player = useAudioPlayer();
  const mic = useSpeechInput();
  const messagesRef = useRef<ChatMessage[]>(messages);
  const draftRef = useRef(draft);
  const voiceOnRef = useRef(voiceOn);
  const playerRef = useRef(player);
  const micRef = useRef(mic);
  const onSessionExpiredRef = useRef(onSessionExpired);
  const didInit = useRef(false);
  const scrollAnchor = useRef<HTMLDivElement | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const interruptTokenRef = useRef(0);
  const sendGenerationRef = useRef(0);
  const isPlayingRef = useRef(false);
  const ttsControllersRef = useRef(new Set<AbortController>());
  const sendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const micRestartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runAssistantRef = useRef<
    ((history: ChatMessage[]) => Promise<void>) | null
  >(null);
  const conversationDisabledRef = useRef(false);
  const composerMicTriggerRef = useRef<(() => void) | null>(null);
  const wasLastInputVoiceRef = useRef(false);

  useEffect(() => {
    messagesRef.current = messages;
    draftRef.current = draft;
    if (conversationDisabledRef.current) return;
    const error = storeConversation(owner, messages, draft);
    const timer = window.setTimeout(() => {
      setStorageError(error);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [draft, messages, owner]);

  useEffect(() => {
    voiceOnRef.current = voiceOn;
  }, [voiceOn]);

  useEffect(() => {
    playerRef.current = player;
    micRef.current = mic;
    onSessionExpiredRef.current = onSessionExpired;
  }, [mic, onSessionExpired, player]);

  const abortTts = useCallback(() => {
    ttsControllersRef.current.forEach((controller) => controller.abort());
    ttsControllersRef.current.clear();
  }, []);

  const cancelResources = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    interruptTokenRef.current += 1;
    sendGenerationRef.current += 1;
    isPlayingRef.current = false;
    abortTts();
    playerRef.current.stop();
    micRef.current.stop(true);
    if (sendTimerRef.current) clearTimeout(sendTimerRef.current);
    if (micRestartTimerRef.current) clearTimeout(micRestartTimerRef.current);
    sendTimerRef.current = null;
    micRestartTimerRef.current = null;
    composerMicTriggerRef.current = null;
  }, [abortTts]);

  const stopResources = useCallback(() => {
    cancelResources();
    setSending(false);
    setVoiceState('idle');
  }, [cancelResources]);

  const handleBargeIn = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    interruptTokenRef.current += 1;
    sendGenerationRef.current += 1;
    isPlayingRef.current = false;
    abortTts();
    playerRef.current.stop();
    setSending(false);
    if (micRestartTimerRef.current) clearTimeout(micRestartTimerRef.current);
    micRestartTimerRef.current = null;
    setMessages((previous) => {
      const last = previous[previous.length - 1];
      if (last?.role === 'assistant' && last.streaming) {
        return updateLastAssistant(previous, last.content, false);
      }
      return previous;
    });
    setVoiceState(micRef.current.listening ? 'listening' : 'idle');
  }, [abortTts]);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getHealthOtl(controller.signal)
      .then(() => setOracleStatus('online'))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof api.ApiError && error.status === 401) {
          conversationDisabledRef.current = true;
          clearStoredConversation();
          stopResources();
          onSessionExpiredRef.current();
          return;
        }
        setOracleStatus('offline');
      });
    return () => controller.abort();
  }, [stopResources]);

  const sendUser = useCallback(
    (content: string, isVoice?: boolean) => {
      const trimmed = content.trim().slice(0, MAX_DRAFT_CHARS);
      if (!trimmed) return;
      handleBargeIn();
      const generation = ++sendGenerationRef.current;
      wasLastInputVoiceRef.current = !!isVoice;
      const cleanPrevious = messagesRef.current.filter(
        (message) =>
          message.content.trim().length > 0 &&
          !message.content.startsWith('Sorry —')
      );
      const completeHistory = [
        ...cleanPrevious,
        { role: 'user', content: trimmed } as ChatMessage,
      ];
      const outboundHistory = completeHistory.slice(-MAX_CHAT_MESSAGES);
      setOmittedMessages(
        Math.max(0, completeHistory.length - outboundHistory.length)
      );
      setReviewEntries(null);
      setManualOpen(false);
      setMessages(completeHistory);
      sendTimerRef.current = setTimeout(() => {
        if (generation === sendGenerationRef.current) {
          void runAssistantRef.current?.(outboundHistory);
        }
      }, 0);
    },
    [handleBargeIn]
  );

  useEffect(() => {
    const onBargeIn = () => handleBargeIn();
    window.addEventListener('otl:barge-in', onBargeIn);
    return () => window.removeEventListener('otl:barge-in', onBargeIn);
  }, [handleBargeIn]);

  const runAssistant = useCallback(async (history: ChatMessage[]) => {
    const thisToken = ++interruptTokenRef.current;
    const turnIsVoice = wasLastInputVoiceRef.current;
    setSending(true);
    setVoiceState('thinking');
    setVoiceNotice(null);
    if (turnIsVoice) void playThinkingCue();
    playerRef.current.stop();

    const controller = new AbortController();
    abortControllerRef.current = controller;
    setMessages((previous) => [
      ...previous,
      { role: 'assistant', content: '', streaming: true },
    ]);

    let accumulated = '';
    let finalText = '';
    let unvoiced = '';
    let itemCounter = 0;
    const audioQueue: Array<{
      id: number;
      blobPromise: Promise<Blob | null>;
    }> = [];

    const processAudioQueue = async () => {
      if (interruptTokenRef.current !== thisToken) {
        audioQueue.length = 0;
        return;
      }
      if (isPlayingRef.current || audioQueue.length === 0) return;
      isPlayingRef.current = true;
      while (audioQueue.length > 0 && interruptTokenRef.current === thisToken) {
        const item = audioQueue.shift();
        if (!item) break;
        try {
          const blob = await item.blobPromise;
          if (!blob || interruptTokenRef.current !== thisToken) continue;
          setVoiceState('speaking');
          const playback = await playerRef.current.play(blob);
          if (!playback || playback.success === false) {
            if (interruptTokenRef.current === thisToken) {
              setVoiceNotice(
                'Voice playback was interrupted. The text response remains available.'
              );
            }
            audioQueue.length = 0;
            break;
          }
        } catch (error: unknown) {
          if (interruptTokenRef.current === thisToken) {
            setVoiceNotice(
              errorText(
                error,
                'Voice playback failed. The text response remains available.'
              )
            );
          }
        }
      }
      if (interruptTokenRef.current === thisToken) {
        isPlayingRef.current = false;
      }
    };

    const enqueueChunk = (chunk: string) => {
      const clean = stripEntriesBlock(chunk).trim();
      if (!clean) return;
      const ttsController = new AbortController();
      ttsControllersRef.current.add(ttsController);
      const id = ++itemCounter;
      const blobPromise = api
        .tts(clean, 1, ttsController.signal)
        .catch((error: unknown) => {
          if (interruptTokenRef.current === thisToken) {
            setVoiceNotice(
              errorText(
                error,
                'Voice synthesis failed. The text response remains available.'
              )
            );
          }
          return null;
        })
        .finally(() => ttsControllersRef.current.delete(ttsController));
      audioQueue.push({ id, blobPromise });
      void processAudioQueue();
    };

    try {
      await api.chatStream(
        history.slice(-MAX_CHAT_MESSAGES),
        (event) => {
          if (interruptTokenRef.current !== thisToken) return;
          if (event.delta) {
            accumulated += event.delta;
            setMessages((previous) =>
              updateLastAssistant(previous, accumulated, true)
            );
            unvoiced += event.delta;
            while (
              voiceOnRef.current &&
              interruptTokenRef.current === thisToken
            ) {
              const match = unvoiced.match(
                /^([\s\S]*?(?:[.?!](?=\s|$|\n)|\n+))([\s\S]*)$/
              );
              if (!match?.[1]?.trim()) break;
              enqueueChunk(match[1].trim());
              unvoiced = match[2];
            }
          } else if (event.error) {
            finalText = accumulated
              ? `${accumulated}\n\nError: ${event.error}`
              : `Sorry — ${event.error}`;
            setMessages((previous) =>
              updateLastAssistant(previous, finalText, false)
            );
          } else if (event.done) {
            finalText = accumulated;
            setMessages((previous) =>
              updateLastAssistant(previous, accumulated, false)
            );
          }
        },
        controller.signal
      );
      if (interruptTokenRef.current !== thisToken) return;
      if (!finalText) {
        finalText = accumulated;
        setMessages((previous) =>
          updateLastAssistant(previous, accumulated, false)
        );
      }
    } catch (error: unknown) {
      if (interruptTokenRef.current !== thisToken) return;
      if (error instanceof api.ApiError && error.status === 401) {
        onSessionExpiredRef.current();
        return;
      }
      const message = errorText(error, 'Connection error.');
      setMessages((previous) =>
        updateLastAssistant(
          previous,
          accumulated || `Sorry — ${message}`,
          false
        )
      );
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        setSending(false);
      }
    }

    if (interruptTokenRef.current !== thisToken) return;
    const extracted = extractEntries(finalText);
    if (extracted?.length) {
      setReviewEntries(extracted);
      setManualOpen(false);
    } else if (looksLikeTimesheetPayload(finalText)) {
      setReviewEntries(null);
      setManualOpen(true);
    }
    if (unvoiced.trim() && voiceOnRef.current) enqueueChunk(unvoiced.trim());
    while (
      (isPlayingRef.current || audioQueue.length > 0) &&
      interruptTokenRef.current === thisToken
    ) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    if (interruptTokenRef.current !== thisToken) return;

    const normalizedFinal = finalText.toLowerCase();
    if (
      normalizedFinal.includes('goodbye') ||
      normalizedFinal.includes('have a great day')
    ) {
      micRef.current.stop();
      setVoiceState('idle');
    } else if (voiceOnRef.current && micRef.current.supported && turnIsVoice) {
      micRestartTimerRef.current = setTimeout(() => {
        if (interruptTokenRef.current === thisToken) {
          composerMicTriggerRef.current?.();
        }
      }, 300);
    } else {
      setVoiceState(micRef.current.listening ? 'listening' : 'idle');
    }
  }, []);

  useEffect(() => {
    runAssistantRef.current = runAssistant;
  }, [runAssistant]);

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    if (!hasRestoredMessages) {
      const kickoff: ChatMessage = {
        role: 'user',
        content: KICKOFF,
        hidden: true,
      };
      void runAssistantRef.current?.([kickoff]);
    }
    return () => {
      didInit.current = false;
      cancelResources();
    };
  }, [cancelResources, hasRestoredMessages]);

  useEffect(() => {
    const anchor = scrollAnchor.current;
    if (anchor && typeof anchor.scrollIntoView === 'function') {
      anchor.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [messages]);

  useEffect(() => {
    const onPageHide = () => stopResources();
    window.addEventListener('pagehide', onPageHide);
    return () => window.removeEventListener('pagehide', onPageHide);
  }, [stopResources]);

  const startMicSession = useCallback(
    async (
      onFinal: (spoken: string) => void,
      onInterim?: (spoken: string) => void,
      onSpeechStart?: () => void
    ) => {
      handleBargeIn();
      setVoiceState('listening');
      await micRef.current.start(
        (spoken) => {
          if (spoken.trim()) onFinal(spoken.trim());
        },
        onInterim,
        () => {
          handleBargeIn();
          onSpeechStart?.();
        },
        true
      );
    },
    [handleBargeIn]
  );

  const stopMicSession = useCallback(() => {
    micRef.current.stop(true);
    setVoiceState('idle');
  }, []);

  const endSession = useCallback(
    async (expired: boolean) => {
      stopResources();
      if (expired) {
        conversationDisabledRef.current = true;
        clearStoredConversation();
        onSessionExpiredRef.current();
        return;
      }
      try {
        await onLogout();
        conversationDisabledRef.current = true;
        clearStoredConversation();
        setActionError(null);
        setStorageError(null);
      } catch {
        setActionError(
          'Sign out could not be confirmed. Your session remains active; try again.'
        );
      }
    },
    [onLogout, stopResources]
  );

  const handleSessionExpired = useCallback(
    () => void endSession(true),
    [endSession]
  );

  const newConversation = useCallback(() => {
    conversationDisabledRef.current = false;
    stopResources();
    clearStoredConversation();
    setActionError(null);
    setDraft('');
    setReviewEntries(null);
    setManualEntries([createManualEntry(employeeNumber, username)]);
    setManualOpen(false);
    setOmittedMessages(0);
    setRestoredNotice(false);
    setVoiceNotice(null);
    wasLastInputVoiceRef.current = false;
    const kickoff: ChatMessage = {
      role: 'user',
      content: KICKOFF,
      hidden: true,
    };
    setMessages([kickoff]);
    void runAssistantRef.current?.([kickoff]);
  }, [employeeNumber, stopResources, username]);

  const visible = messages.filter((message) => !message.hidden);
  const displayedEntries = manualOpen ? manualEntries : reviewEntries;
  const fallbackNotice =
    manualOpen && !reviewEntries
      ? 'The assistant did not return a valid timesheet payload. Complete the form manually; server validation still applies.'
      : null;

  const toggleVoice = () => {
    const nextVoiceOn = !voiceOn;
    if (voiceOn) {
      handleBargeIn();
      micRef.current.stop(true);
    }
    voiceOnRef.current = nextVoiceOn;
    setVoiceOn(nextVoiceOn);
    try {
      localStorage.setItem('otl_voice_on', String(nextVoiceOn));
      setActionError(null);
    } catch {
      setActionError('Voice preference could not be saved in this browser.');
    }
  };

  return (
    <ChatShell
      username={username}
      viewTab={viewTab}
      onViewTabChange={setViewTab}
      voiceOn={voiceOn}
      onVoiceToggle={toggleVoice}
      onLogout={() => void endSession(false)}
      onNewConversation={newConversation}
      oracleStatus={oracleStatus}
    >
      {viewTab === 'history' ? (
        <div className="workspace-content scroll-y">
          <div className="workspace-inner">
            <TimecardHistory onSessionExpired={handleSessionExpired} />
          </div>
        </div>
      ) : viewTab === 'projects' ? (
        <div className="workspace-content scroll-y">
          <div className="workspace-inner">
            <ProjectAssignments onSessionExpired={handleSessionExpired} />
          </div>
        </div>
      ) : (
        <div
          className="workspace-content chat-layout"
          style={{ position: 'relative', zIndex: 1 }}
        >
          <div
            className="transcript scroll-y"
            style={{ background: 'transparent' }}
          >
            <div className="transcript-inner">
              {restoredNotice && (
                <div className="conversation-notice" role="status">
                  Restored your saved draft and transcript. The microphone was
                  not restarted automatically.
                </div>
              )}
              {persistenceError && (
                <div className="error" role="alert">
                  {persistenceError}
                </div>
              )}
              {omittedMessages > 0 && (
                <div className="history-truncation" role="status">
                  {omittedMessages} older{' '}
                  {omittedMessages === 1 ? 'message was' : 'messages were'}{' '}
                  omitted from this request to stay within the 50-message server
                  limit. The full saved transcript remains visible until you
                  start a new conversation.
                </div>
              )}
              {visible.map((message, index) => {
                const parsed = extractEntries(message.content);
                const content =
                  message.role === 'assistant' && parsed
                    ? stripEntriesBlock(message.content) ||
                      'Please review the timesheet below.'
                    : message.content;
                return (
                  <motion.div
                    key={`${message.role}-${index}`}
                    initial={{ opacity: 0, y: 10, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    transition={{ duration: 0.3, delay: 0.05 }}
                  >
                    <MessageBubble message={{ ...message, content }} />
                  </motion.div>
                );
              })}
              {fallbackNotice && (
                <div className="review-fallback-notice" role="status">
                  {fallbackNotice}
                </div>
              )}
              {displayedEntries && (
                <ReviewPanel
                  entries={displayedEntries}
                  onSessionExpired={() => endSession(true)}
                  title={
                    manualOpen ? 'Manual Timesheet Review' : 'Review Timesheet'
                  }
                  description={
                    manualOpen
                      ? 'Enter or correct every field. The server performs final validation after approval.'
                      : 'Check or correct every captured field before approval. The server performs final validation.'
                  }
                  manual={manualOpen}
                />
              )}
              <div ref={scrollAnchor} className="scroll-anchor" />
            </div>
          </div>
          <div className="dock">
            <div className="dock-inner">
              {voiceNotice && (
                <div className="voice-fallback-notice" role="status">
                  {voiceNotice}
                </div>
              )}
              {mic.browserSpeechFallbackAvailable && (
                <div className="browser-speech-consent" role="alert">
                  <p>
                    Browser speech is a different speech service. Choose it only
                    if you consent to microphone audio being processed there.
                  </p>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={mic.useBrowserSpeechFallback}
                    disabled={sending}
                  >
                    Use browser speech instead
                  </button>
                </div>
              )}
              <Composer
                disabled={(sending && !mic.listening) || viewTab !== 'chat'}
                onSend={sendUser}
                supported={mic.supported}
                listening={mic.listening}
                onStartMic={startMicSession}
                onStopMic={stopMicSession}
                errorMsg={mic.errorMsg}
                notice={mic.notice}
                voiceState={voiceState}
                handsFree={voiceOn}
                draft={draft}
                onDraftChange={setDraft}
                onRegisterTrigger={(trigger) => {
                  composerMicTriggerRef.current = trigger;
                }}
              />
              <div className="composer-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setManualOpen((current) => !current);
                    setViewTab('chat');
                  }}
                  disabled={viewTab !== 'chat'}
                >
                  {manualOpen ? 'Close manual review' : 'Review manually'}
                </button>
              </div>
              <p className="hint muted small">
                The assistant captures date, times, payroll and expenditure
                details for your approval. Nothing is sent to OTL until you
                approve the reviewed timesheet.
              </p>
            </div>
          </div>
        </div>
      )}
    </ChatShell>
  );
}
