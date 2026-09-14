"""Pinned optional model specifications, reusable by setup and isolated validation."""

FLASH_NEXT_Q3 = {
    "alias": "Qwen3.8-Flash-Next Q3 (90 GB, text and vision)",
    "status_label": "Qwen 3.8 Flash-Next · Q3",
    "family": "qwen4exp",
    "repo": "unsloth/Qwen3.8-Flash-Next-GGUF",
    "revision": "38bb39ee97821de2c9009abb7e93950eec396e66",
    "download_dir": "Qwen3.8-Flash-Next",
    "download_transport": "range",
    "file": "Qwen3.8-Flash-Next/UD-Q3_K_XL/Qwen3.8-Flash-Next-UD-Q3_K_XL-00001-of-00003.gguf",
    "mmproj": "Qwen3.8-Flash-Next/mmproj-F16.gguf",
    "assets": [
        {"path": "UD-Q3_K_XL/Qwen3.8-Flash-Next-UD-Q3_K_XL-00001-of-00003.gguf", "size": 10946624,
         "sha256": "f2ef4328929d8b8c8930e2856eef52128dd4ce3425302f04bc3c657431cc4c49"},
        {"path": "UD-Q3_K_XL/Qwen3.8-Flash-Next-UD-Q3_K_XL-00002-of-00003.gguf", "size": 49983253824,
         "sha256": "7d230e7c9421d868b89eebaf23033af0ea1a4e046956df00fb156814fb62346e"},
        {"path": "UD-Q3_K_XL/Qwen3.8-Flash-Next-UD-Q3_K_XL-00003-of-00003.gguf", "size": 39992153376,
         "sha256": "21d4f90f9cd7b7c3a1582667c20cb22f7b03de895b88a23bb20aaeaa44f2c199"},
        {"path": "mmproj-F16.gguf", "size": 904004000,
         "sha256": "1f7b7f0b984cf065c604360c29c8098362ed61b290db0ff12c6f360bb1a8a980"},
    ],
    "optional_download": True,
    # Measured from the verified GGUF tensors, so unsupported PCs can be rejected
    # before downloading 90 GB. Startup still verifies and inspects the real files.
    "layout_hint": {
        "manifest_signature": "2f394e16fcdb970b7a922f93492a55945f90d293311d638c39dbc180479a06f5",
        "layout": {
            "common_bytes": 5351626240,
            "lazy_bytes": 28800138240,
            "projector_bytes": 903984064,
            "expert_layer_bytes": [1782579200 if layer == 2 else
                1533542400 if layer in (4, 30, 46, 47) else 1114112000 for layer in range(48)],
        },
    },
    "runtime_id": "llama-b10935-cuda13.3",
    "minimum_runtime_build": 10935,
    "read_timeout": 1800,
    "adaptive_runtime": True,
    "ctx_size": 262144,
    "kv_cache": "q8_0_256k",
    "kv_cache_profiles": {
        "q8_0_128k": {"cache_type": "q8_0", "ctx_size": 131072, "min_vram_gb": 12,
                      "label": "8-bit - context 128k"},
        "q8_0_192k": {"cache_type": "q8_0", "ctx_size": 196608, "min_vram_gb": 16,
                      "label": "8-bit - context 192k"},
        "q8_0_256k": {"cache_type": "q8_0", "ctx_size": 262144, "min_vram_gb": 24,
                      "label": "8-bit - context 256k"},
    },
    "server_args": ["-fa", "on", "--lazy-mode", "on", "--load-mode", "none", "--no-host"],
    "sampling": {
        "thinking": {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "presence_penalty": 0.0},
        "non_thinking": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5},
    },
}
