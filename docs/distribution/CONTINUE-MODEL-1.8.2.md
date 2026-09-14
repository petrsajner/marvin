# Marvin 1.8.2: Continue after switching models

14 September 2026. This fix followed the automatic WebView2 setup build. The release number and public links remained 1.8.2.

## Cause and behavior

After Flash-Next ran out of memory, the user manually started Qwen Q5. Settings and the last successful model were correct, but the interrupted SQLite job retained a snapshot of the old Flash-Next configuration. Continue merely requeued that job, so the worker stopped Qwen and loaded Flash-Next again.

`ApplicationService.resume()` now copies the currently selected model, current model definition and KV profile, hardware settings and requested adaptive context into the resumed job and its settings. A correctly configured running model is reused.

Job identity, messages, attachments, work mode, reasoning depth and safety settings remain attached to the original task. Previously saved interrupted tasks work without a database migration or manual edits. At the time of this fix, normal new/queued submissions retained their existing snapshot rules; later runtime-budget reconciliation is documented in [memory profiles](../design/memory-profiles.md).

If the replacement model has a smaller context, automatic compression uses its limit while retaining the complete UI/history transcript.

## Verification recorded for this release

- Before the fix, regression tests reproduced the old-model reload, restart caused by stale KV settings, and wrong context limit.
- API tests covered failed, stopped, interrupted and waiting-confirmation jobs; Flash-Next to Qwen Q5/Q4/Q3, KV changes within one model, and a smaller Flash-Next profile. Correctly running profiles received no restart request.
- Recovery after an application restart preserved partial output, marked unknown tool results for checking, and used the new model.
- Moving to a 32k context summarized with the new model and retained all original messages.
- An isolated copy of the reported job changed from Flash-Next to Qwen Q5/Q8/196,608 tokens without a restart request. Original history bytes were unchanged. This was a controlled routing test, without generation or tool actions over the user's conversation.
- 366 core checks and 82 service tests passed, including WebView2, history recovery, queueing and model switching.
- A real Minimal upgrade exited 0. All 82 service tests also passed in the installed application. Installed source and both manuals matched the distribution, and normal Marvin opened with Qwen Q5 Ready.
- Full passed its build and relocated private-Python checks, including API startup and llama.cpp DLL loading. Inference runtime and dependencies were unchanged.

The [release manifest](release-1.8.2.json) identifies current installers, manuals and hashes. Offline updates replace changed distribution files without repacking weights, WebView2 or the inference environment.
