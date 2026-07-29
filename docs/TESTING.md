# Testing

## Fast checks

```powershell
python -m compileall -q src tools tests
python -m tabnanny src tools tests
python -m unittest discover -s tests -v
```

The unit suite covers formats, metadata filtering and escaping, progress
parsing, output collision handling, advanced overrides, updater version
comparison, complete profile serialization, skipped-file reasons, remaining
time, results reports, notification modes, balanced NVDA popup state, download
cancellation, filename templates, media-information parsing, EBU R128
arguments, artwork mapping, stop-after-current behavior, queue recovery,
stream-copy validation, standalone settings-window lifecycle, checksums,
manifest validation, and ZIP path traversal rejection.

## End-to-end codec validation

```powershell
python tools/validate_codecs.py
```

This generates Unicode-named sources and tests all 17 encoder paths (the 16
encoded targets, with both MP3 encoders) plus original-stream extraction and
AAC-to-M4A remuxing. It verifies that compressed packet payloads are unchanged,
that no video stream reaches the output, and that non-AAC input is rejected by
the M4A copy mode. It also checks recursive output layout, folder-level
target-format skipping, explicitly selected same-format source protection,
all/selected/no metadata modes, real FFmpeg progress, and advanced
sample-rate/channel settings.

## Stress and extreme cases

```powershell
python tools/stress_test.py --files 250
```

The stress suite creates a deep Unicode source tree with long names, converts
hundreds of files, ensures progress never moves backwards, checks output-tree
exclusion and memory use, then cancels a long active encode and verifies that
the FFmpeg process stops and its partial result is removed.

The file count can be raised to 5000 when sufficient time and disk space are
available.

## Interactive NVDA speech validation

Automated tests do not replace testing the actual wx interface with NVDA:

1. Open NVDA Speech Viewer.
2. Press Insert+N, open Tools, Easy Audio Converter, and use both settings
   commands. Verify that each opens the standalone Easy Audio Converter window
   on the requested Standard or Advanced settings tab. Confirm that main NVDA
   Preferences lists no Easy Audio Converter category. Traverse all three
   tabs and the OK and Cancel buttons; verify that Cancel discards changes and
   OK preserves them after reopening. In particular, verify that the custom
   LUFS, dBTP, and LRA fields have distinct spoken names.
3. Select “Copy selected metadata fields” and verify that every field is
   announced as a check box with its checked state.
4. Open “Convert selected files or folders with options”. Traverse the
   complete dialog, switch each built-in profile, save and remove a temporary
   user profile, and verify that canceling does not change defaults.
5. Import and export user profiles, replace a same-name profile, reject an
   invalid or oversized JSON file, and verify that built-in profiles cannot be
   replaced through import.
6. Enter templates with metadata, literal prefixes and suffixes, reserved
   Windows names, invalid characters, and colliding output names. Verify the
   preview and exact planned output paths.
7. Review a plan containing supported, unsupported, and already-target-format
   files. Verify destination, free space, duration, size estimate, skipped
   reasons, and the lossy-to-lossy warning.
8. Open information for exactly one tagged file with artwork and chapters.
   Traverse and copy the complete report, then test empty and multiple
   selections.
9. Test every successful-completion notification mode and all three sound-test
   buttons. Verify milestone, per-file, and on-demand progress announcement
   modes.
10. Convert measured audio with every loudness preset and a custom target.
    Confirm that NVDA reports the analysis, second pass, and optional
    verification stages.
11. Convert tagged chaptered audio to supported and unsupported artwork
    targets. Inspect the outputs with FFmpeg and verify full-decode duration
    checking.
12. Extract audio from video files whose first audio streams are AAC and MP3.
    Verify automatic `.aac` and `.mp3` output names, no output video stream,
    unchanged audio codec, and disabled quality, loudness, metadata, artwork,
    chapter, and advanced controls.
13. Remux an AAC stream to M4A and verify it is not re-encoded. Try the same
    mode with MP3 and a video without audio; verify both are skipped with the
    correct spoken reason.
14. Start a multi-file job and verify that visual progress does not flood
   speech with automatic percentages.
15. Add two jobs while another is active. Verify spoken queue positions,
    sequential execution, queue reporting and clearing, immediate cancel, and
    stop after exactly the current file.
16. Test the report, remaining-time estimate, hide, reopen, cancel, results,
    and close buttons in the progress window.
17. Run a mixed valid, corrupt, and already-target-format folder. Confirm that
   the results window lists success, failure, and skip rows; copy its report;
   open the output folder; then repair the corrupt source and retry only that
   failed file.
18. Test successful, empty-input, corrupt-input, and Explorer-selection jobs.
19. Open and dismiss the destination selectors, folder confirmation, update
   dialog, and support page.
20. While the standalone settings window is already open, invoke its input
    gesture again and verify that focus returns to the existing window instead
    of creating a duplicate.
21. Review the NVDA log for add-on import, callback, and traceback errors.

## Translation validation

```powershell
python tools/poedit_catalog.py validate
python tools/poedit_catalog.py compile
```

Validation rejects missing translations and mismatched formatting
placeholders.

## Package validation

```powershell
python tools/build_addon.py
git diff --check
```

The build verifies required members, ZIP integrity, path layout, and absence
of Python cache files.
