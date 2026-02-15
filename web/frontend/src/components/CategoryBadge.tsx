/**
 * CategoryBadge — Small label showing which agent handled the message.
 * Appears above assistant messages (e.g., "📈 stock", "🧮 knowledge").
 */

interface Props {
  category: string;
}

const LABELS: Record<string, { icon: string; color: string }> = {
  stock: { icon: "📈", color: "#10b981" },      // green
  work: { icon: "💰", color: "#f59e0b" },       // amber
  schedule: { icon: "📅", color: "#3b82f6" },   // blue
  knowledge: { icon: "🧮", color: "#8b5cf6" },  // purple
};

export function CategoryBadge({ category }: Props) {
  const label = LABELS[category];
  if (!label) return null;

  return (
    <span className="category-badge" style={{ color: label.color }}>
      {label.icon} {category}
    </span>
  );
}
