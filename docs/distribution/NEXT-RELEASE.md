# Waiting for the next release

Things that are already on `main` but landed after the last tag, so the published
release does not have them. Say them in the next release notes, then delete the
entry.

## The offline backup carries the image-generation program

`scripts/offline_backup.py` collects `runtime/openart/openart.exe` into the
package, so a machine restored from a backup is finished when the restore is
rather than owing a 4 MB download the first time it sees a connection.

Landed in `07ee919`, after `v1.16.1`. Deliberately not re-tagged: the release
assets are published with their checksums, and breaking those for a program that
does nothing without a connection would cost more than waiting one version.

**Check before saying it shipped:** build a backup from a clean checkout of the
new tag and confirm `payload/runtime/openart/openart.exe` is in it. The owner's
own backup was refreshed by hand on 19 September 2026 and already has it, so
checking that one proves nothing about the packaged script.
