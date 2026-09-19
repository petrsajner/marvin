# Marvin 1.12.1 - a stale package payload no longer blocks startup

Released on 19 September 2026. **Install this instead of 1.12.0.**

## Why

1.12.0 added a Python package, which exposed a fault in the upgrade path: on a
machine installed from the Full package, Marvin would not start at all. The
dialog said only

> Bundled Python environment could not be prepared. See runtime/launcher.log.

The Minimal installer replaces `requirements.txt`, while the bundled package
payload and its manifest ship only with Full. Their digests therefore stopped
matching, and `bootstrap_full.py` refused to continue - even though the private
environment on that machine was perfectly good and already had the new package.

The payload matters when the private environment has to be **built**. When the
environment already satisfies the current requirements there is nothing to build,
and a payload older than the requirements is a reason to fetch the difference,
not a reason to refuse to start.

## What changed

- An environment whose recorded requirements match the current ones is accepted,
  with a note that the bundled payload is older and that the Full package for this
  version would refresh it.
- When the environment genuinely has to be rebuilt from a payload that predates
  the requirements, the missing packages are downloaded instead of the whole thing
  failing.
- The dialog now says what to do - connect to the internet and start again, or
  install the Full package - and points at `runtime/full-setup-error.log`, which
  holds the actual traceback.
- `tests/test_full_bootstrap.py` covers all of it, and the release gate runs it.

Everything in [1.12.0](RELEASE-1.12.0.md) - dictation, window-aware computer
control, and the prompt-cache work - is unchanged and included.

## If 1.12.0 already stopped starting for you

Install this version over it; nothing else is needed. Conversations, projects,
models and settings are untouched, as with any application update.

## Verification

370 checks in the core suite and 237 unit tests, green locally before the build.
The real bootstrap was additionally run against the owner's own installation,
where 1.12.0 had failed: it now reports the environment as satisfying the
requirements, exits cleanly, and the application starts.
