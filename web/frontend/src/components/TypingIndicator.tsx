/**
 * TypingIndicator — Animated dots shown while the assistant is thinking.
 * Optionally shows which agent is working (e.g., "Checking stocks...").
 */

interface Props {
  category: string | null;
}

const CATEGORY_LABELS: Record<string, string> = {
  stock: "Checking stocks...",
  work: "Checking payments...",
  schedule: "Checking calendar...",
  knowledge: "Thinking...",
};

export function TypingIndicator({ category }: Props) {
  return (
    <div className="message message-assistant">
      <div className="bubble bubble-assistant typing-bubble">
        <div className="typing-dots">
          <span />
          <span />
          <span />
        </div>
        {category && (
          <span className="typing-label">
            {CATEGORY_LABELS[category] || "Processing..."}
          </span>
        )}
      </div>
    </div>
  );
}
