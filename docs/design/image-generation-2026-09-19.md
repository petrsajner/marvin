# Letting the model make a picture

19 September 2026.

Generating locally is not practical here. A picture model and the language model
would have to take turns on the card, and every swap costs a reload and the
processed prompt with it - the thing the rest of this month's work went into
protecting. So this calls a service, and it is the only part of the harness that
does.

## There is no API key, so there is nothing to store

The feature was specified with a settings field for an OpenArt API key. That
field cannot exist. OpenArt publishes no REST API, and their own documentation
answers it directly: *"Do I need an API key? No. Add the server URL in your
agent's settings and sign in with your OpenArt account through OAuth. There are
no keys to create, rotate, or leak."*

Two routes remain, and they are not equally sized:

| | what it means here |
|---|---|
| **MCP server** | implement the MCP protocol, OAuth 2.0 with PKCE and dynamic client registration, inside the harness |
| **CLI** | download one pinned binary and run it |

The CLI was chosen. It is a single 4 MB executable, verified against the
`checksums.txt` the vendor publishes with each release, fetched and run exactly
the way `llama-server` and `whisper.cpp` already are. Nothing new enters the
architecture, and the MCP route would have meant building the "MCP ecosystem"
that AGENTS.md lists as a permanent non-goal - the owner offered to reverse that,
and it turned out not to need reversing.

**Removing the key removed the question of where to keep it.** `openart login`
opens a browser, the owner completes it, and the CLI keeps its own credential in
the user profile at mode 0600, refreshing it itself. The harness never sees it,
never stores it, and it never reaches `config.yaml`, an export or a backup. A
test asserts the configuration block contains exactly one key, `enabled`, and
that the account reported to the interface carries only a name, a plan and a
balance - so a future field on the account payload cannot quietly start
travelling.

The harness also never signs anyone in. `login_argv` hands back the command
instead of running it, because an account holder's sign-in is theirs to complete.

## The switch

One place, as asked: Settings → Behaviour → Image generation. Off by default, and
off means off even when the CLI is installed and the account is connected - the
switch is not a mirror of the sign-in state. When the account is connected it is
shown as a highlighted chip with the credit balance, which is what the "key is
inserted and active" indicator became once there was no key.

## What the model is told

A written table of five models rather than a live `openart model list`:

| id | for |
|---|---|
| `nano-banana-2` | Google Nano Banana 2 - 4K, accurate in-image text. The default. |
| `gpt-image-2-5-flare` | OpenAI GPT Image 2.5, speed-first |
| `gpt-image-2-5-sunburst` | OpenAI GPT Image 2.5, quality- and editing-first |
| `nano-banana-pro` | long in-image text, several consistent people |
| `byte-plus-seedream-4-5` | anime and 2D illustration |

Written rather than fetched on purpose. The tool description travels in every
request, so a catalogue that changed between sessions would move the prompt
prefix and cost a full reprocess - the exact failure measured earlier today, when
a system prompt that grew by 462 characters threw away 144k tokens. A test asserts
the schema is identical across two builds. An unlisted model is passed through
rather than refused, because this table is the short list worth knowing by heart,
not the whole of OpenArt.

The tool is registered **only when the switch is on**. A tool in the schema is a
promise to the model, and one it cannot keep costs a wasted step and a wrong
answer to the user. `build_registry` takes the configuration for this; without
one the tool is left out, which is the safe direction.

## Credits

Every generation is priced first with `openart model cost`, which spends nothing,
and the price is reported in the tool result beside the saved file. No cap and no
confirmation: the owner asked for one switch and otherwise for it to work. The
guard is that the switch exists and that the tool is `Risk.WRITE`.

## Verified against the real program, and what it caught

The binary was downloaded, checked against the published digest and extracted:
4,066,696 bytes in, a 9,980,416-byte `openart.exe` out, reporting build
`85fa0ad`. Then every call the harness makes, except the one that costs money:

**Two things read from documentation were wrong.**

*The account payload is nested.* It is `{"user": {"uid", "email"}, "plan",
"credits"}`, not a flat `email`, so the interface would have shown a signed-in
account with no name against it. The test that "passed" was asserting against a
shape invented to match the code. Identity now goes through one helper, and
`signed_in` asks it rather than asking whether the call succeeded - deliberately
stricter, because whether the CLI reports a signed-out state by exit code or by
an empty payload could not be tested without signing the owner out.

*`--timeout` is a Go duration and rejects a bare number.* `--timeout 420` fails
with `missing unit in duration "420"`. **Every generation would have failed**, and
the only reason it did not have to be found the expensive way is that `--dry-run`
costs nothing. It is `420s` now, with a regression test.

What was confirmed: all five catalogued model ids exist among the 28 the service
offers; `model cost` parses to 20 credits for `nano-banana-2` at `text2image`;
and `--dry-run` returns exactly the intended request -
`POST /api/cli/v1/generate` with `{"model": "nano-banana-2", "media": "image",
"mode": "text2image", "params": {"prompt": ...}}`.

**The one thing still unverified is a real generation**, because it spends the
owner's credits and that is his to authorise. Everything up to the paid call has
now carried traffic.

The CLI is at **v0.1.1**. That is an early version, and the interface may move;
the pin is what protects against it moving underneath us.
