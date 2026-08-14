import ReactMarkdown from "react-markdown";
import { stripEntriesBlock } from "../lib/entries";
import type { ChatMessage } from "../types";
import { SpeakerIcon } from "./icons";

export default function MessageBubble({
  message,
  onSpeak,
}: {
  message: ChatMessage;
  onSpeak?: (text: string) => void;
}) {
  const isUser = message.role === "user";
  const text = isUser ? message.content : stripEntriesBlock(message.content);

  return (
    <div className={`bubble-row ${isUser ? "user" : "assistant"}`}>
      <div className="bubble">
        {isUser ? (
          <p>{message.content}</p>
        ) : (
          <div className="md">
            <ReactMarkdown>
              {text || (message.streaming ? "…" : "")}
            </ReactMarkdown>
            {message.streaming && <span className="caret" aria-hidden />}
          </div>
        )}

        {!isUser && !message.streaming && text && onSpeak && (
          <button
            className="icon-btn speak"
            title="Play aloud"
            aria-label="Play this reply aloud"
            onClick={() => onSpeak(text)}
          >
            <SpeakerIcon />
          </button>
        )}
      </div>
    </div>
  );
}
