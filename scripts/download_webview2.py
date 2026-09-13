"""Cache and verify Microsoft's redistributable WebView2 installers for release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.webview_runtime import payload_valid

SOURCES = {
    "bootstrapper": ("MicrosoftEdgeWebview2Setup.exe", "https://go.microsoft.com/fwlink/p/?LinkId=2124703"),
    "standalone": ("MicrosoftEdgeWebView2RuntimeInstallerX64.exe", "https://go.microsoft.com/fwlink/p/?LinkId=2124701"),
}


def microsoft_signature(path: Path) -> dict:
    script = ("$ErrorActionPreference = 'Stop'; "
              "$s = Get-AuthenticodeSignature -LiteralPath $env:MARVIN_WEBVIEW_PAYLOAD; "
              "[pscustomobject]@{status=$s.Status.ToString(); subject=$s.SignerCertificate.Subject; "
              "thumbprint=$s.SignerCertificate.Thumbprint} | ConvertTo-Json -Compress")
    env = {**os.environ, "MARVIN_WEBVIEW_PAYLOAD": str(path)}
    # A PowerShell 7 parent can export module paths incompatible with Windows PS.
    env = {key: value for key, value in env.items() if key.upper() != "PSMODULEPATH"}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            env=env,
                            capture_output=True, text=True, check=True, creationflags=0x08000000)
    signature = json.loads(result.stdout)
    if signature["status"] != "Valid" or "CN=Microsoft Corporation," not in signature["subject"]:
        raise ValueError(f"Not a valid Microsoft-signed payload: {path.name}: {signature}")
    return signature


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Explicitly pin the current Microsoft release")
    args = parser.parse_args()
    manifest_path = ROOT / "installer/webview2.json"
    cache = ROOT / "runtime/webview2"
    cache.mkdir(parents=True, exist_ok=True)
    manifest = {} if args.refresh else json.loads(manifest_path.read_text(encoding="utf-8"))
    for kind, (filename, source) in SOURCES.items():
        target = cache / filename
        item = manifest.get(kind)
        if args.refresh or not payload_valid(target, item):
            temporary = target.with_suffix(".download")
            try:
                with urllib.request.urlopen(source if args.refresh else item["url"], timeout=60) as response:
                    resolved = response.url
                    with temporary.open("wb") as output:
                        shutil.copyfileobj(response, output, 1024 * 1024)
                if not args.refresh and not payload_valid(temporary, item):
                    raise ValueError(f"Pinned payload checksum mismatch: {filename}")
                signature = microsoft_signature(temporary)
                with temporary.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                if args.refresh:
                    manifest[kind] = {"filename": filename, "source": source, "url": resolved,
                                      "size": temporary.stat().st_size, "sha256": digest,
                                      "signature": signature}
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        microsoft_signature(target)
        print(f"[WEBVIEW2] Verified {filename}: {target.stat().st_size} bytes", flush=True)
    if args.refresh:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(manifest_path, cache / "webview2.json")


if __name__ == "__main__":
    main()
