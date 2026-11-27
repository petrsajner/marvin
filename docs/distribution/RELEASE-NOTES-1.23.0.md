## What's New in Marvin 1.23.0

This release makes Marvin faster, smarter with long projects, and noticeably more reliable during everyday coding and document work — while keeping the same local single-model setup, instant interruption/steering, and full feature set.

- **Faster replies with less wasted context:**
  - Related internal tools (browser inspection/interaction, task planning, memory, context, and project info) are now grouped cleanly, cutting tool overhead by roughly a third (~1,500 tokens saved on every request) without removing a single capability.
  - Marvin no longer re-sends repeated internal instructions or breaks the model's reasoning flow mid-task, so prompt caching works much better and follow-up steps feel snappier.
- **Longer memory in big projects without losing details:**
  - Before summarizing older parts of a long chat, Marvin first hides only old, bulky tool outputs (such as huge file reads or long command logs) while keeping your conversation, recent work, memories, project decisions, and task plan untouched.
  - Full original outputs always stay saved in your chat history and can be read back anytime.
  - Memory management can now update or remove outdated facts directly and automatically avoids duplicate entries.
- **More reliable file editing and error recovery:**
  - Patching files tolerates minor whitespace, line-ending, and indentation differences safely, protects against accidentally overwriting external edits, returns a compact diff on success, shows the closest matching lines on failure, and validates `.toml` and `.xml` syntax before saving.
  - Built-in safeguards automatically recover if a local model gets stuck repeating itself while thinking or leaks raw tool tags into plain text.
  - Reading huge files defaults to a sensible 400-line window with clear continuation coordinates instead of flooding the context at once.
- **Accurate setup awareness and live cache stats:**
  - The model now always knows your actual selected model, detected GPU/RAM, and chosen UI language instead of hardcoded workstation assumptions.
  - The **Context** panel now displays **Prompt cache** hit-rate and the count of **Masked tool outputs**, so you can immediately see how efficiently the model is reusing context.
  - Faster incremental code indexing, broader multi-language project maps, `.gitignore`-aware search fallback, and smarter error extraction from long shell logs.

## Downloads & Updating

- **`Marvin-Setup-Full.exe`**: complete self-contained installer — private Python 3.12, locked packages, validated `llama.cpp v1.0.0 (b12359)`, offline Strata `0.2.17`, offline Infernix `2026.11.20`, and offline WebView2. Only model weights are downloaded when not already on disk.
- **`Marvin-Setup-Minimal.exe`**: lightweight installer (requires separately installed 64-bit Python 3.12); downloads packages, `llama.cpp`, and missing selected weights automatically.
- Updating over an existing installation keeps all conversations, projects, memories, skills, and downloaded models intact.
- See [SHA256SUMS.txt](https://github.com/petrsajner/marvin/releases/download/v1.23.0/SHA256SUMS.txt) and the updated English / Czech PDF manuals included in this release.
