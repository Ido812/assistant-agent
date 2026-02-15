/**
 * MessageBubble — Renders a single chat message.
 *
 * - User messages: blue bubble, right-aligned
 * - Assistant messages: dark bubble, left-aligned, with markdown rendering
 *   and a small category badge above (e.g., "📈 stock")
 */

import ReactMarkdown from "react-markdown";
import { CategoryBadge } from "./CategoryBadge";
import type { ChatMessage } from "../types";

interface Props {
  message: ChatMessage;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  return (
    <div className={`message ${isUser ? "message-user" : "message-assistant"}`}>
      {/* Show category badge above assistant messages */}
      {!isUser && message.category && message.category !== "unknown" && (
        <CategoryBadge category={message.category} />
      )}
      <div className={`bubble ${isUser ? "bubble-user" : "bubble-assistant"}`}>
        {isUser ? (
          <p>{message.content}</p>
        ) : (
          /* Render markdown (bold, code blocks, lists, etc.) in assistant messages */
          <ReactMarkdown>{message.content}</ReactMarkdown>
        )}
      </div>
    </div>
  );
}
