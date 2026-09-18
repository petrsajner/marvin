# Marvin 1.11.0 - semantic search

Released on 18 September 2026. The first item of the approved harness roadmap:
hybrid semantic retrieval over project files and chat history, powered by a
pinned CPU-only embedding model.

## What's new

- **`semantic_search` tool** (every work mode): retrieves project files and past
  conversations by meaning — Czech and English, paraphrases included — labeled
  `[semantic score]` / `[keyword]` and merged with the existing FTS5 keyword
  results. A background thread builds the indexes; the tool reports progress.
- **bge-m3 Q8_0 embedding sidecar** (635 MB, SHA-256 pinned, downloaded on first
  enable): a dedicated llama-server with `-dev none --embeddings` on port 8091 —
  strictly CPU (measured zero GPU usage; `-ngl 0` would still allocate a CUDA
  context), ~0.9 GiB RSS, ~57 short texts/s. Started lazily, stopped on close.
- **Opt-in setting** (Settings > Model and device): off by default, no surprise
  downloads; the tool guides the model to tell the user when disabled.
- Vector stores follow the existing index conventions (per-workspace SQLite
  beside the FTS5 index, history store in the sessions directory, mtime/size
  incremental, float16 normalized vectors, numpy similarity — no new
  dependencies beyond numpy, already in the lock).

Design and measurements: [docs/design/semantic-search.md](../design/semantic-search.md).
Cross-lingual spot checks: a Czech query about retries scored 0.59/0.68 on
Czech/English documentation and 0.29 on an unrelated Czech text; over the
shipped manuals a Czech query retrieved the English context-compression section.

## Validation

- 368 core checks (registry golden table updated) and 117 service tests
  (5 new: chunking, incremental indexing with prune, history filtering, tool
  disabled/enabled paths, settings wiring) in the source checkout; React build
  and both manuals rebuilt.
- Real-sidecar validation on the workstation: receipt-verified model reuse,
  Czech/English retrieval quality, GPU usage unchanged while running, clean
  start/stop including the atexit path.
- Actual Full upgrade of the owner's installation (exit 0; the second build after
  raising the sidecar's physical batch to 2048 so long Czech history chunks
  embed without errors). The installed copy passed all 117 service tests
  (three source-only tests skipped). With the setting enabled, the pre-seeded
  embedding model was receipt-verified in 0.4 s, the full 14-session chat
  history indexed in 86 s on CPU, and a Czech query about placing the draft
  model in RAM retrieved the relevant analysis session as the top hit (0.54)
  with GPU usage unchanged.

| Artifact | Bytes | Actual upgrade |
|---|---:|---|
| Minimal | 53,475,646 | built; not installed this time |
| Full | 940,756,670 | Exit 0 |
