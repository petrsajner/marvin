"""Bounded GGUF header inspection; never maps or reads the model weight payload."""
from __future__ import annotations

import re
import struct
from pathlib import Path

FORMATS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
HEADER_LIMIT = 64 * 1024 * 1024


def read_header(path: Path) -> dict:
    with Path(path).open("rb") as f:
        def read(fmt):
            size = struct.calcsize("<" + fmt)
            data = f.read(size)
            if len(data) != size or f.tell() > HEADER_LIMIT:
                raise ValueError("Truncated or oversized GGUF header")
            return struct.unpack("<" + fmt, data)[0]

        def string(keep=True):
            length = read("Q")
            if length > HEADER_LIMIT or f.tell() + length > HEADER_LIMIT:
                raise ValueError("Oversized GGUF string")
            if keep:
                value = f.read(length)
                if len(value) != length:
                    raise ValueError("Truncated GGUF string")
                return value.decode("utf-8")
            f.seek(length, 1)

        def value(kind, keep=True, depth=0):
            if kind in FORMATS:
                result = read(FORMATS[kind])
                return result if keep else None
            if kind == 8:
                return string(keep)
            if kind == 9 and depth < 2:
                element, count = read("I"), read("Q")
                if count > 4_000_000:
                    raise ValueError("Oversized GGUF metadata array")
                if not keep and element in FORMATS:
                    size = struct.calcsize("<" + FORMATS[element]) * count
                    if f.tell() + size > HEADER_LIMIT:
                        raise ValueError("Oversized GGUF metadata array")
                    f.seek(size, 1)
                    return None
                result = [] if keep else None
                for _ in range(count):
                    item = value(element, keep, depth + 1)
                    if keep:
                        result.append(item)
                return result
            raise ValueError(f"Unsupported GGUF metadata type: {kind}")

        if f.read(4) != b"GGUF" or read("I") not in (2, 3):
            raise ValueError("Unsupported GGUF file")
        tensor_count, meta_count = read("Q"), read("Q")
        if tensor_count > 200_000 or meta_count > 100_000:
            raise ValueError("Oversized GGUF header")
        meta = {}
        for _ in range(meta_count):
            key, kind = string(), read("I")
            keep = not key.startswith("tokenizer.")
            result = value(kind, keep)
            if keep:
                meta[key] = result
        tensors = []
        for _ in range(tensor_count):
            name, dims = string(), read("I")
            if not 1 <= dims <= 4:
                raise ValueError("Unsupported GGUF tensor dimensions")
            dimensions = [read("Q") for _ in range(dims)]
            kind, offset = read("I"), read("Q")
            tensors.append({"name": name, "dimensions": dimensions, "type": kind, "offset": offset})
        alignment = meta.get("general.alignment", 32)
        if not isinstance(alignment, int) or alignment < 1 or alignment > 4096:
            raise ValueError("Invalid GGUF alignment")
        data_start = (f.tell() + alignment - 1) // alignment * alignment
        payload_size = Path(path).stat().st_size - data_start
        if payload_size < 0:
            raise ValueError("Truncated GGUF header padding")
        ordered = sorted(tensors, key=lambda x: x["offset"])
        for index, tensor in enumerate(ordered):
            end = ordered[index + 1]["offset"] if index + 1 < len(ordered) else payload_size
            if tensor["offset"] < 0 or end <= tensor["offset"] or end > payload_size:
                raise ValueError("GGUF tensor data is incomplete")
            tensor["bytes"] = end - tensor["offset"]  # includes small alignment padding
        return {"metadata": meta, "tensors": tensors, "header_bytes": data_start}


def model_memory_layout(models_dir: Path, spec: dict) -> dict:
    from harness.model_files import asset_path, local_model_dir
    directory = local_model_dir(models_dir, spec)
    routed = {}
    common = lazy = projector = 0
    meta = {}
    for asset in spec["assets"]:
        path = asset_path(directory, asset["path"])
        header = read_header(path)
        if Path(asset["path"]).name.startswith("mmproj"):
            projector += sum(t["bytes"] for t in header["tensors"])
            continue
        meta.update(header["metadata"])
        for tensor in header["tensors"]:
            match = re.match(r"blk\.(\d+)\.ffn_.*_exps\.weight$", tensor["name"])
            if match:
                layer = int(match.group(1))
                routed[layer] = routed.get(layer, 0) + tensor["bytes"]
            elif tensor["name"] == "per_layer_token_embd.weight":
                lazy += tensor["bytes"]
            else:
                common += tensor["bytes"]
    if meta.get("general.architecture") != "qwen4exp" or len(routed) != 48 or lazy == 0:
        raise ValueError("Flash-Next model header does not match its supported memory layout")
    return {"common_bytes": common, "lazy_bytes": lazy, "projector_bytes": projector,
            "expert_layer_bytes": [routed[i] for i in range(48)]}
