"""Write requirements-strata-py312.lock: Strata's Python packages with their PyPI SHA-256.

The versions are those Strata v0.2.17's terminal/requirements.txt pins for Python 3.12
on Windows. Strata engine 0.1.63 bundles cublas64_13.dll and cublasLt64_13.dll in the
portable engine tarball, so NVIDIA CUDA pip wheels are no longer required. Run after
changing a pin:

    python scripts/lock_strata_dependencies.py
"""
from __future__ import annotations

from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "requirements-strata-py312.lock"
PINS = {
    "numpy": "2.5.3", "jinja2": "3.1.6", "markupsafe": "3.0.3", "regex": "2026.9.10", "pyyaml": "6.0.3",
    "tqdm": "4.70.1", "colorama": "0.4.6", "requests": "2.34.2", "certifi": "2026.10.19",
    "truststore": "0.10.5", "charset-normalizer": "3.5.1", "idna": "3.20", "urllib3": "2.8.0",
    "pillow": "13.0.0", "psutil": "7.2.2",
}


def fits(filename: str) -> bool:
    """A wheel that Python 3.12 on 64-bit Windows can install."""
    if not filename.endswith(".whl"):
        return False
    python, abi, platform = filename[:-4].split("-")[-3:]
    return (platform in ("any", "win_amd64")
            and any(tag in python.split(".") for tag in ("py3", "cp312", "cp37", "cp38", "cp39", "cp310", "cp311"))
            and abi in ("none", "abi3", "cp312"))


def main() -> int:
    lines = ["# Strata v0.2.17's Python packages for Windows x64 / Python 3.12, installed with",
             "# pip install --require-hashes --no-deps (scripts/lock_strata_dependencies.py)."]
    for name, version in PINS.items():
        release = requests.get(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30)
        release.raise_for_status()
        digests = sorted(item["digests"]["sha256"] for item in release.json()["urls"] if fits(item["filename"]))
        if not digests:
            raise SystemExit(f"{name}=={version} has no wheel for Python 3.12 on Windows x64")
        lines.append(f"{name}=={version} \\")
        lines += [f"    --hash=sha256:{digest}" + (" \\" if i < len(digests) - 1 else "")
                  for i, digest in enumerate(digests)]
    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {TARGET} ({len(PINS)} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
