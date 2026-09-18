# Harness parity roadmap - where Marvin stands against comparable tools

18 September 2026, status verified against the tree at 1.11.1 (`v1.11.1`,
`423c0251`). Compared against Open WebUI / AnythingLLM, Aider, Continue, Cline and
Claude Code.

The goal is parity in what a good harness can do, along two axes that carry equal
weight:

1. **Capability** - the harness can do the work.
2. **Legibility** - a user can find the capability and reach it in the interface.

**The target user is not a programmer.** This is the single most important
constraint in this document, and it is what makes Marvin's priorities differ from
a straight feature-parity list: every competitor above is aimed at developers, so
copying their ordering would optimise for the wrong person.

## Boundaries

[AGENTS.md](../../AGENTS.md) records permanent non-goals. They are treated here as
fixed constraints, not as gaps:

- No LSP runtime or language-server distribution layer.
- No persistent interactive terminal as a primary workflow.
- No parallel model agents, subagents or multi-model orchestration.
- No one-million-token context profiles.
- No general plugin host, MCP ecosystem or broad integration framework.

Most of these align with the targeting rather than fighting it: LSP, terminals and
agent fleets are developer concerns. The two that a feature comparison will keep
raising are parallel agents and MCP, because competitors market them heavily.
Reversing either is an owner decision and out of scope for this roadmap.

## Where Marvin already leads

Comparable tools generally do not have these, and they are the backbone worth
extending rather than replacing:

- Measured VRAM profiles with a recovery ladder that lowers context only, never
  silently changing model or cache precision.
- MTP speculative profiles (2-3x generation) with a pinned, verified draft model.
- Offline installer plus a portable, SHA-256 verified backup of weights, runtime
  and dependencies.
- Mode-aware context compression that preserves what each work mode needs.
- Research ledger with citation coverage checking.
- Cross-chat decision ledger.
- In-place DOCX editing that preserves formatting.
- Computer control.
- Retrieval from the user's own history after compression.
- Visible tok/s and real context accounting.

Reliability and model management are the strongest areas. Further investment there
pays off only where something is plainly missing.

## Delivered

Recorded so the roadmap does not silently go stale. All of this landed on
18 September 2026 and is verified in the tree:

| Capability | Where | State |
|---|---|---|
| Semantic search over files and history | `semantic_index.py`, `tools/semantic.py`, `embedding_server.py`, [design](semantic-search.md) | Released in 1.11.0 (`6f4bdff`) |
| Diff viewer with per-file restore | `changes.py:file_diff`, diff dialog, restore-point drift | `16dd993`, made reachable in `02a9a3c` |
| Per-task Git auto-commit | `application.py:_maybe_autocommit`, `projects.py:set_autocommit` | `77e0e1c`, `4b04c1a`, `49976f8` |
| Project checks with agent repair | `project_checks.py`, Project status panel | `3cb3cf2`, corrected in `02a9a3c` and `e21ae01` |

Semantic search shipped close to the original proposal - a CPU-only sidecar beside
the main model, a vector index next to FTS5, hybrid merge - with two deviations
worth remembering: the model is 635 MB rather than the estimated 0.1-0.5 GB, and
**there is no rerank stage**; results are merged and labelled, not re-scored.

A synthetic evaluation battery was built and then removed (`69e305e` to `c841804`).
That was a change of requirement, not a failure: the owner wanted testing and
repair on real projects, not the harness exercising itself against fixtures, and
project checks cover that. If a regression battery is wanted later, it should run
against real project workspaces for the same reason.

## Remaining gaps

Verified against the tree, not assumed.

| # | Gap | Current state |
|---|---|---|
| A | Tool discoverability | **Missing.** See below - the largest gap for this target. |
| B | Voice input (dictation) | **Missing.** No speech path anywhere in the tree. |
| C | Live document preview while writing | **Partial.** Document and HTML preview exist; nothing renders while the user writes. |
| D | Unified global search | **Partial.** `/api/search` covers chats only; files, memory and decisions are reached separately. `semantic_search` spans files and history but only as a model tool. |
| E | Command palette | **Missing.** No keyboard-driven action launcher. |
| F | Usage analytics | **Partial.** Current context estimate, measured tokens of the last request and live tok/s; no history and no per-chat or per-project totals. |
| G | Exposed OpenAI-compatible endpoint | **Missing.** `server.host` and `web.host` are `127.0.0.1` in config with no switch. |

### A. Tool discoverability is the real gap

The harness registers this many tools per work mode:

| Work mode | Tools |
|---|---:|
| Discussion, Research | 33 |
| Writing | 37 |
| Development | 68 |
| Computer | 75 |

A non-programmer has no way to learn that seventy-five capabilities exist. The
model sees them; the user does not. Today the only user-facing catalogue is the
optional skills list and the manual.

This is axis 2 of the goal, it is absent from a straight feature comparison
because every competitor assumes a developer who reads documentation, and it is
worth more to this target than any single remaining feature. A command palette (E)
is one component of a solution, not the solution.

## Priority for this target

This ordering deliberately differs from a developer-oriented comparison. The
reasoning is recorded so it can be argued with later.

1. **Tool discoverability (A).** Directly serves axis 2 and the stated user. The
   capability already exists and is being wasted.
2. **Voice input (B).** The remaining capability gap that most favours a
   non-programmer, and no local competitor offers it.
3. **Live document preview (C).** Writing is the non-programmer's mode; it is the
   place where feedback while working matters most.
4. **Unified search (D)** and **command palette (E).** Both reduce "where do I
   find this", which is the same problem as A from a different direction.
5. **Usage analytics (F)** and **exposed endpoint (G).** Deferred. Analytics serve
   a power user; the endpoint serves other tools, not this user. Neither is wrong,
   both are for a different audience.

Auto-commit was ranked high in the original comparison as a cheap professional
touch. It shipped, and it was worth shipping, but it is worth noting that the
argument for it was explicitly "high value for developers" - the opposite of this
document's target. Future items should not inherit that bias unexamined.

## Deliberately excluded

Recorded so they are visibly decisions rather than oversights:

- **Docker sandboxing** (OpenHands). Marvin runs on a personal machine by design;
  supervised mode and restore points are the substitute.
- **MCP ecosystem** (Cline). Permanent non-goal.
- **IDE integration** (Cursor, Continue). Marvin has its own workspace UI and
  symbol index; LSP distribution is a permanent non-goal.

## Keeping this document true

Every "state" column above was checked against the tree, not recalled. Before
acting on this roadmap, re-check the specific item: the gaps that closed on
18 September closed within hours of the comparison that identified them, and the
same can happen again.
