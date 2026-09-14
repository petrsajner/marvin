# Marvin on macOS: technical assessment

13 September 2026, source version 1.8.0. This is a scope assessment, not implementation approval or a claim of Mac compatibility.

## One product with two platform layers

React/TypeScript, FastAPI, ApplicationService, the sequential agent loop, history, projects, context compression and most document tools can remain shared. A permanent product fork is unnecessary.

The current application cannot simply be recompiled: its launcher uses Win32/WebView2, process management passes Windows creation flags, file opening uses `os.startfile`, GPU detection uses `nvidia-smi`, and runtime/Python discovery assumes Windows paths and extensions. These operations need a platform layer separate from application logic.

## Runtime and models

Start with llama.cpp ARM64 and Metal, retaining the HTTP API, chat templates and GGUF format. A different operating system does not inherently require different model files. Every architecture, quantization, vision projector and KV type must nevertheless be qualified on Metal; CUDA support is insufficient evidence. [llama.cpp Metal](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#metal-build).

MLX could be investigated later, but a second API and model format are unnecessary for the first port.

## Memory and performance

Apple Silicon shares memory between CPU and GPU. A Windows machine with 64 GB RAM plus 32 GB VRAM is not equivalent to a Mac with 64 GB unified memory. The Mac needs one budget for weights, KV, working buffers and the operating system, respecting GPU limits and memory pressure. [Apple unified memory](https://developer.apple.com/documentation/metal/mtldevice/hasunifiedmemory).

Model/quantization choices, context sizes, batches, CPU threads, loading modes and caches all need new measurements. Do not copy the Windows Flash-Next `load-mode none`, `no-host` or P-core masks blindly. The measured RTX 5090 throughput of 27 tokens/s and long prefill time do not predict Mac performance.

## Desktop and distribution

pywebview supports Cocoa/WebKit, allowing the React UI to remain shared. Required work includes a private ARM64 Python runtime, a platform dependency lock, launcher, `.app` bundle and separate build/distribution pipeline. Models and mutable data belong outside the signed application, for example in Application Support. [pywebview](https://pywebview.flowrl.com/guide/installation.html#macos), [Apple signing and notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution?language=objc).

Computer mode needs platform-specific screen capture, window control, keyboard handling and permissions. macOS separates Accessibility control permission from screen recording permission. [Accessibility](https://support.apple.com/guide/mac-help/allow-accessibility-apps-to-access-your-mac-mh43185/mac), [screen recording](https://support.apple.com/en-euro/guide/mac-help/mchld6aa7d23/mac).

History and project formats can remain common; absolute paths and platform-specific offline backup contents need portability handling. A Windows Python/DLL backup is not a macOS installer.

## Proposed sequence, if authorized later

1. Isolate platform operations and build manifests while retaining Windows regression tests.
2. On a real Apple Silicon Mac, qualify one existing model with chat, tools, vision, STOP and long context.
3. Establish memory profiles and a desktop package.
4. Qualify Computer mode and the supported model catalog.

The main continuing cost is a second qualification and distribution matrix. A reliable estimate requires a first run on a specific Mac and an agreed minimum memory specification. This work remains deferred.
