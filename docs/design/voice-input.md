# Voice input - dictation for someone who would rather not type

19 September 2026. Implementation design for item B of the
[harness parity roadmap](harness-parity-roadmap.md). Every number below was
measured on the owner's machine before the design was fixed.

## What it has to do

Dictate a request into the chat input box, in Czech, and edit it before sending.
Not a voice assistant: no wake word, no hands-free operation, no spoken replies.
The text lands in the input box and nothing is ever sent automatically - the same
rule that makes the rest of the harness safe to hand to a non-programmer.

Czech quality is the requirement, not a nice-to-have. The owner writes Czech and
said so explicitly.

## The model cannot do it

`runtime/models/mmproj-F16.gguf` declares `clip.has_vision_encoder` and a
`qwen3vl_merger` projector, with no audio tower. Qwen3.8 as shipped here sees but
does not hear, so transcription needs its own runtime. That is the only reason
this feature has moving parts at all.

## Measured: which model

FLEURS `cs_cz` dev - native Czech speakers reading sentences, with reference
transcripts. The twenty shortest clips, 121 s of speech, which is dictation
length. Word error rate against the normalised reference, on CPU with 20 threads:

| model | download | WER | per utterance |
|---|---|---|---|
| `ggml-large-v3-turbo-q5_0` | 547 MB | **11.4%** | **3.9 s** |
| `ggml-large-v3-q5_0` | 1 080 MB | 11.4% | 6.1 s |
| `ggml-medium-q5_0` | 514 MB | 27.4% | 3.1 s |

The full model is not better here - the same 27 errors in the same 237 words - and
it costs 1.6x the time and twice the download. Medium is barely faster than turbo
and makes two and a half times as many mistakes, which is what a smaller model
costs in a language it has seen less of. Turbo is therefore the default and the
only model shipped; there is no useful smaller option to offer.

Almost every error is a proper noun rather than Czech grammar:

```
want: poté zpěv bhajanů převzal lakkha singh
got : poté zpěv bajanů převzal lakasink
want: největší turnaj roku se odehrává v prosinci na hřištích na pólo v las cañitas
got : největší turnej roku se odehrává v prosince na hřištích na polu v laskanitas
```

That is the right shape of error for this use: ordinary Czech comes out clean,
unusual names need a correction, and the text is in an editable box.

English, as a control - the sentence came back word for word:

```
Open the project called Arkanoid and run the tests, then tell me which ones are failing.
```

## Measured: silence is the real hazard

Pressing the button and hesitating is what will actually happen. Whisper does not
return nothing for silence; it invents. Three seconds of digital silence, and
three seconds of faint hiss, both produced:

```
Titulky vytvořil JohnyX.
```

A subtitle credit from the training data, in Czech, with no audio behind it.
Shipping without a guard would mean junk appearing in the input box whenever the
owner paused.

Silero VAD, which the same build supports, fixes it completely:

| input | without VAD | with `--vad` |
|---|---|---|
| 3 s digital silence | `Titulky vytvořil JohnyX.` | *(empty)* |
| 3 s faint hiss | `Titulky vytvořil JohnyX` | *(empty)* |
| Czech speech | correct | correct |

VAD is therefore not optional and not a setting. It is always on, and an empty
result is reported as "nothing was heard" rather than as a failure.

## Decisions

1. **whisper.cpp CPU build, not CUDA.** `whisper-bin-x64.zip` is 8.5 MB;
   the CUDA build is 643 MB and would claim GPU memory the language model is
   using - at 196k context there is little to spare. On CPU an utterance costs
   3.9 s, of which about 3 s is the encoder pass over Whisper's fixed 30-second
   window, so the cost barely varies with how long the owner speaks.
2. **One process per utterance, no sidecar.** Model load is about 0.3 s of the
   3.9 s, so a resident server would save little and would hold 550 MB of RAM
   between dictations. `whisper-cli.exe` is started, it writes the text, it exits.
3. **The language is stated, never guessed.** Measured: `-l auto` reached the
   same 11.4% on these clips but took 6.8 s instead of 3.9 s - detection costs a
   separate pass over the audio, three quarters again on top of the work. The
   expected accuracy argument did not appear on clean read speech; the latency
   argument is enough on its own. The default follows the interface language and
   can be set explicitly.
4. **Capture happens in the harness, not in the page.** `sounddevice` records
   16 kHz mono straight to a WAV, which is the only format `whisper-cli` reads.
   The interface runs in WebView2, where microphone permission is not ours to
   grant, and a browser recording would arrive as Opus and need a decoder the
   harness does not ship. The owner's default input device is a Brio 100 webcam
   microphone; the device is selectable.
5. **Everything is pinned and verified**, the same way the model runtime and the
   embedding model already are: release tag `b5130` for the binaries, repository
   revisions for the two models, sha256 for all three.
6. **Off until asked for, then downloaded once.** Dictation follows the semantic
   search precedent: a switch in settings, a background download of the pinned
   assets on first enable, and a button that explains itself while the assets are
   missing rather than failing when pressed. 556 MB in total.

## Shape

```
harness/speech.py        availability, capture, transcription, the silence guard
harness/model_catalog.py the two pinned model specs, beside the embedding one
harness/web_api.py       /api/voice/{state,start,stop,cancel,install}
frontend               microphone button in the composer, voice section in settings
config.yaml            speech: enabled, model, language, device, threads
```

Recording is owned by the application service, not by a request: a start without
a matching stop has to survive a reloaded page, and a second start must not open a
second stream. Stop returns the text; the interface inserts it at the cursor.

## What is deliberately not here

- **No wake word and no continuous listening.** A microphone that is always open
  on a personal machine is a different product and a different risk.
- **No spoken output.** Reading answers aloud was not asked for.
- **No dictation tool for the model.** This is the owner's input path. Giving the
  agent a microphone is not the same feature and would need its own consent.
- **No CUDA.** Revisit only if 3.9 s proves too slow in daily use; the flag and
  the 643 MB build are available without redesign.

## Verification

Unit cover in `tests/test_speech.py`; an end-to-end check that runs the real
binary against a generated sample lives in `tests/check_speech.py`, so the
measurement above can be repeated after any pin change.

The one thing no test can settle is the owner's own microphone in his own room.
FLEURS is clean read speech; a webcam microphone at desk distance will be worse.
That number arrives the first time he dictates.
