import { ArrowLeft, Ban, CheckCircle2, RotateCw, Trash2, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  abandonRun,
  approveRun,
  deleteRun,
  getRun,
  publishRun,
  rejectRun,
  retryRun,
  type AbandonResult,
  type ApproveResult,
  type PublishResult,
  type RejectResult,
  type RetryResult,
  type RunDetail,
} from "../api";
import { CodeReviewPanel } from "../components/codeReview";
import { DiffViewer } from "../components/diff";
import { ErrorText, Panel, Shell, Skeleton, Spinner, StageBadge } from "../components/ui";

export function RunDetailPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const decodedRunId = useMemo(() => (runId ? decodeURIComponent(runId) : ""), [runId]);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [approveResult, setApproveResult] = useState<ApproveResult | null>(null);
  const [rejectResult, setRejectResult] = useState<RejectResult | null>(null);
  const [publishResult, setPublishResult] = useState<PublishResult | null>(null);
  const [abandonResult, setAbandonResult] = useState<AbandonResult | null>(null);
  const [retryResult, setRetryResult] = useState<RetryResult | null>(null);
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [abandoning, setAbandoning] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [feedback, setFeedback] = useState("");

  const load = useCallback(async () => {
    if (!decodedRunId) {
      setError("Missing run id.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setRun(await getRun(decodedRunId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run.");
    } finally {
      setLoading(false);
    }
  }, [decodedRunId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onApprove() {
    if (!run) {
      return;
    }
    setApproving(true);
    setActionError(null);
    setApproveResult(null);
    try {
      const result = await approveRun(run.run_id);
      setApproveResult(result);
      setRun({ ...run, stage: result.stage, changed_files: result.changed_files });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Approve failed.");
    } finally {
      setApproving(false);
    }
  }

  async function onReject() {
    if (!run || !feedback.trim()) {
      return;
    }
    setRejecting(true);
    setActionError(null);
    setRejectResult(null);
    try {
      const result = await rejectRun(run.run_id, feedback.trim());
      setRejectResult(result);
      setRun({ ...run, stage: result.stage, attempt_no: result.attempt_no });
      setFeedback("");
      setShowReject(false);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Reject failed.");
    } finally {
      setRejecting(false);
    }
  }

  async function onRetryPublish() {
    if (!run) {
      return;
    }
    setPublishing(true);
    setActionError(null);
    setPublishResult(null);
    try {
      const result = await publishRun(run.run_id);
      setPublishResult(result);
      setRun({ ...run, stage: result.stage, publish_error: result.publish_error });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Retry push failed.");
    } finally {
      setPublishing(false);
    }
  }

  async function onAbandon() {
    if (!run) {
      return;
    }
    setAbandoning(true);
    setActionError(null);
    setAbandonResult(null);
    try {
      const result = await abandonRun(run.run_id);
      setAbandonResult(result);
      setRun({ ...run, stage: result.stage });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Abandon failed.");
    } finally {
      setAbandoning(false);
    }
  }

  async function onRetry() {
    if (!run) {
      return;
    }
    setRetrying(true);
    setActionError(null);
    setRetryResult(null);
    try {
      const result = await retryRun(run.run_id);
      setRetryResult(result);
      // The pipeline re-ran: reload to pick up the fresh diff, review, and mode.
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Retry failed.");
    } finally {
      setRetrying(false);
    }
  }

  async function onDelete() {
    if (!run) {
      return;
    }
    setDeleting(true);
    setActionError(null);
    try {
      await deleteRun(run.run_id);
      // The run is gone; go back to the console.
      navigate("/");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Delete failed.");
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <Shell>
        <DetailSkeleton />
      </Shell>
    );
  }

  if (error || !run) {
    return (
      <Shell>
        <Link className="focus-ring mb-4 inline-flex items-center gap-2 rounded text-sm font-medium text-accent" to="/">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back to pending runs
        </Link>
        <ErrorText>{error || "Run not found."}</ErrorText>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link className="focus-ring mb-3 inline-flex items-center gap-2 rounded text-sm font-medium text-accent" to="/">
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to pending runs
          </Link>
          <h1 className="font-mono text-xl font-semibold text-accent">{run.run_id}</h1>
        </div>
        <StageBadge stage={run.stage} />
      </div>

      <div className="space-y-5 pb-28">
        <Panel title="Issue">
          <p className="whitespace-pre-wrap text-base leading-7 text-text">{run.issue}</p>
        </Panel>

        {run.mode === "llm_failure" ? (
          <Panel title="LLM Failure">
            <p className="mb-2 text-sm text-muted">
              The LLM was unavailable, so no patch was produced. Retry to re-run this attempt (the
              retry budget is not consumed), or abandon the run.
            </p>
            <p className="whitespace-pre-wrap rounded border border-danger/40 bg-red-50 px-3 py-2 font-mono text-sm text-danger">
              {run.failure_reason || "Unknown LLM failure."}
            </p>
          </Panel>
        ) : (
          <>
            <Panel title="Code Review">
              <CodeReviewPanel markdown={run.code_review} />
            </Panel>

            <Panel title="Diff">
              <div className="mb-4 flex flex-wrap gap-2">
                {run.changed_files.length > 0 ? (
                  run.changed_files.map((file) => (
                    <span key={file} className="rounded border border-border bg-surface-hover px-2.5 py-1 font-mono text-xs text-muted">
                      {file}
                    </span>
                  ))
                ) : (
                  <span className="text-sm text-muted">No changed files reported.</span>
                )}
              </div>
              <DiffViewer diff={run.diff} />
            </Panel>
          </>
        )}
      </div>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/95 px-4 py-4 shadow-sm backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-h-10 text-sm">
            {approveResult ? (
              <p className="text-approve">
                Published branch:{" "}
                <span className="font-mono font-semibold">{approveResult.published_branch || "(not published)"}</span>
              </p>
            ) : null}
            {rejectResult ? (
              <p className="text-warn">
                Rejected. Current stage: <span className="font-semibold">{rejectResult.stage}</span>, attempt{" "}
                {rejectResult.attempt_no}.
              </p>
            ) : null}
            {publishResult ? (
              <p className="text-approve">
                Published branch:{" "}
                <span className="font-mono font-semibold">{publishResult.published_branch || "(not published)"}</span>
              </p>
            ) : null}
            {abandonResult ? (
              <p className="text-danger">
                Abandoned. Current stage: <span className="font-semibold">{abandonResult.stage}</span>.
              </p>
            ) : null}
            {run.stage === "publish_failed" && run.publish_error ? (
              <p className="text-danger">Publish error: {run.publish_error}</p>
            ) : null}
            {retryResult ? (
              <p className="text-warn">
                Retried. Current stage: <span className="font-semibold">{retryResult.stage}</span>.
              </p>
            ) : null}
            {actionError ? <ErrorText>{actionError}</ErrorText> : null}
          </div>

          {run.stage === "human_review" && run.mode !== "llm_failure" ? (
            <div className="flex flex-col gap-3 sm:items-end">
            {showReject ? (
              <div className="w-full sm:w-[420px]">
                <label className="mb-1 block text-sm font-medium text-muted" htmlFor="reject-feedback">
                  Reject feedback
                </label>
                <textarea
                  id="reject-feedback"
                  value={feedback}
                  onChange={(event) => setFeedback(event.target.value)}
                  className="focus-ring min-h-24 w-full resize-y rounded border border-border bg-surface px-3 py-2 text-base text-text"
                  placeholder="Explain what must change before approval."
                  disabled={approving || rejecting}
                />
              </div>
            ) : null}
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => void onDelete()}
                disabled={approving || rejecting || deleting}
                className="focus-ring inline-flex items-center gap-2 rounded border border-border bg-surface px-4 py-2 text-sm font-semibold text-muted hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                {deleting ? <Spinner /> : <Trash2 className="h-4 w-4" aria-hidden="true" />}
                Delete
              </button>
              <button
                type="button"
                onClick={() => setShowReject((value) => !value)}
                disabled={approving || rejecting}
                className="focus-ring inline-flex items-center gap-2 rounded border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-danger hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <XCircle className="h-4 w-4" aria-hidden="true" />
                Reject
              </button>
              {showReject ? (
                <button
                  type="button"
                  onClick={() => void onReject()}
                  disabled={approving || rejecting || !feedback.trim()}
                  className="focus-ring inline-flex items-center gap-2 rounded border border-danger bg-danger px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {rejecting ? <Spinner /> : <XCircle className="h-4 w-4" aria-hidden="true" />}
                  Submit rejection
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => void onApprove()}
                disabled={approving || rejecting}
                className="focus-ring inline-flex items-center gap-2 rounded border border-approve bg-approve px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {approving ? <Spinner /> : <CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
                Approve
              </button>
            </div>
            </div>
          ) : null}

          {run.stage === "publish_failed" ? (
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => void onAbandon()}
                disabled={publishing || abandoning}
                className="focus-ring inline-flex items-center gap-2 rounded border border-danger bg-red-50 px-4 py-2 text-sm font-semibold text-danger hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {abandoning ? <Spinner /> : <Ban className="h-4 w-4" aria-hidden="true" />}
                Abandon
              </button>
              <button
                type="button"
                onClick={() => void onRetryPublish()}
                disabled={publishing || abandoning}
                className="focus-ring inline-flex items-center gap-2 rounded border border-approve bg-approve px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {publishing ? <Spinner /> : <RotateCw className="h-4 w-4" aria-hidden="true" />}
                Retry push
              </button>
            </div>
          ) : null}

          {run.stage === "human_review" && run.mode === "llm_failure" ? (
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => void onDelete()}
                disabled={retrying || abandoning || deleting}
                className="focus-ring inline-flex items-center gap-2 rounded border border-border bg-surface px-4 py-2 text-sm font-semibold text-muted hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                {deleting ? <Spinner /> : <Trash2 className="h-4 w-4" aria-hidden="true" />}
                Delete
              </button>
              <button
                type="button"
                onClick={() => void onAbandon()}
                disabled={retrying || abandoning}
                className="focus-ring inline-flex items-center gap-2 rounded border border-danger bg-red-50 px-4 py-2 text-sm font-semibold text-danger hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {abandoning ? <Spinner /> : <Ban className="h-4 w-4" aria-hidden="true" />}
                Abandon
              </button>
              <button
                type="button"
                onClick={() => void onRetry()}
                disabled={retrying || abandoning}
                className="focus-ring inline-flex items-center gap-2 rounded border border-approve bg-approve px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {retrying ? <Spinner /> : <RotateCw className="h-4 w-4" aria-hidden="true" />}
                Retry
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </Shell>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-5 w-40" />
      <Skeleton className="h-8 w-96" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-52 w-full" />
      <Skeleton className="h-80 w-full" />
    </div>
  );
}
