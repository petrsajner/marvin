"""Write requirements-strata-py312.lock: Strata's Python packages with their PyPI SHA-256.

The versions are those Strata v0.1.39's requirements.txt pins for Python 3.12 on
Windows, plus the two CUDA wheels its setup installs. cmake and ninja only serve a
source build of the engine, which Marvin does not do. Run after changing a pin:

    python scripts/lock_strata_dependencies.py
"""
from __future__ import annotations

from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "requirements-strata-py312.lock"
PINS = {
    "numpy": "2.5.3", "jinja2": "3.1.6", "markupsafe": "3.0.3", "regex": "2026.9.10", "pyyaml": "6.0.3",
    "tqdm": "4.70.1", "colorama": "0.4.6", "requests": "2.34.2", "certifi": "2026.7.22",
    "charset-normalizer": "3.5.1", "idna": "3.20", "urllib3": "2.8.0", "pillow": "12.3.0", "psutil": "7.2.2",
    "nvidia-cublas": "13.0.2.14", "nvidia-cuda-runtime": "13.0.96",
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
    lines = ["# Strata v0.1.39's Python packages for Windows x64 / Python 3.12, installed with",
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
