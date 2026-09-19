# Marvin 1.15.0 - the model can make a picture

19 September 2026.

## One feature that leaves the computer

Everything in Marvin runs locally, and this is the exception: the model can now
generate a picture, through OpenArt, on the owner's account, for credits. It is
off until it is turned on, and off means off.

Generating locally was never the alternative. A picture model and the language
model would have to take turns on the graphics card, and every swap costs a
reload and the processed prompt with it - the thing the rest of this month's work
went into protecting.

**Settings > Behavior > Allow paid image generation.** A 4 MB program downloads
once, then **Sign in to OpenArt** opens the sign-in in a browser. The switch is
separate from the sign-in: turning it off stops generation while the account
stays connected.

## There is no API key, which is why there is nothing to protect

This was specified with a field for an OpenArt API key. That field cannot exist.
OpenArt publishes no REST API, and their own documentation says it outright:
*"Do I need an API key? No. There are no keys to create, rotate, or leak."*

Their two routes are an MCP server or a CLI. The CLI was taken: one pinned 4 MB
binary, verified against the `checksums.txt` the vendor publishes, fetched and
run exactly the way `llama-server` and `whisper.cpp` already are. The MCP route
would have meant implementing the protocol, OAuth 2.0 with PKCE and dynamic
client registration inside the harness - and that is the "MCP ecosystem" listed
as a permanent non-goal. The owner offered to reverse that; it turned out not to
need reversing.

Removing the key removed the question of where to keep it. The OpenArt program
holds its own credential in the user profile at mode 0600 and refreshes it
itself. **Marvin never sees it, never stores it, and nothing about it reaches
settings, an export or a backup.** Marvin also never signs anyone in: the command
is handed back, and the account holder completes it in their browser.

## What the model knows

Five models, as a written table rather than a live catalogue:

| id | for |
|---|---|
| `nano-banana-2` | Google Nano Banana 2 - 4K, accurate in-image text. The default. |
| `gpt-image-2-5-flare` | OpenAI GPT Image 2.5, speed-first |
| `gpt-image-2-5-sunburst` | OpenAI GPT Image 2.5, quality- and editing-first |
| `nano-banana-pro` | long in-image text, several consistent people |
| `byte-plus-seedream-4-5` | anime and 2D illustration |

Written rather than fetched for a measured reason: the tool description travels
in every request, so a catalogue that changed between sessions would move the
prompt prefix and cost a full reprocess - exactly what a system prompt growing by
462 characters did earlier today, throwing away 144k tokens.

The tool is offered to the model **only when the switch is on**, because a tool
in the schema is a promise, and one that cannot be kept costs a wasted step and a
wrong answer. Pictures are priced first with a call that spends nothing, the
price is reported beside the file, and they land in `generated-images` inside the
current project.

## Verified against the real service

The binary was downloaded and checked, every call was run, and one picture was
actually generated with the owner's permission: **nano-banana-2, 17 seconds,
quoted 20 credits and charged exactly 20**, 1.5 MB saved into the project.

That verification found three defects that testing against documentation had not:

- **`--timeout` is a Go duration and rejects a bare number.** `--timeout 420`
  fails with `missing unit in duration`. *Every generation would have failed.*
  Found with `--dry-run`, which costs nothing, rather than the expensive way.
- **The account payload is nested** - `{"user": {"uid", "email"}, ...}`, not a
  flat `email` - so the settings panel would have shown a connected account with
  no name against it.
- **A test was passing against a shape invented to match the code.** It now
  asserts against the payload the program actually returns.

The live run also showed what no documentation said: the service names each file
after its own id, so a folder of them is unreadable. The tool's `name` parameter
now tells the model to always pass a descriptive one, with that id as the example.

## Upgrading

Application code only. Conversations, projects, models and settings are
untouched. Image generation is off after upgrading, as it is for a new
installation.

## Verification

372 checks in the core suite, 311 unit tests and 13 localization checks, green
locally before the build, plus a frontend type-check and build. 20 of the unit
tests are new. Recorded in
[image-generation-2026-09-19.md](../design/image-generation-2026-09-19.md).
