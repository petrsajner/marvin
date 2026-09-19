"""Image generation through the OpenArt CLI, when the owner turns it on.

Generating locally is not practical here: the picture models would have to take
turns on the card with the language model, and every swap costs a reload and the
processed prompt with it. So this calls out to a service instead, and it is the
only part of the harness that does.

OpenArt has no REST API and no API key - their own documentation says "there are
no keys to create, rotate, or leak". Access is either their MCP server or their
CLI, and the CLI is what this uses: a single pinned binary, verified against the
checksum the vendor publishes, fetched and run exactly the way llama-server and
whisper.cpp already are. Nothing new is introduced to the architecture.

That choice also settles where a secret lives, by removing the secret. The CLI
signs in through the browser and keeps its own credential in the user profile at
0600; the harness never sees it, never stores it, and it never reaches
config.yaml, an export or a backup. There is nothing here to leak.

Two things this module will not do. It never signs anyone in - `openart login`
opens a browser and the owner completes it, because a program should not be
handling an account holder's credentials on their behalf. And it never generates
without the setting being on, whatever the model asks for.
"""
from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

from harness.config import Config
from harness.i18n import t

RELEASE = "v0.1.1"
# Size and digest as the vendor publishes them in checksums.txt for this tag.
ARCHIVE = ("openart_0.1.1_windows_amd64.zip", 4066696,
           "a480f8ef131c08b60a740bcd55c310e4a2294e63f84189dab5a37cb3b4095691")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CALL_TIMEOUT = 60                # Listing, pricing, account: these answer at once.
GENERATE_TIMEOUT = 420           # A picture takes minutes; the CLI polls for it.

# What the model is told it can ask for. This is a written table rather than a
# live `openart model list` on purpose: the catalogue would then change between
# sessions, and the tool description travels in every request, so a catalogue
# that moves would break the processed prompt exactly the way a changing system
# prompt does. The model can still call `openart model list` through the shell
# if it wants the full catalogue; this is the part worth knowing by heart.
MODELS = (
    ("nano-banana-2", "Google Nano Banana 2. Native 4K, accurate text in the picture, "
                      "realistic people and animals. The general first choice."),
    ("gpt-image-2-5-flare", "OpenAI GPT Image 2.5, speed-first. Top aesthetics, precise "
                            "small text and UI icons. Pick when the wait matters."),
    ("gpt-image-2-5-sunburst", "OpenAI GPT Image 2.5, quality-first. The same price as "
                               "Flare and slower; the strongest editing precision."),
    ("nano-banana-pro", "Google Nano Banana Pro. The specialist for long in-image text "
                        "and for keeping several people consistent."),
    ("byte-plus-seedream-4-5", "Seedream 4.5. Anime and 2D illustration rather than "
                               "photorealism; strong poster and logo layout."),
)
DEFAULT_MODEL = "nano-banana-2"
SAVE_DIRECTORY = "generated-images"      # Inside the current project, per the owner.


# ------------------------------------------------------------------ where it is
def openart_dir(cfg: Config) -> Path:
    return cfg.path("paths.runtime_dir") / "openart"


def openart_cli(cfg: Config) -> Path:
    return openart_dir(cfg) / "openart.exe"


def installed(cfg: Config) -> bool:
    return openart_cli(cfg).is_file()


def enabled(cfg: Config) -> bool:
    """The owner's switch. Off by default, and off means off even when signed in."""
    try:
        return bool(cfg.data.get("openart", {}).get("enabled"))
    except AttributeError:
        return False


def missing(cfg: Config) -> list[str]:
    """What image generation still needs, in words the owner can act on."""
    absent = []
    if not installed(cfg):
        absent.append(t("image generation program (4 MB)"))
    elif not signed_in(cfg):
        absent.append(t("sign-in to OpenArt"))
    return absent


# --------------------------------------------------------------------- install
def install_bytes() -> int:
    return ARCHIVE[1]


def install(cfg: Config, *, progress=print, should_stop=None, on_progress=None) -> None:
    """Fetch the pinned program. Safe to call when it is already there."""
    import requests
    from harness.runtime_update import sha256
    name, size, digest = ARCHIVE
    target = openart_dir(cfg)
    target.mkdir(parents=True, exist_ok=True)
    cache = cfg.path("paths.runtime_dir") / "runtime-archives" / ("openart-" + RELEASE)
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    if not archive.is_file() or sha256(archive) != digest:
        progress(t("Preparing image generation: {name}", name=name))
        partial = archive.with_suffix(".part")
        url = f"https://github.com/OpenArt-AI/cli/releases/download/{RELEASE}/{name}"
        with requests.get(url, stream=True, timeout=(15, 30)) as response, partial.open("wb") as out:
            response.raise_for_status()
            written = 0
            for chunk in response.iter_content(4 * 1024**2):
                if should_stop and should_stop():
                    raise InterruptedError("Image generation setup cancelled")
                out.write(chunk)
                written += len(chunk)
                if on_progress:
                    on_progress(written)
        if partial.stat().st_size != size or sha256(partial) != digest:
            partial.unlink(missing_ok=True)
            raise RuntimeError(t("The downloaded image generation program did not match its checksum."))
        partial.replace(archive)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            if item.is_dir() or not item.filename.lower().endswith("openart.exe"):
                continue
            with bundle.open(item) as source, (target / "openart.exe").open("wb") as out:
                out.write(source.read())
    if not installed(cfg):
        raise RuntimeError(t("The image generation program is missing from the downloaded archive."))


# ------------------------------------------------------------------ calling it
def _run(cfg: Config, arguments: list[str], *, timeout: int = CALL_TIMEOUT) -> tuple[int, str, str]:
    """Run the CLI and hand back what it said. Never raises for a failed call."""
    if not installed(cfg):
        return 127, "", t("The image generation program is not installed.")
    try:
        finished = subprocess.run(
            [str(openart_cli(cfg)), *arguments],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return 124, "", t("The image generation service did not answer in time.")
    except OSError as error:
        return 126, "", f"{type(error).__name__}: {error}"
    return finished.returncode, finished.stdout or "", finished.stderr or ""


def _json(cfg: Config, arguments: list[str], *, timeout: int = CALL_TIMEOUT):
    """The CLI puts structured output on stdout and progress on stderr."""
    code, out, err = _run(cfg, [*arguments, "--json"], timeout=timeout)
    if code != 0:
        return None, (err or out or "").strip()
    try:
        return json.loads(out), ""
    except ValueError:
        return None, (out or err or "").strip()


def account(cfg: Config) -> dict | None:
    """Identity, plan and credit balance, or None when nobody is signed in."""
    data, _ = _json(cfg, ["account"])
    return data if isinstance(data, dict) else None


def identity(payload) -> str:
    """Who the account belongs to, as one line for the interface.

    Observed shape: {"user": {"uid", "email"}, "plan", "credits"}. Read through a
    helper because a flat "email" was assumed first and was wrong - and because
    what counts as signed in has to be the same question in both places."""
    if not isinstance(payload, dict):
        return ""
    user = payload.get("user")
    if isinstance(user, dict):
        for key in ("email", "name", "uid"):
            if str(user.get(key) or "").strip():
                return str(user[key]).strip()
    for key in ("email", "name"):
        if str(payload.get(key) or "").strip():
            return str(payload[key]).strip()
    return ""


def signed_in(cfg: Config) -> bool:
    """A payload that does not name anybody is not a sign-in.

    Deliberately stricter than "the call succeeded": whether the CLI reports a
    signed-out state by exit code or by an empty payload could not be tested
    without signing the owner out, so neither is relied on."""
    return bool(identity(account(cfg)))


def login_argv(cfg: Config) -> list[str]:
    """The command that opens the browser. The owner completes the sign-in.

    Deliberately returned rather than run here: signing in is the account
    holder's to do, and this keeps the harness out of the credential entirely."""
    return [str(openart_cli(cfg)), "login"]


def logout(cfg: Config) -> bool:
    code, _, _ = _run(cfg, ["logout"])
    return code == 0


def cost(cfg: Config, model: str, mode: str = "text2image") -> int | None:
    """What one picture would cost in credits. Pricing spends nothing."""
    data, _ = _json(cfg, ["model", "cost", "--model", model, "--mode", mode])
    rows = (data or {}).get("items") if isinstance(data, dict) else None
    if isinstance(data, dict) and isinstance(data.get("totalCredits"), (int, float)):
        return int(data["totalCredits"])
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("totalCredits"), (int, float)):
                return int(row["totalCredits"])
    return None


def _saved_files(payload, directory: Path, before: set[Path]) -> list[Path]:
    """Which files the run produced.

    The CLI reports what it wrote, but a version that words it differently must
    not make a generated picture look like a failure - so the directory is the
    fallback authority on what actually arrived."""
    found: list[Path] = []
    for path in sorted(directory.glob("*")):
        if path.is_file() and path not in before:
            found.append(path)
    if found:
        return found
    for value in _strings(payload):
        candidate = Path(value)
        if candidate.is_file():
            found.append(candidate)
    return found


def _strings(payload) -> list[str]:
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        return [s for value in payload.values() for s in _strings(value)]
    if isinstance(payload, list):
        return [s for value in payload for s in _strings(value)]
    return []


def generate(cfg: Config, prompt: str, *, model: str = DEFAULT_MODEL,
             directory: Path, reference: Path | None = None,
             timeout: int = GENERATE_TIMEOUT) -> dict:
    """Generate one picture into `directory`. Returns what happened, never raises."""
    if not enabled(cfg):
        return {"ok": False, "error": t("Image generation is switched off in settings.")}
    if not installed(cfg):
        return {"ok": False, "error": t("The image generation program is not installed.")}
    directory.mkdir(parents=True, exist_ok=True)
    before = {path for path in directory.glob("*") if path.is_file()}
    # The CLI parses --timeout as a Go duration, so it needs a unit: a bare "420"
    # is rejected outright. Found with --dry-run, which would otherwise have been
    # found by the first real generation failing.
    arguments = ["generate", "image", prompt, "--model", model,
                 "-o", str(directory), "--timeout", "%ds" % timeout]
    if reference is not None:
        arguments += ["--image", str(reference)]
    payload, message = _json(cfg, arguments, timeout=timeout + 60)
    files = _saved_files(payload, directory, before)
    if not files:
        return {"ok": False, "error": message or t("No picture came back.")}
    return {"ok": True, "files": files, "model": model}
