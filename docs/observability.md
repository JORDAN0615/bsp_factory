# Observability with Langfuse (self-hosted, local)

This agent emits LLM traces to a self-hosted [Langfuse](https://langfuse.com)
instance running locally, so every repair run's LLM calls (skill selection, patch
generation, code review) are visible with prompt, response, token usage, and
latency, grouped under one trace per run.

Tracing is **off by default**. It activates only when the Langfuse keys are set,
so tests, CI, and offline runs are unaffected.

## Why this shape

All LLM calls in the agent funnel through a single function,
`agent/tools/llm_tools.py::chat_completion` (a raw `urllib` call to an
OpenAI-compatible endpoint — no OpenAI SDK, no LangChain). That single choke
point is wrapped as a Langfuse *generation*. The whole graph run is wrapped as a
*trace* keyed by `run_id`, and because the Langfuse v3 SDK propagates context via
OpenTelemetry, each generation nests under the run trace automatically.

```text
trace: run:<run_id>            (run_repair_graph / resume_review_graph)
  ├─ generation chat_completion  (select_skills)
  ├─ generation chat_completion  (patch_agent)
  └─ generation chat_completion  (code_review_agent)
```

## 1. Run Langfuse locally (docker compose)

Langfuse v3 self-host is a small stack: `langfuse-web`, `langfuse-worker`,
Postgres, ClickHouse, Redis, and MinIO (S3). Budget ~2–4 GB RAM.

```bash
git clone https://github.com/langfuse/langfuse
cd langfuse
docker compose up -d
# Web UI: http://localhost:3000
```

Then in the UI: create a local account → create a project → copy the API keys:

```text
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

## 2. Point the agent at it

Add to `.env` (leave blank to keep tracing off):

```bash
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

Then run the agent as usual (CLI or `bsp-agent serve`). Open the Langfuse UI and
each run appears as a trace named `run:<run_id>` with its LLM generations.

## 3. How it is wired

```text
agent/observability.py   lazy Langfuse client; no-op unless both keys are set.
                         run_span(run_id, issue) and generation(model, messages)
                         context managers; flush().
agent/tools/llm_tools.py chat_completion wraps the call in generation(...) and
                         reports output + token usage from the response.
agent/graph.py           run_repair_graph / resume_review_graph wrap .invoke in
                         run_span(...) and flush() afterward.
```

### Important: flush

Langfuse batches and sends asynchronously. CLI invocations are short-lived, so the
graph runners call `observability.flush()` after each run; otherwise traces are
lost on process exit. The webhook server flushes per run too.

### Gating

`observability.enabled()` is true only when `LANGFUSE_PUBLIC_KEY` and
`LANGFUSE_SECRET_KEY` are present. When false, every helper is a no-op and no
Langfuse client is constructed — identical behavior to before. This mirrors how
`tests/conftest.py` disables `LANGSMITH_TRACING`.

Langfuse is the self-hostable alternative to LangSmith; the existing `LANGSMITH_*`
vars can stay off.
