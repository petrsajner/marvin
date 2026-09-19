"""Dictation: record the microphone and transcribe it locally with whisper.cpp.

The shipped language model has a vision projector and no audio tower, so speech
needs its own runtime. Everything is pinned and verified the same way the model
runtime is; nothing here reaches the network unless the owner turns dictation on.

Two measured facts shape this module, both recorded in docs/design/voice-input.md:
the turbo model is as accurate in Czech as the full one and considerably faster,
and Whisper invents a Czech subtitle credit when it is given silence - which is
why voice activity detection is always on and never a setting.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
import wave
import zipfile
from pathlib import Path

from harness.config import Config
from harness.i18n import t

RELEASE = "b5130"
ARCHIVE = ("whisper-bin-x64.zip", 8573270,
           "f9ec6c52a2e949b62ab51fa21d0d497958f9e41c3010c157c4e42932d5316f3c")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SAMPLE_RATE = 16000              # whisper.cpp resamples anything else; this avoids it.
MIN_SECONDS = 0.4                # Shorter than this is a mis-click, not a sentence.
TRANSCRIBE_TIMEOUT = 300

# Whisper fills silence with credits it saw in subtitle training data. Voice
# activity detection removes the cause; this catches a fragment that survives it.
# The whole transcript has to match, so real speech is never dropped.
# Written with escapes because interface text belongs in the locale catalogue;
# these are patterns for speech the model invented, not text shown to anyone.
INVENTED = (
    r"titulky\s+(vytvo[\u0159r]il|pro|p[\u0159r]elo[\u017ez]il)\b.*",
    r"p[\u0159r]eklad[:\s].*",
    r"subtitles?\s+(by|provided)\b.*",
    r"amara\.org.*",
    r"[\W_]*",
)


def speech_dir(cfg: Config) -> Path:
    return cfg.path("paths.runtime_dir") / "whisper"


def whisper_cli(cfg: Config) -> Path:
    return speech_dir(cfg) / "whisper-cli.exe"


def model_paths(cfg: Config) -> tuple[Path, Path]:
    """The transcription model and the voice-activity model, in that order."""
    from harness.model_catalog import SPEECH_SILERO_VAD, SPEECH_WHISPER_TURBO
    from harness.model_files import local_model_dir
    models = cfg.path("paths.models_dir")
    directory = local_model_dir(models, SPEECH_WHISPER_TURBO)
    return (directory / SPEECH_WHISPER_TURBO["assets"][0]["path"],
            local_model_dir(models, SPEECH_SILERO_VAD) / SPEECH_SILERO_VAD["assets"][0]["path"])


def missing(cfg: Config) -> list[str]:
    """What dictation still needs, in words the owner can act on."""
    from harness.model_catalog import SPEECH_SILERO_VAD, SPEECH_WHISPER_TURBO
    from harness.model_files import model_ready
    models = cfg.path("paths.models_dir")
    absent = []
    if not whisper_cli(cfg).is_file():
        absent.append(t("speech recognition program (9 MB)"))
    if not model_ready(models, SPEECH_WHISPER_TURBO):
        absent.append(t("Czech speech model (547 MB)"))
    if not model_ready(models, SPEECH_SILERO_VAD):
        absent.append(t("speech detection model (1 MB)"))
    return absent


def ready(cfg: Config) -> bool:
    return not missing(cfg)


def capture_available() -> tuple[bool, str]:
    """Whether an input device exists, without opening it."""
    try:
        import sounddevice
    except Exception as error:                       # The wheel may be absent entirely.
        return False, f"{type(error).__name__}: {error}"
    try:
        inputs = [d for d in sounddevice.query_devices() if d["max_input_channels"] > 0]
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"
    if not inputs:
        return False, t("No microphone is connected.")
    return True, ""


def input_devices() -> list[dict]:
    ok, _ = capture_available()
    if not ok:
        return []
    import sounddevice
    default = sounddevice.default.device[0]
    devices = []
    for index, device in enumerate(sounddevice.query_devices()):
        if device["max_input_channels"] > 0:
            devices.append({"index": index, "name": str(device["name"]),
                            "default": index == default})
    return devices


# --------------------------------------------------------------------- install
def install_bytes() -> int:
    """Everything dictation downloads, so progress can be a share of the whole."""
    from harness.model_catalog import SPEECH_SILERO_VAD, SPEECH_WHISPER_TURBO
    total = ARCHIVE[1]
    for spec in (SPEECH_SILERO_VAD, SPEECH_WHISPER_TURBO):
        total += sum(int(asset["size"]) for asset in spec["assets"])
    return total


def install(cfg: Config, *, progress=print, should_stop=None, on_progress=None) -> None:
    """Fetch the pinned program and models. Safe to call when they already exist.

    on_progress(done, total) counts every byte of the whole installation, not of
    one file: three separate downloads restarting from zero would read as a
    download going backwards."""
    from harness.model_catalog import SPEECH_SILERO_VAD, SPEECH_WHISPER_TURBO
    from harness.model_files import download_pinned_model
    models = cfg.path("paths.models_dir")
    total = install_bytes()
    finished = 0
    for spec in (SPEECH_SILERO_VAD, SPEECH_WHISPER_TURBO):
        if should_stop and should_stop():
            raise InterruptedError("Dictation setup cancelled")
        size = sum(int(asset["size"]) for asset in spec["assets"])
        step = None
        if on_progress:
            done_before = finished
            step = lambda done, _size, base=done_before: on_progress(base + done, total)
        download_pinned_model(models, spec, progress=progress, should_stop=should_stop,
                              on_progress=step)
        finished += size
        if on_progress:
            on_progress(finished, total)
    if not whisper_cli(cfg).is_file():
        _install_program(cfg, progress=progress, should_stop=should_stop,
                         on_progress=(lambda done: on_progress(finished + done, total))
                         if on_progress else None)
    elif on_progress:
        on_progress(total, total)


def _install_program(cfg: Config, *, progress=print, should_stop=None, on_progress=None) -> None:
    import requests
    from harness.runtime_update import sha256
    name, size, digest = ARCHIVE
    target = speech_dir(cfg)
    target.mkdir(parents=True, exist_ok=True)
    cache = cfg.path("paths.runtime_dir") / "runtime-archives" / RELEASE
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    if not archive.is_file() or sha256(archive) != digest:
        progress(t("Preparing dictation: {name}", name=name))
        partial = archive.with_suffix(".part")
        url = f"https://github.com/ggml-org/whisper.cpp/releases/download/{RELEASE}/{name}"
        with requests.get(url, stream=True, timeout=(15, 30)) as response, partial.open("wb") as out:
            response.raise_for_status()
            written = 0
            for chunk in response.iter_content(4 * 1024**2):
                if should_stop and should_stop():
                    raise InterruptedError("Dictation setup cancelled")
                out.write(chunk)
                written += len(chunk)
                if on_progress:
                    on_progress(written)
        if partial.stat().st_size != size or sha256(partial) != digest:
            partial.unlink(missing_ok=True)
            raise RuntimeError(t("The downloaded dictation program did not match its checksum."))
        partial.replace(archive)
    # Only the files transcription needs. The archive also carries unrelated
    # example programs and an SDL dependency that nothing here uses.
    wanted = re.compile(r"(whisper-cli\.exe|whisper\.dll|ggml.*\.dll)$", re.IGNORECASE)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            if item.is_dir() or not wanted.search(item.filename):
                continue
            destination = target / Path(item.filename).name
            with bundle.open(item) as source, destination.open("wb") as out:
                out.write(source.read())
    if not whisper_cli(cfg).is_file():
        raise RuntimeError(t("The dictation program is missing from the downloaded archive."))


# ------------------------------------------------------------------- recording
class Recorder:
    """One microphone stream at a time, owned by the application, not a request."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._stream = None
        self._frames: list = []
        self._started = 0.0
        self._path: Path | None = None

    @property
    def active(self) -> bool:
        return self._stream is not None

    @property
    def seconds(self) -> float:
        return round(time.time() - self._started, 1) if self._stream else 0.0

    def start(self) -> None:
        import numpy
        import sounddevice
        with self._lock:
            if self._stream is not None:
                return                              # A second press must not open a second stream.
            self._frames = []
            limit = int(self.cfg.data["speech"].get("max_seconds", 300)) * SAMPLE_RATE

            def collect(indata, _frames, _time, status):
                # The callback runs on PortAudio's thread; keep it to a copy.
                if sum(len(chunk) for chunk in self._frames) < limit:
                    self._frames.append(indata.copy())

            device = self.cfg.data["speech"].get("device")
            self._stream = sounddevice.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                device=device if device not in (None, "") else None, callback=collect)
            self._stream.start()
            self._started = time.time()
            self._numpy = numpy

    def cancel(self) -> None:
        with self._lock:
            self._close()
            self._frames = []

    def stop(self) -> Path | None:
        """Close the stream and write what was heard to a WAV file."""
        with self._lock:
            if self._stream is None:
                return None
            self._close()
            frames, self._frames = self._frames, []
        if not frames:
            return None
        samples = self._numpy.concatenate(frames).reshape(-1)
        if len(samples) < MIN_SECONDS * SAMPLE_RATE:
            return None
        handle, name = tempfile.mkstemp(prefix="dictation-", suffix=".wav")
        os.close(handle)
        path = Path(name)
        clipped = self._numpy.clip(samples, -1.0, 1.0)
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)
            out.writeframes((clipped * 32767).astype("<i2").tobytes())
        self._path = path
        return path

    def _close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()


# ---------------------------------------------------------------- transcription
def language_for(cfg: Config, preference: str | None = None) -> str:
    """Never 'auto': detection on a short Czech phrase fails towards English."""
    chosen = (preference or cfg.data["speech"].get("language") or "auto").strip().lower()
    if chosen in ("", "auto"):
        from harness.i18n import get_language
        chosen = get_language()
    return chosen if chosen in ("cs", "en") else "en"


def command(cfg: Config, wav: Path, language: str) -> list[str]:
    model, vad = model_paths(cfg)
    threads = int(cfg.data["speech"].get("threads") or 0) or max(2, (os.cpu_count() or 4) - 2)
    return [str(whisper_cli(cfg)), "-m", str(model), "-f", str(wav),
            "-l", language, "-t", str(threads), "-nt", "-np",
            # Always on. Silence is otherwise transcribed as invented text.
            "--vad", "--vad-model", str(vad)]


def clean(text: str) -> str:
    """Drop a transcript that is only an artefact of silence."""
    stripped = " ".join(text.split())
    for pattern in INVENTED:
        if re.fullmatch(pattern, stripped.strip(" .,-"), re.IGNORECASE):
            return ""
    return stripped


def transcribe(cfg: Config, wav: Path, language: str | None = None) -> str:
    """Return what was said, or an empty string when nothing was heard."""
    absent = missing(cfg)
    if absent:
        raise RuntimeError(t("Dictation is not installed yet: {items}",
                             items=", ".join(absent)))
    done = subprocess.run(command(cfg, wav, language_for(cfg, language)),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=TRANSCRIBE_TIMEOUT,
                          creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise RuntimeError(f"whisper-cli: {(done.stderr or '').strip()[-300:]}")
    return clean(done.stdout)
