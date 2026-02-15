/** A single message in the chat (either from the user or from the assistant). */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  /** Which agent handled this message (only on assistant messages) */
  category?: "stock" | "work" | "knowledge" | "schedule" | "unknown";
  confidence?: number;
}

/** Events the server sends via SSE (Server-Sent Events) */
export interface SSEEvent {
  type: "thinking" | "classified" | "answer" | "error";
  category?: string;
  confidence?: number;
  answer?: string;
  reason?: string;
  mission?: string;
  error?: string;
}
