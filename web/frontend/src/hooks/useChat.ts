/**
 * useChat — Custom React hook that manages all chat state and server communication.
 *
 * What it does:
 * - Keeps track of all messages (user + assistant) in a list
 * - Sends user messages to the backend via SSE (Server-Sent Events)
 * - Updates "isThinking" and "thinkingCategory" for the typing animation
 * - Returns everything the UI components need to render the chat
 */

import { useState, useCallback } from "react";
import type { ChatMessage, SSEEvent } from "../types";

/** Generate a unique ID for each message */
function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingCategory, setThinkingCategory] = useState<string | null>(null);

  const sendMessage = useCallback(async (text: string) => {
    // 1. Add the user's message to the chat immediately
    const userMsg: ChatMessage = {
      id: generateId(),
      role: "user",
      content: text,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsThinking(true);
    setThinkingCategory(null);

    try {
      // 2. Send the message to the backend's SSE endpoint
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });

      // 3. Read the SSE stream — the server sends events as they happen:
      //    "thinking" → "classified" (which agent) → "answer" (final response)
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE format: each event is "data: {...json...}\n\n"
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const event: SSEEvent = JSON.parse(line.slice(6));

          if (event.type === "classified") {
            // The server figured out which agent to use — update the typing label
            setThinkingCategory(event.category || null);
          } else if (event.type === "answer") {
            // Got the final answer — add it to the chat
            const assistantMsg: ChatMessage = {
              id: generateId(),
              role: "assistant",
              content: event.answer || "",
              timestamp: Date.now(),
              category: event.category as ChatMessage["category"],
              confidence: event.confidence,
            };
            setMessages((prev) => [...prev, assistantMsg]);
            setIsThinking(false);
            setThinkingCategory(null);
          } else if (event.type === "error") {
            // Something went wrong — show the error as an assistant message
            setMessages((prev) => [
              ...prev,
              {
                id: generateId(),
                role: "assistant",
                content: `Error: ${event.error}`,
                timestamp: Date.now(),
                category: "unknown",
              },
            ]);
            setIsThinking(false);
          }
        }
      }
    } catch {
      // Network error — show a friendly message
      setMessages((prev) => [
        ...prev,
        {
          id: generateId(),
          role: "assistant",
          content: "Connection error. Please try again.",
          timestamp: Date.now(),
          category: "unknown",
        },
      ]);
      setIsThinking(false);
    }
  }, []);

  return { messages, isThinking, thinkingCategory, sendMessage };
}
