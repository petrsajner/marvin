"""Pinned optional model specifications, reusable by setup and isolated validation."""

# Qwen3.8-Flash-Next on the Strata engine (docs/design/2026-10-05-strata-backend.md).
# Strata has no K-quant expert kernels, so it needs ISTA-DASLab's GSQ-RCO files
# instead of Unsloth's. It replaced the llama.cpp entry once it was qualified
# (owner, 2026-10-07). Paths are relative to paths.strata_data_dir,
# laid out as Strata's own data folder (models/, packs/, mtp/), so a folder that
# Strata's setup prepared can be used as it is.
#
# The engine is an implementation detail: names and labels describe the model
# and its weights only, so switching to it looks like switching any other model.
FLASH_NEXT_STRATA = {
    "backend": "strata",
    "alias": "Qwen3.8-Flash-Next IQ3_S (85 GB, text and vision)",
    "status_label": "Qwen 3.8 Flash-Next · IQ3_S",
    "family": "qwen4exp",
    "repo": "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF",
    "revision": "ed59f92082b1e93c0e96d60a8b11aab089b52f09",
    "download_dir": "models",
    "download_transport": "range",
    "file": "models/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf",
    "mmproj": "models/mmproj-Qwen3.8-Flash-Next-BF16.gguf",
    "assets": [
        {"path": "IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf", "size": 54817524224,
         "sha256": "4c1eb2ceb4915e1192f4f386021897bde56a97f40a0bb78bb86465e0f7d2aca3"},
        {"path": "IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf", "size": 28800138432,
         "sha256": "316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113"},
        {"path": "mmproj-Qwen3.8-Flash-Next-BF16.gguf", "size": 907543008,
         "sha256": "b1a82259702816a5330d7bd7607cd9676b11780e79ff7348c21103ff3ce49bd0"},
    ],
    "optional_download": True,
    "vision": True,
    # Every expert stays in RAM; the GPU holds the dense weights and an expert cache.
    "uses_system_ram": True,
    # Strata reads an image in at most 1,024 tokens by default; the calibration
    # from each answer's usage corrects the estimate per conversation.
    "image_tokens": 1024,
    "read_timeout": 1800,
    "sampling": {
        "thinking": {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "presence_penalty": 0.0},
        "non_thinking": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5},
    },
    "strata": {
        "version": "0.1.39",
        "model_name": "qwen3.8-flash-next-iq3_s",
        # The n-gram (PLE) table, read lazily from the SSD.
        "ple_gguf": "models/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf",
        "pack": "packs/iq3_s",
        "mtp": "mtp/rt",
        "expert_profile": "data/expert-profile.bin",   # relative to paths.strata_dir
        "kv": "int8",
        "spec": 4,
        "spec_min_p": 0.5,
        "vision": "gpu",
        "vision_max_tokens": 1024,
        "vram_reserve_mib": 700,
        "resident_experts": False,
        # A per-request effort change then keeps the cached prompt.
        "effort_position": "end",
    },
}

# The same model with IQ2_XS experts: 2-3x faster than IQ3_S on 48 and 32 GB of
# RAM, at a cost in weight quality the user takes on knowingly (owner,
# 2026-10-07; docs/design/strata-qualification-2026-10-07.md). The second shard
# and the projector are IQ3_S's files: a download links them instead of fetching
# them again, and its own receipt keeps the two entries from unverifying each other.
FLASH_NEXT_STRATA_IQ2 = {
    **FLASH_NEXT_STRATA,
    "alias": "Qwen3.8-Flash-Next IQ2_XS (69 GB, text and vision, faster on smaller PCs)",
    "status_label": "Qwen 3.8 Flash-Next · IQ2_XS",
    "receipt": ".marvin-verified-iq2_xs.json",
    "file": "models/IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf",
    "assets": [
        {"path": "IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf", "size": 39225954592,
         "sha256": "92cee27ae5bbadcd732416a0f7a7f0acc092399dbbe8f5a5efa707c2ec0a49d7"},
        {"path": "IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00002-of-00002.gguf", "size": 28800138432,
         "sha256": "316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113"},
        {"path": "mmproj-Qwen3.8-Flash-Next-BF16.gguf", "size": 907543008,
         "sha256": "b1a82259702816a5330d7bd7607cd9676b11780e79ff7348c21103ff3ce49bd0"},
    ],
    "strata": {
        **FLASH_NEXT_STRATA["strata"],
        "model_name": "qwen3.8-flash-next-iq2_xs",
        "ple_gguf": "models/IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00002-of-00002.gguf",
        "pack": "packs/iq2_xs",
    },
}

# Auxiliary draft model for the speculative ("MTP") q4/q5 profiles. Selected via
# a profile, never a standalone model entry; same upstream repository as the
# Qwen3.8-27B weights so the tokenizer matches the target models exactly.
QWEN27B_MTP_DRAFT = {
    "alias": "Qwen3.8-27B MTP draft model (1.3 GB, speculative decoding)",
    "repo": "unsloth/Qwen3.8-27B-GGUF",
    "revision": "4ca720788d1e01f1bff70c033e0d0028fd02e502",
    "download_dir": "Qwen3.8-27B",
    "download_transport": "range",
    "optional_download": True,
    "assets": [
        {"path": "MTP/mtp-Qwen3.8-27B-Q4_0.gguf", "size": 1369590656,
         "sha256": "50d9ce5a6da381bbcfb31061cf73df94a90e6faf8efeddee379a9cb8f1501c6e"},
    ],
}

# Speech recognition for dictation, run by whisper-cli on the CPU. Measured on
# FLEURS cs_cz: 11.4% word error rate, 3.9 s per utterance. The full large-v3
# scored identically on the same clips and took 6.1 s, so turbo is the only one
# shipped - see docs/design/voice-input.md.
SPEECH_WHISPER_TURBO = {
    "alias": "Whisper large-v3-turbo Q5_0 (547 MB, dictation, CPU only)",
    "repo": "ggerganov/whisper.cpp",
    "revision": "5359861c739e955e79d9a303bcbc70fb988958b1",
    "download_dir": "Speech",
    "download_transport": "range",
    "optional_download": True,
    "assets": [
        {"path": "ggml-large-v3-turbo-q5_0.bin", "size": 574041195,
         "sha256": "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2"},
    ],
}

# Voice activity detection. Not optional: without it, silence and faint hiss are
# both transcribed as an invented Czech subtitle credit.
SPEECH_SILERO_VAD = {
    "alias": "Silero VAD v5.1.2 (speech detection for dictation)",
    "repo": "ggml-org/whisper-vad",
    "revision": "9ffd54a1e1ee413ddf265af9913beaf518d1639b",
    # Its own directory: the download receipt is per directory, so two specs
    # sharing one would each report the other's as unverified.
    "download_dir": "Speech/vad",
    "download_transport": "range",
    "optional_download": True,
    "assets": [
        {"path": "ggml-silero-v5.1.2.bin", "size": 885098,
         "sha256": "29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf"},
    ],
}

# CPU-only embedding model for semantic search. Served by a dedicated
# llama-server sidecar with -ngl 0; never registered as a selectable model.
EMBEDDINGS_BGE_M3 = {
    "alias": "bge-m3 Q8_0 embedding model (635 MB, semantic search, CPU only)",
    "repo": "gpustack/bge-m3-GGUF",
    "revision": "2d48f1737679ad900d5c26c5aad5410e9c70fdca",
    "download_dir": "Embeddings",
    "download_transport": "range",
    "optional_download": True,
    "assets": [
        {"path": "bge-m3-Q8_0.gguf", "size": 634553760,
         "sha256": "950f4a8e5e19477a6d3c26d2f162233c20002c601f75e4b002e3239997821167"},
    ],
}
