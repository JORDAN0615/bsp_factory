type DiffViewerProps = {
  diff: string;
};

export function DiffViewer({ diff }: DiffViewerProps) {
  const lines = diff ? diff.split("\n") : ["No diff available."];
  return (
    <pre className="overflow-x-auto rounded border border-border bg-surface text-sm leading-6 text-text">
      <code className="block font-mono">
        {lines.map((line, index) => (
          <span key={`${index}-${line}`} className={`block px-4 ${lineClass(line)}`}>
            {line || " "}
          </span>
        ))}
      </code>
    </pre>
  );
}

function lineClass(line: string): string {
  if (line.startsWith("+") && !line.startsWith("+++")) {
    return "bg-green-600/10 text-green-900";
  }
  if (line.startsWith("-") && !line.startsWith("---")) {
    return "bg-red-600/10 text-red-900";
  }
  if (line.startsWith("@@")) {
    return "bg-indigo-50 text-accent";
  }
  return "";
}
