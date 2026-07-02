import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listRuns, type PendingRun } from "../api";
import { DecisionBadge, ErrorText, Shell, Skeleton } from "../components/ui";

export function PendingList() {
  const [runs, setRuns] = useState<PendingRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = useCallback(async (isRefresh = false) => {
    setError(null);
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    try {
      setRuns(await listRuns());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Shell>
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text">BSP Agent Console</h1>
          <p className="mt-1 text-base text-muted">{runs.length} runs waiting for approval</p>
        </div>
        <button
          type="button"
          onClick={() => void load(true)}
          disabled={refreshing}
          aria-label="Refresh pending runs"
          className="focus-ring inline-flex items-center gap-2 rounded border border-border bg-surface px-3 py-2 text-sm font-medium text-text hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />
          Refresh
        </button>
      </div>

      {error ? <ErrorText>{error}</ErrorText> : null}

      <section className="mt-4 rounded border border-border bg-surface">
        {loading ? (
          <PendingSkeleton />
        ) : runs.length === 0 ? (
          <div className="px-5 py-12 text-center text-base text-muted">No runs waiting for approval.</div>
        ) : (
          <div className="divide-y divide-border">
            {runs.map((run) => (
              <button
                key={run.run_id}
                type="button"
                onClick={() => navigate(`/runs/${encodeURIComponent(run.run_id)}`)}
                className="focus-ring grid w-full cursor-pointer grid-cols-1 gap-3 px-5 py-4 text-left hover:bg-surface-hover md:grid-cols-[1.6fr_0.7fr_0.8fr_0.6fr_0.5fr]"
              >
                <div>
                  <div className="font-mono text-sm font-semibold text-accent">{run.run_id}</div>
                  <div className="mt-1 truncate text-sm text-muted">
                    {run.issue_first_line || "No issue summary"}
                  </div>
                </div>
                <div className="self-center text-sm font-medium text-text">
                  {run.issue_no ? `GitLab #${run.issue_no}` : "No issue"}
                </div>
                <div className="self-center">
                  <DecisionBadge decision={run.code_review} />
                </div>
                <div className="self-center text-sm text-muted">
                  <span className="font-medium text-text">{run.changed_files.length}</span> changed files
                </div>
                <div className="self-center text-sm text-muted">
                  Attempt {run.attempt_no ?? "-"}
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
    </Shell>
  );
}

function PendingSkeleton() {
  return (
    <div className="divide-y divide-border">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="grid grid-cols-1 gap-3 px-5 py-4 md:grid-cols-[1.6fr_0.7fr_0.8fr_0.6fr_0.5fr]">
          <div>
            <Skeleton className="h-5 w-64" />
            <Skeleton className="mt-2 h-4 w-80" />
          </div>
          <Skeleton className="h-5 w-20 self-center" />
          <Skeleton className="h-7 w-28 self-center" />
          <Skeleton className="h-5 w-24 self-center" />
          <Skeleton className="h-5 w-20 self-center" />
        </div>
      ))}
    </div>
  );
}
