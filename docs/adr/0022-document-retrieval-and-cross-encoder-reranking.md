# Document Retrieval and Cross-Encoder Reranking

Wire the ingested knowledge documents (ADR-0021) into the agent, and replace the
LLM re-ranker with a small self-hosted cross-encoder. Records why dense retrieval is
still not used, and why the ranking stage — not recall — is the bottleneck.

Status: **Proposed** on branch `feat/deep-agent-integration`.

## Context

ADR-0021 landed the corpus in Postgres — 6 sources, 1411 `doc_chunks`, 2186
`pinmux_pins` — but nothing queries those tables, so the agent's capability is
unchanged. This ADR connects them and settles how results are ranked.

Three measurements against the real corpus drove the decisions below.

**Recall is not the problem; precision is.** Running the real MIC-741 issue text
against the document corpus returns hundreds of keyword hits per issue:

| Case | doc_chunks hits |
|---|---|
| ISSUE-G42006 (Mgbe failed up connection) | 674 |
| ISSUE-G42005 (GPU frequency mismatch) | 361 |
| RE-02 | 195 |
| RE-01 (MDIO / Ethernet PHY bring-up) | 127 |

Several hundred candidates is not good recall — it is an absence of discrimination.
Whatever sits after retrieval has to do the real work.

**Keyword search misses whole symbol families.** `plainto_tsquery('simple','can')`
returns **0** rows from `pinmux_pins`, even though 40 CAN pins are present
(`GP210_CAN2_DOUT`, signal `CAN2_DOUT`, …). Postgres matches whole lexemes, and the
digit fuses into the token, so `'can'` never matches `'can2'`. A prefix query
`can:*` returns all **40**. This is the same tokenization failure ADR-0014 recorded
for `v38.4.0` → `v38`.

**The corpus is English; the issues are mostly English too.** Chinese-only terms find
nothing (`相機`, `電源`, `無法開機` → 0) while their English equivalents work
(`camera` 28, `regulator` 7, `MGBE` 45). The real issue text is English technical
prose with Chinese table scaffolding, which is why keyword matching works at all.

### Benchmarked before adoption

`BAAI/bge-reranker-v2-m3` was downloaded and measured on an M4 / 24 GB Mac against
real FTS candidates, because the parameters below are only defensible with numbers.

*Quality.* For the query "MGBE ethernet link fails to come up automatically after
reboot", the reranker put the **MGBE pin table** first — `D28/D29 | UPHY RX12 |
DIFF IN | 100nF | MGBE0 RX differential signal…` — ahead of prose that merely states
the module "is equipped with integrated MGBE controllers" (rank 8). Preferring
concrete pin-level facts over generic description is the behaviour this agent wants:
a repair needs the ball numbers and the termination, not the marketing sentence.

*Latency*, fp16 on MPS, after the ADR-0021 table-rendering fix shortened chunks:

| Candidates | Time |
|---|---|
| 20 | 2.27 s |
| 40 | **4.12 s** |
| 100 | 8.27 s |

Roughly 100 ms per pair, linear in candidate count. fp32 was about twice as slow.

*A defect the benchmark exposed:* the top four results contained only two distinct
documents — a table spanning pages 14–15 was ingested twice, and one chunk appeared
twice. Near-duplicate chunks consume the top-K budget without adding information.

## Decision

### 1. Doc Retrieval joins Case Retrieval

A new module parallel to `mic741_knowledge.py` queries `doc_chunks` and
`pinmux_pins`, and its results are merged with Case Retrieval into one ranked
bundle. It is exposed the same two ways the case knowledge already is: as a
`search_technical_docs` tool the planner calls on demand, and as preloaded context
for the executor.

`pinmux_pins` and `doc_chunks` are queried separately — one is an atomic per-pin
record, the other a passage — but they compete in a single ranking stage, so the
agent gets one ordered list rather than two unrelated ones.

### 2. Prefix matching for symbol-like query terms

Query construction extends the existing `_fts_query_text` so that symbol-shaped
tokens are matched as prefixes (`can` → `can:*`). This is what makes a query about
"CAN" reach `CAN0_DOUT` / `CAN2_DIN`. It is a query-side change only: no
re-ingestion, no new index, no embeddings.

### 3. Ranking: a self-hosted cross-encoder replaces the LLM re-ranker

**BAAI/bge-reranker-v2-m3**, run in-process through `sentence-transformers`,
becomes the ranking stage for both Case and Doc Retrieval. The model is loaded once
as a process-level singleton and reused for every query — never re-initialized per
call — with device auto-detection (MPS on the Mac, CUDA or CPU elsewhere) so the
same code moves to the Ubuntu workstation unchanged.

Considered and rejected:

- **Keeping the LLM re-ranker as the ranking stage.** It runs on the same local
  `gpt-oss-120b` that performs the actual repair, so every ranking call contends for
  the GPU with the agent's real work — and the candidate pool just grew from ~10
  cases to several hundred document chunks. Published comparisons put a calibrated
  cross-encoder at parity-or-better with listwise LLM reranking for 100–1000× less
  cost and latency; listwise measured 0.78 vs 0.74 NDCG@10 at roughly 9× cost and
  35× latency. Spending a 120B model on work a 0.6B model does as well is the wrong
  allocation.
- **Ollama.** It has no `/api/rerank` endpoint; `/api/embeddings` returns embeddings
  rather than cross-encoder classification scores, so a reranker served through it
  is not actually performing cross-encoder reranking. The open feature request has
  sat unattended since mid-2025.
- **Hosted rerank APIs (Cohere and similar).** The corpus is proprietary vendor
  material; it does not leave the network.
- **Qwen3-Reranker-0.6B.** Equivalent size and quality class, but it is a
  *generative* reranker scored from yes/no logits, needing a bespoke prompt and
  scoring path. BGE exposes a classification head, so `CrossEncoder.predict` returns
  usable scores directly. Same result, far less integration surface. Revisit if BGE
  underperforms.

The existing `_rerank_with_llm` is kept behind its current flag so the two can be
compared rather than swapped on faith.

### 4. Flow: bounded recall, deduplicate, then rerank

```text
issue + logs
  -> FTS over doc_chunks + pinmux_pins + mic741_chunks   (prefix-aware)
  -> ts_rank, keep top 40                                (recall cap)
  -> deduplicate near-identical candidates
  -> cross-encoder rerank, fp16                          (bge-reranker-v2-m3)
  -> top 10 -> rendered into the prompt
```

The recall cap exists because a cross-encoder scores every (query, candidate) pair
individually — about 100 ms each. **40 was chosen from the measurement above**: it
costs ~4 s, where 100 costs ~8 s and reranking all 674 candidates would cost over a
minute. Four seconds is acceptable inside a repair that already takes minutes; eight
is not worth double the wait for candidates `ts_rank` placed 41st or lower.

**Deduplication is required, not cosmetic.** The benchmark's top four results held
only two distinct documents. Collapse near-identical candidates before reranking —
compare on normalized content (a hash of whitespace-collapsed text, plus a
similarity check for chunks that differ only by a page boundary), keeping the
highest-ranked instance and its page range. Without this, a table spanning two pages
silently costs two of the ten slots the agent gets.

fp16 is the default dtype: it halved latency with no observed quality change.

### 5. Dense retrieval is still not adopted

No embeddings, no pgvector. The evidence above says the failure mode is ranking, not
retrieval breadth, and the one measured recall failure (symbol families) is fixed by
a prefix query rather than by semantics. Dense earns its place when a real repair
misses because the issue and the document share meaning but no vocabulary — most
plausibly an issue written wholly in Chinese. Until such a miss is observed, the
cost (pgvector, an embedding model, re-ingesting every chunk, query-time embedding)
buys nothing measurable.

## Configuration

```env
DOC_RETRIEVAL_ENABLED=false          # default off until verified end to end
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_DEVICE=auto                 # auto | mps | cuda | cpu
RERANKER_DTYPE=float16               # ~2x faster than float32, no quality change observed
RERANK_CANDIDATE_LIMIT=40            # measured: ~4s; 100 costs ~8s
RERANK_TOP_K=10                      # what reaches the prompt
RERANK_BATCH_SIZE=32
```

## Consequences

The agent can finally reach the board facts ingested in ADR-0021, and ranking moves
off the model that does the repair work onto a model sized for the job — with the
measured behaviour of surfacing pin-level tables ahead of descriptive prose. The
costs are real: `sentence-transformers` pulls in torch (~1–2 GB) and the reranker
weights are another ~2.3 GB, a meaningful addition to a project whose dependencies
were previously light; the ranking stage must stay warm in memory, so the first
query after start-up pays the model load (~3 s observed); and every query now
carries roughly four seconds of reranking. The recall cap means a relevant chunk
ranked 41st or lower by `ts_rank` is invisible to the reranker — the main risk this
design accepts, and the first thing to inspect if retrieval quality disappoints.

## Deferred

- Dense retrieval / pgvector, pending an observed semantic miss.
- A second-stage LLM re-rank over the cross-encoder's top 10, if final ordering
  proves to matter more than the latency it costs.
- BM25 (ParadeDB `pg_search`) in place of `ts_rank` for the recall stage.
- Evaluation: leave-one-case-out over the 21 MIC-741 cases plus page- and cell-level
  golden queries for the documents, comparing `ts_rank` alone, prefix-aware FTS,
  cross-encoder reranking, and the retired LLM re-ranker.
- Whether the reranker weights ship with the project or are fetched on first use.
