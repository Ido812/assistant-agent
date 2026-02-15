/**
 * InputBar — The message input at the bottom of the screen.
 *
 * - Textarea that grows with content (up to 120px)
 * - Send button (arrow icon)
 * - Enter sends, Shift+Enter adds a new line
 * - Disabled while the assistant is thinking
 * - Font size >= 16px to prevent iOS Safari from zooming in on focus
 */

import { useState, useRef, useCallback } from "react";

interface Props {
  onSend: (message: string) => void;
  disabled: boolean;
}

export function InputBar({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    // Refocus the input after sending
    setTimeout(() => inputRef.current?.focus(), 100);
  }, [text, disabled, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Enter = send, Shift+Enter = new line
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="input-bar">
      <textarea
        ref={inputRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Message..."
        rows={1}
        disabled={disabled}
        className="input-textarea"
      />
      <button
        onClick={handleSend}
        disabled={disabled || !text.trim()}
        className="send-button"
        aria-label="Send"
      >
        {/* Simple arrow icon */}
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
        </svg>
      </button>
    </div>
  );
}
