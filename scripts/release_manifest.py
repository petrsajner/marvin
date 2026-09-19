"""Write the release manifest from the staged assets, so it cannot drift.

The manifest records what a release actually published: every asset, its size, its
SHA-256 and the stable URLs. It used to be typed by hand, which is exactly the
kind of thing that ends up disagreeing with the files.

    python scripts/release_manifest.py --commit <sha>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER_REPO = "petrsajner/marvin"


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=None, help="defaults to installer/version.txt")
    parser.add_argument("--commit", default=None, help="defaults to the current HEAD")
    args = parser.parse_args()

    version = args.version or (ROOT / "installer/version.txt").read_text(encoding="utf-8").strip()
    commit = args.commit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    staged = ROOT / "dist" / f"release-{version}"
    if not staged.is_dir():
        raise SystemExit(f"Run scripts/package_distribution.ps1 first: {staged}")

    tag = f"v{version}"
    base = f"https://github.com/{OWNER_REPO}/releases/download/{tag}/"
    latest = f"https://github.com/{OWNER_REPO}/releases/latest/download/"
    assets = []
    for path in sorted(staged.iterdir()):
        if not path.is_file():
            continue
        assets.append({
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "url": base + path.name,
            "latest_url": latest + path.name,
        })
    manifest = {
        "version": version,
        "tag": tag,
        "application_commit": commit,
        "release_url": f"https://github.com/{OWNER_REPO}/releases/tag/{tag}",
        "assets": assets,
    }
    target = ROOT / "docs" / "distribution" / f"release-{version}.json"
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {target.relative_to(ROOT)} with {len(assets)} assets")
    for asset in assets:
        print("  %-26s %10.1f MB  %s" % (asset["name"], asset["bytes"] / 1048576,
                                         asset["sha256"][:16]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
