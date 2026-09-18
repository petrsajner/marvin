# Semantic search — hybrid vector + keyword retrieval

18 September 2026. Fills the biggest gap identified in the harness roadmap: every
competitor harness offers embedding-based retrieval; Marvin had only FTS5
keywords and symbols.

## Choices

- **Model: bge-m3 Q8_0** (`gpustack/bge-m3-GGUF`, revision `2d48f173…`, 634,553,760 bytes,
  SHA-256 `950f4a8e…`). Best multilingual quality (Czech verified below), 1024-dim
  embeddings, 8k-token context, no query/passage prefixes. Embeddings are
  quantization-sensitive, hence Q8_0 over smaller quants.
- **CPU-only sidecar** (`harness/embedding_server.py`): a second llama-server with
  `-dev none --embeddings -b 1024 -ub 1024` on port 8091. `-dev none` is essential:
  `-ngl 0` still creates a CUDA context (~0.5 GiB VRAM); `-dev none` measures zero
  GPU usage. Started lazily on the first search, stopped on application close and
  via atexit. Own pid file with exe+port validation so it is never confused with
  the main server. Measured: ~0.9 GiB RSS, 48 CPU threads, start in ~7 s, ~57 short
  texts/s or ~5 long chunks/s (~600-token Czech chunks).
- **Opt-in**: off by default. The `semantic_search` setting downloads the model on
  first enable (background thread, pinned machinery with SHA-256 receipt); the
  tool returns guidance when disabled so the model can inform the user.

## Indexes (`harness/semantic_index.py`)

- Per-workspace `runtime/indexes/<key>.vectors.sqlite3` mirrors the FTS5 key
  convention; history vectors live in `sessions/semantic-index.sqlite3`. WAL,
  short-lived connections, mtime/size incremental state — the same conventions as
  `file_index`/`history_index`. Vectors are stored normalized float16; similarity
  is a dot product in numpy (no new dependencies beyond numpy, which the lock
  already carried).
- Chunking: blank-line blocks packed to ~1500 chars with 150-char overlap; files
  over 2 MB and binary content skipped; history indexed per user/assistant
  message with internal protocol prefixes excluded.
- A background daemon thread (`semantic-indexer`) indexes on demand; the tool
  gives it a bounded head start (8 s) and reports building progress. Deletions
  are pruned even when nothing else changed.

## Tool

`semantic_search(query, scope=files|history|both, max_results)` — registered in
every work mode, SAFE/parallel. Results are labeled `[semantic score]` /
`[keyword]` and merged with FTS5 hits from the same query (files deduped by
path, history by session).

## Validation

- 5 unit tests (mock embeddings): chunking, incremental file indexing with
  prune, history filtering/dedup, tool disabled/enabled paths, settings
  validation and state wiring. Full suite: 368 core checks, 117 service tests.
- Real sidecar: a Czech query asking how repeated attempts are handled when a
  request fails scored 0.59/0.68 against Czech/English retry documentation and
  0.29 against an irrelevant Czech text — cross-lingual retrieval works. Over the
  shipped manuals, a Czech query about context/memory retrieved the English
  compression section (0.56) and an English query retrieved the
  project-deletion section (0.63). GPU usage unchanged while the sidecar runs.

## Non-goals kept

The sidecar is infrastructure like llama-server itself, not a second agent: it
never generates, never touches the GPU, and the sequential single-agent loop is
unchanged.
