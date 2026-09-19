"""Dictation: what it asks whisper for, and what it refuses to hand back.

The measured reasons behind these rules are in docs/design/voice-input.md: silence
is transcribed as an invented Czech subtitle credit unless voice activity
detection is on, and naming the language is about twice as fast as detecting it.
"""
import copy
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness import speech
from harness.application import ApplicationService
from harness.config import Config, load_config
from harness.web_api import create_app


def configuration(root: Path) -> Config:
    data = copy.deepcopy(load_config().data)
    data["hardware"]["vram_gb"] = 32
    return Config(data, root)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cfg = configuration(Path(self.temporary.name))

    def test_voice_activity_detection_is_always_requested(self):
        """Without it, silence comes back as text the owner never said."""
        argv = speech.command(self.cfg, Path("say.wav"), "cs")
        self.assertIn("--vad", argv)
        self.assertIn("--vad-model", argv)
        self.assertTrue(argv[argv.index("--vad-model") + 1].endswith("ggml-silero-v5.1.2.bin"))

    def test_the_language_is_always_stated(self):
        argv = speech.command(self.cfg, Path("say.wav"), "cs")
        self.assertEqual(argv[argv.index("-l") + 1], "cs")
        self.assertNotIn("auto", argv)

    def test_auto_resolves_to_the_interface_language_never_to_auto(self):
        from harness.i18n import set_language
        previous = None
        try:
            from harness.i18n import get_language
            previous = get_language()
            set_language("cs")
            self.assertEqual(speech.language_for(self.cfg, "auto"), "cs")
            set_language("en")
            self.assertEqual(speech.language_for(self.cfg, "auto"), "en")
            self.assertEqual(speech.language_for(self.cfg, "cs"), "cs")
            # Anything unexpected still has to be a language whisper accepts.
            self.assertEqual(speech.language_for(self.cfg, "klingon"), "en")
        finally:
            if previous:
                set_language(previous)

    def test_the_two_models_do_not_share_a_directory(self):
        """A shared directory makes each download receipt invalidate the other."""
        model, vad = speech.model_paths(self.cfg)
        self.assertNotEqual(model.parent, vad.parent)

    def test_missing_pieces_are_named_in_words_and_sizes(self):
        absent = speech.missing(self.cfg)
        self.assertEqual(len(absent), 3)
        self.assertTrue(all(any(unit in item for unit in ("MB", "GB")) for item in absent))
        self.assertFalse(speech.ready(self.cfg))

    def test_an_upgraded_installation_gets_the_settings_it_never_had(self):
        """An upgrade keeps the user's config.yaml, so a new section can only
        arrive through the defaults in code. Without this, dictation raised a
        KeyError on every installation that predates it."""
        from harness.config import DEFAULTS, Config, _deep_merge
        older = {"server": {"host": "127.0.0.1"}, "default_model": "q5"}
        upgraded = Config(_deep_merge(DEFAULTS, older), Path(self.temporary.name))
        self.assertEqual(upgraded.data["speech"]["language"], "auto")
        self.assertFalse(upgraded.data["speech"]["enabled"])
        # The command can be built, which is what actually crashed.
        self.assertIn("--vad", speech.command(upgraded, Path("say.wav"), "cs"))

    def test_transcribing_without_the_runtime_explains_instead_of_crashing(self):
        with self.assertRaises(RuntimeError) as caught:
            speech.transcribe(self.cfg, Path("say.wav"), "cs")
        self.assertIn("MB", str(caught.exception))


class SilenceGuardTests(unittest.TestCase):
    """Czech here is recorded speech, not interface text, so it is written with
    escapes: the localisation rule keeps literal Czech out of source files."""

    INVENTED = (
        "Titulky vytvo\u0159il JohnyX.",          # What three seconds of silence produced.
        "titulky vytvo\u0159il JohnyX",
        "Titulky pro Amara.org",
        "Subtitles by the Amara.org community",
        "P\u0159eklad: nekdo",
        "  ", "...", "",
    )
    SPOKEN = (
        "Otev\u0159i projekt Arkanoid a spus\u0165 testy.",
        "Titulky k tomu videu jsem ned\u011blal j\u00e1.",   # Has the word, is not the artefact.
        "P\u0159elo\u017e mi ten dokument do angli\u010dtiny.",
    )

    def test_an_invented_subtitle_credit_is_dropped(self):
        for invented in self.INVENTED:
            self.assertEqual(speech.clean(invented), "", invented)

    def test_real_speech_is_kept_exactly(self):
        for said in self.SPOKEN:
            self.assertEqual(speech.clean(" " + said + "\n"), said)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cfg = configuration(Path(self.temporary.name))
        self.service = ApplicationService(self.cfg, llm_factory=lambda c: None,
                                          manage_model=False)
        self.addCleanup(self.service.models.wait, 3)
        self.addCleanup(self.service.close)
        self.client = TestClient(create_app(self.cfg, service=self.service))

    def test_dictation_is_off_until_it_is_turned_on(self):
        state = self.client.get("/api/state").json()
        self.assertFalse(state["voice"]["enabled"])
        self.assertFalse(state["voice"]["recording"])

    def test_enabling_it_asks_for_the_download_once(self):
        with patch.object(ApplicationService, "prepare_voice_input") as prepare:
            self.client.patch("/api/settings", json={"voice_input": True}).raise_for_status()
        prepare.assert_called_once()
        self.assertTrue(self.client.get("/api/state").json()["voice"]["enabled"])

    def test_the_download_reports_how_far_it_has_got(self):
        """It used to show one sentence that never changed, so 556 MB of download
        was indistinguishable from a download that had stalled."""
        seen = []

        def fake_install(cfg, *, progress=print, should_stop=None, on_progress=None):
            for done in (0, 200 * 1048576, speech.install_bytes()):
                on_progress(done, speech.install_bytes())
                seen.append(self.service.voice_state()["install_done"])

        with patch.object(speech, "ready", return_value=False), \
                patch.object(speech, "install", side_effect=fake_install):
            self.service.prepare_voice_input()
            for _ in range(100):
                if not self.service.voice_state()["installing"]:
                    break
                time.sleep(0.02)
        self.assertEqual(seen, [0, 200 * 1048576, speech.install_bytes()])
        state = self.service.voice_state()
        self.assertEqual(state["install_total"], speech.install_bytes())
        self.assertFalse(state["installing"])

    def test_the_total_covers_every_piece_that_is_downloaded(self):
        from harness.model_catalog import SPEECH_SILERO_VAD, SPEECH_WHISPER_TURBO
        expected = speech.ARCHIVE[1] + sum(
            int(asset["size"]) for spec in (SPEECH_SILERO_VAD, SPEECH_WHISPER_TURBO)
            for asset in spec["assets"])
        self.assertEqual(speech.install_bytes(), expected)
        # Roughly the figure the interface quotes, so the two cannot drift apart.
        self.assertAlmostEqual(speech.install_bytes() / 1048576, 556, delta=2)

    def test_recording_cannot_start_before_the_runtime_is_there(self):
        answer = self.client.post("/api/voice/start")
        self.assertEqual(answer.status_code, 400)
        self.assertIn("MB", answer.json()["detail"])

    def test_stopping_when_nothing_is_recording_is_not_an_error(self):
        answer = self.client.post("/api/voice/stop").json()
        self.assertEqual(answer["text"], "")
        self.assertFalse(answer["heard"])

    def test_a_second_start_does_not_open_a_second_microphone(self):
        opened = []

        class Stream:
            def __init__(self, **kwargs):
                opened.append(kwargs)

            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass

        with patch.object(speech, "missing", return_value=[]), \
                patch.object(speech, "capture_available", return_value=(True, "")), \
                patch.dict("sys.modules", {"sounddevice": type("sd", (), {
                    "InputStream": Stream, "default": type("d", (), {"device": (1, 1)})})}):
            self.client.post("/api/voice/start").raise_for_status()
            self.client.post("/api/voice/start").raise_for_status()
            self.assertEqual(len(opened), 1)
            self.assertTrue(self.client.get("/api/state").json()["voice"]["recording"])
            self.client.post("/api/voice/cancel").raise_for_status()
            self.assertFalse(self.client.get("/api/state").json()["voice"]["recording"])

    def test_transcribed_text_is_returned_and_never_sent(self):
        """Dictation fills the input box. Sending stays the owner's decision."""
        sid = self.client.get("/api/state").json()["session_id"]
        before = len(self.service.session(sid).messages)
        recorded = Path(self.temporary.name) / "said.wav"
        with wave.open(str(recorded), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(speech.SAMPLE_RATE)
            out.writeframes(b"\x00\x01" * speech.SAMPLE_RATE)

        class Recorder:
            active = True
            seconds = 1.0

            def stop(self):
                return recorded

        self.service.recorder = Recorder()
        said = "Otev\u0159i projekt Arkanoid"
        with patch.object(speech, "transcribe", return_value=said):
            answer = self.client.post("/api/voice/stop").json()
        self.assertEqual(answer["text"], said)
        self.assertTrue(answer["heard"])
        self.assertEqual(len(self.service.session(sid).messages), before)
        self.assertFalse(recorded.exists(), "the recording is not kept after transcription")

    def test_silence_reports_that_nothing_was_heard(self):
        class Recorder:
            active = True
            seconds = 0.2

            def stop(self):
                return None          # Too short to be a sentence.

        self.service.recorder = Recorder()
        answer = self.client.post("/api/voice/stop").json()
        self.assertEqual(answer["text"], "")
        self.assertFalse(answer["heard"])


if __name__ == "__main__":
    unittest.main()
