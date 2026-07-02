import { DecisionBadge } from "./ui";

type ParsedReview = {
  decision: string | null;
  findings: string[];
  requiredChanges: string[];
};

export function CodeReviewPanel({ markdown }: { markdown: string }) {
  const parsed = parseCodeReview(markdown);
  return (
    <div className="space-y-4">
      <DecisionBadge decision={parsed.decision} />
      <ReviewList title="Findings" items={parsed.findings} empty="No findings listed." />
      <ReviewList
        title="Required Changes"
        items={parsed.requiredChanges}
        empty="No required changes listed."
      />
    </div>
  );
}

function ReviewList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-muted">{title}</h3>
      {items.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-base leading-7 text-text">
          {items.map((item, index) => (
            <li key={`${title}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="text-base text-muted">{empty}</p>
      )}
    </div>
  );
}

function parseCodeReview(markdown: string): ParsedReview {
  const lines = markdown.split("\n");
  const decision = lines
    .find((line) => line.toLowerCase().includes("decision:"))
    ?.split(":")
    .slice(1)
    .join(":")
    .trim()
    .replace(/[`*]/g, "")
    .split(/\s+/)[0] ?? null;
  return {
    decision,
    findings: sectionBullets(lines, "Findings"),
    requiredChanges: sectionBullets(lines, "Required Changes").filter((item) => item !== "(none)"),
  };
}

function sectionBullets(lines: string[], sectionName: string): string[] {
  const start = lines.findIndex((line) => line.trim().toLowerCase() === sectionName.toLowerCase());
  if (start === -1) {
    return [];
  }
  const items: string[] = [];
  for (const line of lines.slice(start + 1)) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    if (!trimmed.startsWith("-") && !trimmed.startsWith("*") && items.length > 0) {
      break;
    }
    if (trimmed.startsWith("-") || trimmed.startsWith("*")) {
      items.push(trimmed.replace(/^[-*]\s*/, ""));
    }
  }
  return items;
}
