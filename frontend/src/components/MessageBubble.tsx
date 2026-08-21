import ReactMarkdown from "react-markdown";
import { stripEntriesBlock } from "../lib/entries";
import type { ChatMessage } from "../types";
import ThinkingState from "./ThinkingState";
import ToolChip from "./ToolChip";

export default function MessageBubble({
  message,
}: {
  message: ChatMessage;
}) {
  const isUser = message.role === "user";
  let text = isUser ? message.content : stripEntriesBlock(message.content);
  
  if (!isUser) {
    // Strip SSML tags for visual rendering (e.g. <break time="300ms"/>)
    text = text.replace(/<[^>]+>/g, "");
  }

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
        
        {(text || message.streaming || (isUser && message.content)) && (
          <div className="bubble">
            {isUser ? (
              <p>{message.content}</p>
            ) : (
              <div className={`md ${message.streaming ? "streaming" : ""}`}>
                <ReactMarkdown
                  components={{
                    // eslint-disable-next-line @typescript-eslint/no-unused-vars
                    a: ({ node: _node, ...props }) => (
                      <a {...props} target="_blank" rel="noopener noreferrer" />
                    ),
                  }}
                >
                  {text || (message.streaming ? "…" : "")}
                </ReactMarkdown>
                {message.streaming && <span className="caret" aria-hidden />}
              </div>
            )}

          </div>
        )}
      </div>
    </div>
  );
}
