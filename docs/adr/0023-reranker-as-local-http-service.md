# Reranker as a Local HTTP Service

Move the cross-encoder out of the agent process and behind a local HTTP endpoint
served by `llama-server`. ADR-0022's in-process design failed in a real run; this
records why, and what replaces it.

Status: **Proposed** on branch `feat/deep-agent-integration`. Amends ADR-0022 §3.

## Context

ADR-0022 loaded `BAAI/bge-reranker-v2-m3` in-process through
`sentence-transformers`, behind an optional `rerank` extra. Two problems showed up
once it ran for real.

**It silently stopped reranking.** A Langfuse trace of an actual repair run showed
every result rendered as `Cross-encoder score: 0.0000`. That is the exact signature
of `rerank()`'s fail-open path: the model never loaded, so the ordering was plain
`ts_rank` while the output still looked like scored results. The cause is that
`sentence-transformers` lives in an **optional** extra — a plain `uv sync` or
`uv run` resolves without extras and removes it, after which reranking degrades
silently on the next run. An optional dependency that the runtime silently depends
on is a trap, not a feature.

**It made the agent environment heavy.** torch is 3–4 GB in every environment that
runs the agent, and each new process paid roughly 3 s of model load before the first
query. Meanwhile the LLM and PostgreSQL were already services — the reranker was the
only model the agent hosted itself, for no architectural reason.

## Decision

Run the reranker as a local service and make the agent a thin HTTP client.

```bash
llama-server -hf gpustack/bge-reranker-v2-m3-GGUF \
  --reranking --pooling rank \
  -c 8192 -b 4096 -ub 4096 \
  --host 127.0.0.1 --port 8081
```

It exposes an OpenAI-shaped `POST /v1/rerank` returning
`{results: [{index, relevance_score}]}` — the same request/response idiom the agent
already uses for the LLM. `llama.cpp` builds natively for `Darwin arm64`, so this is
Metal-accelerated on the development Mac and the same invocation moves to the Ubuntu
build host with a CUDA backend.

*Measured on the M4, 40 real candidates:*

| | Time | Per pair |
|---|---|---|
| `llama-server` (Metal) | **4.09 s** | **102 ms** |
| in-process, fp32 / batch 4 | 5.78 s | 144 ms |

About 30% faster, with the same ordering as the in-process ranker (top hits were the
same MGBE pin table, function tables, and MGBE prose).

The agent drops `sentence-transformers`, torch, and the `rerank` extra entirely.
There is no in-process fallback: keeping one would reintroduce the heavy dependency
this ADR exists to remove, and the fail-open path is now visible (ADR-0022 follow-up)
so a stopped service is obvious rather than silent.

### Three details that will otherwise bite

**Batch and context must be raised at start-up.** With defaults, the server clamps
`n_batch` to 512 and any request containing a longer chunk fails with HTTP 500 —
observed immediately on real document chunks. `-c 8192 -b 4096 -ub 4096` is part of
the contract, not tuning.

**The score scale changed.** `llama.cpp` returns raw logits (negative values, e.g.
`-2.359`); `sentence-transformers` returned sigmoid-normalised `[0, 1]`. Ordering is
identical, but the numbers are not comparable. The client applies a sigmoid so the
rendered `Cross-encoder score` stays on the `[0, 1]` scale that existing artifacts,
debug JSON, and the ADR-0022 measurements use.

**Model choice is now constrained by the server.** `llama.cpp`'s rerank path
produces wrong results for pooling-incompatible models — Qwen3-Reranker, mxbai, and
ColBERT among them — while `bge-v2-m3` is on the supported list. ADR-0022 chose BGE
because its classification head made integration simpler; that choice is now also
what keeps this deployment viable. Do not swap the model without checking llama.cpp
compatibility first.

## Configuration

```env
RERANKER_URL=http://127.0.0.1:8081/v1/rerank
RERANKER_TIMEOUT_SEC=120
RERANK_CANDIDATE_LIMIT=40
RERANK_TOP_K=10
```

`RERANKER_MODEL`, `RERANKER_DEVICE`, `RERANKER_DTYPE`, and `RERANKER_BATCH_SIZE`
are retired — model, device, and batching are now the service's concern, chosen by
its start-up flags.

## Consequences

The agent environment sheds 3–4 GB and the class of failure where a dependency
resolve silently disables ranking. The model stays warm, so no run pays the load
cost. In exchange there is one more service to keep running, and a new failure mode
— service down, or wrong port — which degrades to `ts_rank` order and, because of
the visible-degradation change, says so in the output rather than printing a
plausible-looking `0.0000`. The service is bound to `127.0.0.1`, so it is not
reachable off-box; note that `llama-server` sets permissive CORS and no API key,
which is acceptable only while it stays bound to loopback.

## Deferred

- Auto-starting the service (docker-compose entry, or a launch script) rather than
  running it by hand.
- Serving embeddings from the same `llama-server` process — it can host LLM,
  embedding, and reranker together, which becomes relevant only if dense retrieval
  is ever adopted (ADR-0022 says not yet).
- Sharing one reranker service between the Mac and the Ubuntu host instead of
  running one per machine.
