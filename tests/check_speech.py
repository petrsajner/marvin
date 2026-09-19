"""Run dictation against the real runtime, so the measurement can be repeated.

Unit tests cover what whisper is asked for; this covers what it answers. Needs the
pinned program and models installed, which happens when dictation is enabled.

    python tests/check_speech.py
"""
from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import speech                                    # noqa: E402
from harness.config import load_config                        # noqa: E402

SENTENCE = "Open the project called Arkanoid and run the tests."
EXPECTED = ("project", "arkanoid", "run", "tests")


def synthesize(path: Path) -> bool:
    """Speak a sentence with the voice Windows already has, so no clip is shipped."""
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{SENTENCE}'); "
        "$s.SetOutputToDefaultAudioDevice(); $s.Dispose()")
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True)
    return done.returncode == 0 and path.is_file() and path.stat().st_size > 1000


def silence(path: Path, seconds: float = 3.0) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(speech.SAMPLE_RATE)
        out.writeframes(struct.pack("<h", 0) * int(seconds * speech.SAMPLE_RATE))


def main() -> int:
    cfg = load_config()
    absent = speech.missing(cfg)
    if absent:
        print("Dictation is not installed; enable it in settings first. Missing:", absent)
        return 0
    failures = []
    with tempfile.TemporaryDirectory(prefix="speech-check-") as temporary:
        directory = Path(temporary)

        quiet = directory / "silence.wav"
        silence(quiet)
        started = time.time()
        heard = speech.transcribe(cfg, quiet, "cs")
        print("silence      %.1f s  -> %r" % (time.time() - started, heard))
        if heard:
            failures.append("silence produced text: %r" % heard)

        spoken = directory / "spoken.wav"
        if not synthesize(spoken):
            print("No speech synthesiser available; the spoken check was skipped.")
        else:
            started = time.time()
            heard = speech.transcribe(cfg, spoken, "en")
            print("spoken       %.1f s  -> %r" % (time.time() - started, heard))
            words = heard.lower()
            absent_words = [w for w in EXPECTED if w not in words]
            if absent_words:
                failures.append("missing from the transcript: %s" % absent_words)

    for failure in failures:
        print("FAIL:", failure)
    print("RESULT:", "ok" if not failures else "%d problem(s)" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
