# Review of the 1.18.0 update

30 September 2026. Source baseline: the 1.17.4 application commit `b8cf075`.
Reviewed update: `8be0831`, including the MTP implementation in `7e47a73`
and the exFAT packaging changes in `db6a43d`. Workspace and MTP corrections were
installed locally as 1.18.1. The launcher follow-up is packaged as 1.18.2.

## Confirmed findings

1. **Startup crashes before fetching application state.**
   `App` initially holds `app = null`. Computing the compression activity label
   read `app.active` before the loading-screen guard, producing
   `TypeError: Cannot read properties of null (reading 'active')` and an empty
   workspace. This was reproduced against the installed 1.18.0 bundle
   `index-D1-kz05q.js`. The null-safe read fixes startup without changing MTP.

   The unsafe source line predates the MTP update (`49af326`), and therefore
   is not a newly introduced line in the 1.17.4-to-1.18.0 source diff. The retained
   earlier installed bundle `index-s5ViK5cG.js` evaluates that label inside the
   already-loaded workspace instead and renders successfully against the same
   disposable API. Its SHA-256 is
   `5ae27864cdaa69455ea28cad3a125a6dfd51a9c4c68cb5d23f7cc4fd0ee37d3d`.
   This source/artifact mismatch explains why source-only checks missed the
   user-visible startup regression; the retained file alone does not establish
   the exact contents of every previous published installer.

2. **Settings changed during memory recovery can be ignored by the next task.**
   A task starts on `q8_0_mtp`; the owner chooses `f16` while it is running;
   a memory event drops the draft and recovers the task on `q8_0`. Recovery used
   the current global preference and incorrectly marked the running Q8 profile
   as serving the new F16 choice. The next task then skipped the necessary
   profile change. Recovery now uses the active job's captured request and
   passes that intent explicitly to the model controller. The owner selection
   remains intact and the next task applies it.

3. **A new model request can retain an obsolete served-profile marker.**
   `setdefault` preserved an earlier MTP request after a successful explicit
   start on F16. Conversely, reuse of a matching plain profile copied the old
   MTP intent even when the owner explicitly selected plain. This leaves task
   restart decisions inconsistent with the loaded profile. Every explicit
   request now records its own intent; recovery separately identifies the
   earlier request it continues to serve. Reusing a matching profile still
   avoids an unnecessary restart.

## Remaining update scope

- Reviewed the MTP toggle, plain/MTP profile pairing, profile filtering, demotion
  notice/retry action, budget preset recall, preference persistence, autostart,
  active-task handover, model rollback and recovery paths.
- Browser checks cover Simple and Advanced toggles, retaining MTP when changing
  context, disabling it for unsupported F16 profiles, delayed initial state,
  API failure display and successful reload. No other defect was confirmed in
  these checked paths.
- The exFAT changes provide copy fallback for staging and Full-runtime checks;
  they do not modify application execution. The remaining differences are
  release records, version metadata, localization, screenshots and manuals.
- The package-lock root version was still 1.9.0. It is synchronized to 1.18.1;
  dependency versions and the measured hardware profiles are unchanged.

## Regression checks

The startup browser test failed against 1.18.0 and passes after repair. Both
memory-selection regression tests failed before repair and pass afterward.
The matching-profile reuse case is also covered by a controller test.

Run the browser checks against disposable data, not personal settings:

```powershell
& .venv/Scripts/python.exe -B tests/serve_workspace_fixture.py
npx.cmd --yes --package @playwright/cli playwright-cli -s=release-check open http://127.0.0.1:7878
npx.cmd --yes --package @playwright/cli playwright-cli -s=release-check run-code --filename tests/workspace_startup.browser.js
npx.cmd --yes --package @playwright/cli playwright-cli -s=release-check run-code --filename tests/workspace_mtp.browser.js
npx.cmd --yes --package @playwright/cli playwright-cli -s=release-check close
```

An API/model-only smoke check does not establish that React rendered. Verify the
built workspace in a browser and the installed desktop window before releasing.
The targeted application, memory-profile and restart suites passed 87 tests.
The full 1.18.1 unittest suite passed 367 tests and the core suite passed 361
checks. The Minimal upgrade exited 0. All 15 existing history files retained
their SHA-256 values and installation preserved the complete preferences file.
State, selected-chat and detail endpoints returned HTTP 200. The actual WebView2
window rendered the existing conversation and reported Q5 Ready with
`q8_0_128k_mtp`; the served sources and frontend matched the built files.

## Additional launcher finding

The taskbar exposed an otherwise hidden `GDI+ Window (Marvin.exe)` beside the
workspace. `_focus_window` enumerated every desktop window whose title contained
`Marvin`, then called `ShowWindow(SW_RESTORE)` on all matches. That includes
the graphics helper and can also raise windows belonging to other processes.
The offending logic predates this update (August 2026).

The callback now receives the exact window returned by `webview.create_window`
and focuses its native WinForms handle. It neither enumerates nor restores
helper windows. Native handle initialization is retried and Windows API handle
arguments are explicitly typed. Three unit tests cover the target window,
delayed native creation and missing/invalid handles.

After the owner closed the application and requested completion, the 1.18.2
upgrade includes this launcher correction together with the workspace/MTP fixes.
The standalone native-window probe passed: the callback receives the created
window, the main window is restored, and both hidden matching-title helpers
remain hidden. An invalid model request also remains covered by the controller's
failure handler rather than leaving startup permanently in progress.

Final 1.18.2 checks passed 371 unittests and 361 core checks. The frontend build
and the isolated Full-runtime check passed. Both installers were compiled and
the staged release assets matched every SHA-256 entry. The actual Minimal
upgrade exited 0; the installed executable, launcher, service files and frontend
matched the built files. All 15 original history files still matched their
pre-upgrade hashes. The new API returned version 1.18.2 and all 15 chats.

The final Computer Use check was cancelled by the user's physical Escape key.
No further desktop automation was performed. The installed launcher subsequently
recorded its normal shutdown and was closed at the last process check. The
taskbar check on the installed executable was therefore not completed; the
standalone test with real main/helper windows passed.
