import type { ReactNode } from "react";
import type { ReviewDecision } from "../api";

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-bg text-text">
      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded border border-border bg-surface">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-base font-semibold text-text">{title}</h2>
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-border/70 ${className}`} />;
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent ${className}`}
    />
  );
}

export function StageBadge({ stage }: { stage: string }) {
  return (
    <span className="inline-flex items-center rounded border border-border bg-surface-hover px-2.5 py-1 text-xs font-medium text-muted">
      Stage: {stage}
    </span>
  );
}

export function DecisionBadge({ decision }: { decision: ReviewDecision }) {
  const value = decision || "unknown";
  const classes =
    value === "pass"
      ? "border-green-200 bg-green-50 text-green-700"
      : value === "reject"
        ? "border-red-200 bg-red-50 text-red-700"
        : value === "needs_human"
          ? "border-amber-200 bg-amber-50 text-amber-700"
          : "border-border bg-surface-hover text-muted";
  return (
    <span className={`inline-flex items-center rounded border px-2.5 py-1 text-xs font-semibold ${classes}`}>
      Review: {value}
    </span>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-danger">
      {children}
    </p>
  );
}
