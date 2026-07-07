const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8080";

export type ReviewDecision = "pass" | "needs_human" | "reject" | string | null;

export type ReviewMode = "patch_review" | "llm_failure" | string;

export type PendingRun = {
  run_id: string;
  run_dir?: string;
  issue_no?: string | null;
  changed_files: string[];
  code_review: ReviewDecision;
  issue_first_line?: string;
  attempt_no?: number;
  mode?: ReviewMode;
  failure_reason?: string | null;
};

export type RunDetail = {
  run_id: string;
  stage: string;
  issue: string;
  attempt_no: number;
  changed_files: string[];
  publish_error: string | null;
  mode: ReviewMode;
  failure_reason: string | null;
  code_review: string;
  diff: string;
  repo_inspection: string;
};

export type ApproveResult = {
  run_id: string;
  stage: string;
  published_branch: string | null;
  changed_files: string[];
};

export type RejectResult = {
  run_id: string;
  stage: string;
  attempt_no: number;
};

export type PublishResult = {
  run_id: string;
  stage: string;
  published_branch: string | null;
  publish_error: string | null;
};

export type AbandonResult = {
  run_id: string;
  stage: string;
};

export type RetryResult = {
  run_id: string;
  stage: string;
  attempt_no: number;
  failure_reason: string | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      const text = await response.text();
      message = text || message;
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function listRuns(): Promise<PendingRun[]> {
  return request<PendingRun[]>("/api/runs");
}

export function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`);
}

export function approveRun(runId: string): Promise<ApproveResult> {
  return request<ApproveResult>(`/api/runs/${encodeURIComponent(runId)}/approve`, {
    method: "POST",
  });
}

export function rejectRun(runId: string, feedback: string): Promise<RejectResult> {
  return request<RejectResult>(`/api/runs/${encodeURIComponent(runId)}/reject`, {
    method: "POST",
    body: JSON.stringify({ feedback }),
  });
}

export function publishRun(runId: string): Promise<PublishResult> {
  return request<PublishResult>(`/api/runs/${encodeURIComponent(runId)}/publish`, {
    method: "POST",
  });
}

export function abandonRun(runId: string): Promise<AbandonResult> {
  return request<AbandonResult>(`/api/runs/${encodeURIComponent(runId)}/abandon`, {
    method: "POST",
  });
}

export function retryRun(runId: string): Promise<RetryResult> {
  return request<RetryResult>(`/api/runs/${encodeURIComponent(runId)}/retry`, {
    method: "POST",
  });
}

export type DeleteResult = {
  run_id: string;
  deleted: boolean;
};

export function deleteRun(runId: string): Promise<DeleteResult> {
  return request<DeleteResult>(`/api/runs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
}
