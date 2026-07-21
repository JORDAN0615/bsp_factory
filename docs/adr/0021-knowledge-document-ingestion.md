# Knowledge Document Ingestion

Define which vendor hardware documents enter Doc Retrieval and how they are turned
into indexable records. This covers **ingestion only** — the retrieval method
(keyword ranking, dense vectors, fusion) is deliberately left to a later ADR.

Status: **Proposed** on branch `feat/deep-agent-integration`.

## Context

Case Retrieval (ADR-0013/0014/0015) already answers "has something like this been
fixed before?" from past MIC-741 repairs. It does not answer "what does the board
actually specify?" — the pin functions, design rules, and electrical facts a repair
depends on. That is Doc Retrieval, and its corpus (`RAG_DOCS/`, ~98 MB of raw vendor
material) has never been ingested.

Two clarifications shaped the sequencing:

- **Storage and index are orthogonal.** Chunks are stored once; keyword and vector
  search are two *indexes over the same rows*, not a partition of the data. There is
  no "this data goes to keyword, that data goes to dense" split — the same record is
  reachable both ways, and only binaries are excluded outright.
- **Ingestion is prerequisite to, and independent of, the retrieval decision.**
  Whichever ranking method wins, it needs the same chunks. So ingestion is built
  first and cannot be wasted work, while the far more expensive retrieval choices
  stay open until they can be measured.

## Decision

### 1. Scope of the v1 corpus

Ingested:

- The two pinmux templates — `Jetson_Thor_Series_Modules_Pinmux_Template_v1.7.xlsm`
  and `IGX_T5000_Pinmux_Config_Template_v1.2.xlsm`
- `Jetson_Thor_Series_Modules_DesignGuide_DG12084001_v1.3.pdf`
- `Jetson_Thor_Series_Modules_Datasheet_DS-11945-001v1.4.pdf`
- `IGX_T5000_Modules_DesignGuide_DG12265001_v1.0.pdf` and
  `IGX_T5000_Module_SMCU_DesignGuide_DG-12322-001_v1.0.pdf`

Excluded:

- **`Thor-Series-SoC-Technical-Reference-Manual_Debug-and-Trace_DP11881003v0.3.pdf`**
  (21 MB, 2076 pp). It is the *Debug-and-Trace* volume, not the register manual, so
  it is the least relevant document to the pinmux / camera / CAN / ethernet / PCIe
  repairs actually observed — while being by far the largest and the most sensitive
  (an "NVIDIA CONFIDENTIAL" stamp on every page). Cost and exposure are highest
  exactly where value is lowest.
- The MIC-741 BOM (a parts list; no bearing on source changes).
- Binaries (`.ko`, `.bin`, packaged `dpkg` state) — unindexable; retained as path
  citations only.

Deferred: Product Specification, Verification Guide, Thor→IGX Migration guide.

### 2. Pipeline shape: by type, not by file

Two ingesters — one for `.xlsm`, one for PDF — plus a manifest that declares each
file's variation (platform, document version, sheet name, header row). Per-file
bespoke scripts do not scale, and a single universal parser cannot span clean tabular
data and page-layout prose. The manifest exists because the two pinmux templates are
*different template versions* (v1.7 vs v1.2) whose layouts do not necessarily match.

### 3. PDF extraction depth: text **and** tables

Extract prose with PyMuPDF and detect tables with `find_tables()`, emitting tables as
structured records.

Considered and rejected:

- **Text only** — flat extraction was verified to turn a routing table into
  interleaved column soup. Much of a design guide's and a datasheet's value *is* the
  tables (pin descriptions, electrical limits), so this loses the point of ingesting
  them.
- **Full layout extraction (Docling)** — more faithful, but a heavy ML dependency for
  four PDFs. Revisit only if table detection proves insufficient.

### 4. Per-type preprocessing

**Pinmux `.xlsm`** — read values with `openpyxl(data_only=True)`; normalize the merged
multi-row header; emit **one record per pin** (ball, signal name, SFIO mux options,
direction, pull/drive, generated DTSI); tag platform and template version; store the
structured fields (for filtering) alongside a natural-language rendering (for
retrieval). The VBA macro is skipped — it is only the DTSI generator, not knowledge.

**PDF** — extract per page; **strip repeating header/footer/watermark lines** (those
recurring on more than half the pages) before chunking, or every chunk carries
identical noise; tables render only non-empty cells because the detected grid is both
padded and misaligned, and the remaining prose is chunked
section/heading-aware at roughly 512 tokens with 10–20% overlap; every chunk carries
document, page, section path, platform, and version. Figures are recorded as citation
stubs (page plus caption) rather than extracted — schematics yield component-value
noise, and a human can open the page.

**Common** — one chunk-record shape for both ingesters; a `content_hash` so re-ingest
is idempotent; symbol extraction reuses the existing `_extract_symbols`.

### 5. Storage

Postgres, in tables parallel to the case schema (document sources, document chunks,
pinmux pins) rather than mixed into the MIC-741 case tables. One stored copy; indexes
are added by the retrieval ADR.

## Explicitly not decided here

Left open until they can be measured rather than guessed:

- Keyword ranking: keep Postgres `ts_rank`, or adopt real BM25 (ParadeDB `pg_search`
  in the database vs `bm25s` in the application).
- Whether dense retrieval earns its keep at this corpus size, and therefore whether
  pgvector is added. BGE-M3 is the candidate embedding model, chosen for being
  multilingual — issue text is Traditional Chinese while the documents are English,
  so an English-leaning embedder would silently degrade recall.
- The fan-out/fusion/re-rank flow across Case and Doc Retrieval, and its evaluation
  (leave-one-case-out over the 21 MIC-741 cases, plus page- and cell-level golden
  queries for the documents).
- Which of the pinmux template's ~66 columns is authoritative for a pin's *correct*
  function (raw mux columns vs the generated-DTSI columns).

## Consequences

The agent gains access to the board facts its repairs actually depend on, and the
pinmux templates — the cleanest data in the corpus, and the direct cause of the RE-16
pin-reset regression — become queryable ground truth. Excluding the TRM keeps the
largest cost and the sharpest confidentiality exposure out of the system at the price
of losing register-level depth, which can be added later if a real miss demands it.
Table extraction is fiddly and will not be perfect; the fallback is to accept
flattened tables for prose-heavy documents and keep structured parsing for the pinmux
templates and datasheet pin tables.
