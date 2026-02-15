/**
 * ChatWindow — The main chat screen.
 *
 * Combines all pieces together:
 * - Header at the top
 * - Scrollable message list in the middle
 * - Typing indicator when assistant is working
 * - Input bar fixed at the bottom
 * - Auto-scrolls to the latest message
 */

import { useRef, useEffect } from "react";
import { useChat } from "../hooks/useChat";
import { MessageBubble } from "./MessageBubble";
import { InputBar } from "./InputBar";
import { TypingIndicator } from "./TypingIndicator";

export function ChatWindow() {
  const { messages, isThinking, thinkingCategory, sendMessage } = useChat();
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the bottom whenever a new message appears or thinking starts
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  return (
    <div className="chat-window">
      {/* Header */}
      <header className="chat-header">
        <h1>Assistant Agent</h1>
      </header>

      {/* Message list */}
      <div className="messages-container">
        {messages.length === 0 && (
          <div className="empty-state">
            <p className="empty-state-emoji">💬</p>
            <p>Ask me anything about math, stocks, schedule, or payments</p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {isThinking && <TypingIndicator category={thinkingCategory} />}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <InputBar onSend={sendMessage} disabled={isThinking} />
    </div>
  );
}
