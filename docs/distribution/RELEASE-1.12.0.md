# Marvin 1.12.0 - dictation, windows the model can actually see, and a prompt cache that holds

Released on 19 September 2026.

## What's new

**Dictation.** Speak instead of typing, in Czech or English. Turn **Voice input**
on in Settings > Behavior; about 556 MB of speech program and model is fetched
once, and everything then runs on the processor, on this computer, with nothing
sent anywhere. The button sits beside Attach: press, speak, press again, and the
text appears in the prompt box for you to read and correct. Nothing is ever sent
by voice alone.

Czech decided the design, and it was measured rather than assumed. On FLEURS
`cs_cz`, twenty clips of dictation length:

| model | download | word error rate | per utterance |
|---|---|---|---|
| large-v3-turbo | 547 MB | **11.4%** | **3.9 s** |
| large-v3 | 1 080 MB | 11.4% | 6.1 s |
| medium | 514 MB | 27.4% | 3.1 s |

The full model was no more accurate and took 1.6x as long, and medium made two
and a half times as many mistakes, so turbo is the only model shipped. Nearly all
remaining errors are proper nouns; ordinary Czech comes back clean. Naming the
language rather than detecting it costs 3.9 s instead of 6.8 s.

Silence was the hazard worth catching before release. Three seconds of quiet, and
three of faint hiss, were both transcribed as an invented Czech subtitle credit -
text with no audio behind it. Voice activity detection removes it completely and
is always on, so an empty recording reports that nothing was heard.

**The model can see the window it is testing.** Computer mode could photograph
only the whole screen and send keys only to whatever was in front, which is how a
test of a running game produced a picture of a browser. It can now list the open
windows, photograph one by name **while another program covers it** - verified
against a real pygame window sitting behind another - and bring a window forward
before pressing keys, saying so honestly when the system refuses to change the
foreground. Coordinates follow the window, so a click lands where the picture
showed it.

The model also no longer has to discover this by experiment: the Computer prompt
carries a table of its own tools and the order that works, and a test keeps that
table honest against the registry.

**The conversation stops being re-read.** A Computer-mode session spent 13 minutes
on prompt prefill, about 12 of them avoidable, for two reasons that the recorded
progress events made measurable.

Memory lived in the system prompt, so a fact the model saved changed the first
tokens of the next request and the server reprocessed everything: three requests
in that session reused nothing and cost 65, 78 and 98 seconds. Memory and the
skill catalogue now travel at the end of the request, where they append instead of
rewriting, and the system prompt is byte-stable for a whole session.

The request also sent only the newest eight screenshots and recomputed that set
every time, so the ninth silently removed the first from a message the server had
already processed - eleven such breaks in one session, 38 to 62 seconds each.
Screenshots are now given up only under context pressure, deliberately and once,
ahead of summarising the conversation.

Driving the real agent through a ten-step task with a memory save in the middle
now reuses the whole prompt at every step: about 650 ms of prefill per step
instead of 40 to 98 seconds. The activity line shows the share reused and the time
left, because a cached prompt and a full reprocess used to look identical while
waiting.

`--cache-reuse` would have softened what remains, but the server disables it for
this context in every configuration tried, including unified and unquantized KV,
so it was not adopted.

**Also in this release.** New projects can be given their own folder (Settings >
Data and backups). Text can be selected and copied from the chat. Keys reach games
as hardware scancodes with a configurable hold, which is what SDL and DirectInput
require.

Three faults found while preparing the release rather than after it. The release
staging linked files that get rebuilt, so a rebuilt manual silently rewrote the
copy inside an already published release and its checksums stopped matching. The
new speech settings existed only in `config.yaml`, which an upgrade preserves, so
dictation would have raised a KeyError on every existing installation - caught by
loading the installed configuration instead of the repository's own. And
refreshing the offline backup replaced the installer and dependencies but not the
runtime payload, so a restored offline install would have had no speech program;
a refresh now carries new runtime while still recognising the unchanged 226 GB by
size rather than re-reading it.

Adding a dependency also used to make the launcher announce that the application
was not fully installed and offer to download 37 GB of models again. A release
that adds a Python package now says what it is: a few megabytes.

## Upgrading

The installer replaces application code only. Conversations, projects, models, the
Python environment and `config.yaml` are left alone. Dictation is off until you
turn it on.

## Verification

370 checks in the core suite and 232 unit tests, green locally before the build.
Dictation is additionally covered end to end by `tests/check_speech.py`, which
runs the real program against a generated sample; window capture was verified
against a live pygame window. The measurements behind both features are recorded
in [voice-input.md](../design/voice-input.md) and
[prompt-cache-cost.md](../design/prompt-cache-cost.md).

The one thing no test settles is a real microphone in a real room. FLEURS is clean
read speech; a webcam microphone at desk distance will be worse.
