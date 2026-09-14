# NInfer evaluation and deferred roadmap

Research date: 6 September 2026. Target: Qwen 3.8 27B Q5_K_M on an NVIDIA RTX 5090 with 32 GB VRAM. Implementation is deferred.

This historical research note records the assessment made on that date. Third-party capability and performance claims below were not revalidated during the September 15 source-language cleanup; they are not local benchmark results.

## Proposed value

The assessment described `Neroued/ninfer` as a specialized C++/CUDA inference engine targeting Blackwell `sm_120a`, particularly the RTX 5090. Reported community throughput of 200–500+ tokens/s was attributed to native NVFP4 tensor-core acceleration, MTP speculative decoding, fused CUDA kernels, CUDA Graphs with fixed allocations, and quantized KV caches (INT8 or specialized 4-bit formats).

An OpenAI-compatible `/v1/chat/completions` server could theoretically connect to Marvin's LLMClient. API compatibility alone would not establish behavioral compatibility.

## Reasons not to adopt it at the time

- **Model format:** Marvin's downloaded models are GGUF, including Qwen Q5/Q4/IQ3 and Ornith. The evaluated NInfer path required separate `.ninfer` packages such as `neroued/Qwen3.8-27B-nvfp4-NInfer`; the existing weights could not be reused directly. This is a file-format constraint, not a statement about the repository's license.
- **Precision:** the user prioritized Q5 reasoning quality. The investigated acceleration paths used NVFP4 or groupwise INT4 and offered no equivalent Q5 profile. Anecdotal reports of structured-output/tool-call inaccuracies did not establish a controlled quality comparison with Q5_K_M.
- **Windows:** the assessed upstream targeted 64-bit Linux. Community Windows forks such as `natpate/ninfer-windows` were experimental.
- **Vision:** support was considered immature relative to Marvin's existing screenshot, clipboard-image and PDF workflows using a separate projector.

## Conditions for reassessment

1. A suitable precision format, such as FP8 or a validated 5–6-bit option, that preserves the required reasoning and structured-output behavior.
2. A stable Windows binary distribution without relying on an experimental fork.
3. Demonstrated vision and tool-calling parity on Marvin's actual workflows.

llama.cpp / llama-server with CUDA remains the adopted backend. For the original target, Qwen Q5_K_M with Q8_0 KV remains the reference. This note does not authorize downloads, integration or automatic monitoring.
