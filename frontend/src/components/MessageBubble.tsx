import ReactMarkdown from "react-markdown";
import { stripEntriesBlock } from "../lib/entries";
import type { ChatMessage } from "../types";
import { SpeakerIcon } from "./icons";
import ThinkingState from "./ThinkingState";
import ToolChip from "./ToolChip";

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
      <div className="bubble-wrapper">
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="tool-chips-container">
            {message.toolCalls.map((tool, i) => (
              <ToolChip key={i} tool={tool} />
            ))}
          </div>
        )}
        
        {message.thinking && <ThinkingState reasoning={message.reasoning} />}
        
        {(!message.thinking || text) && (
          <div className="bubble">
            {isUser ? (
              <p>{message.content}</p>
            ) : (
              <div className={`md ${message.streaming ? "streaming" : ""}`}>
                <ReactMarkdown
                  components={{
                    a: ({ node, ...props }) => (
                      <a {...props} target="_blank" rel="noopener noreferrer" />
                    ),
                  }}
                >
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
        )}
      </div>
    </div>
  );
}
