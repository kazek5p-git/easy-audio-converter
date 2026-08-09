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
manifest validation, ZIP path traversal rejection, and source-replacement
safety after success, FFmpeg failure, verification failure, and deletion
failure.

## End-to-end codec validation

```powershell
python tools/validate_codecs.py
```

This generates Unicode-named sources and tests all 17 encoder paths (the 16
encoded targets, with both MP3 encoders) plus original-stream extraction and
AAC-to-M4A remuxing. It also encodes and decodes all 13 FLAC levels and all
nine named WavPack profiles, comparing their PCM hashes with the source. It
verifies that copied packet payloads are unchanged, that no video stream
reaches the output, and that non-AAC input is rejected by the M4A copy mode.
It also checks recursive output layout, folder-level
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

## Performance and parallelism

The default automatic mode uses a bounded number of parallel FFmpeg workers
for independent files. To compare modes on the same machine, use a batch of
at least 16 similarly sized sources and select one worker, then automatic mode
in the Processing and notifications settings. Confirm that both summaries
contain every file, output names remain unique, progress reaches 100 percent,
and cancellation removes every partial output. The add-on passes `-threads 0`
to FFmpeg; GPU use is intentionally not expected because the exposed targets
are audio encoders.

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
   Dla FLAC sprawdź listę poziomów 0–12, a dla WavPack profile od szybkiego do
   `-hhx6`; po ponownym otwarciu ustawień wybrany profil ma pozostać aktywny.
3. Select “Copy selected metadata fields” and verify that every field is
   announced as a check box with its checked state.
4. Open “Convert selected files or folders with options”. Traverse the
   complete dialog, switch each built-in profile, save and remove a temporary
   user profile, and verify that canceling does not change defaults.
   Zapisz profile z włączoną i wyłączoną opcją zachowywania dat, a następnie
   sprawdź w Eksploratorze, czy wynik otrzymał datę utworzenia i modyfikacji
   pliku źródłowego.
   Zapisz także profil zastępujący źródła. Sprawdź ostrzeżenie z domyślną
   odpowiedzią „Nie”, anulowanie bez utraty źródła oraz usunięcie źródła
   dopiero po poprawnej konwersji i weryfikacji.
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
15. In Processing and notifications, switch between automatic, one-worker,
   and an explicit multi-worker count. Convert at least four files and verify
   the spoken worker count, unique outputs, monotonic overall progress,
   immediate cancellation of all active FFmpeg processes, and boundary-stop
   behavior for files that have not started.
16. Add two jobs while another is active. Verify spoken queue positions,
   sequential execution, queue reporting and clearing, immediate cancel, and
   stop after exactly the current file.
17. Test the report, remaining-time estimate, hide, reopen, cancel, results,
   and close buttons in the progress window.
18. Run a mixed valid, corrupt, and already-target-format folder. Confirm that
   the results window lists success, failure, and skip rows; copy its report;
   open the output folder; then repair the corrupt source and retry only that
   failed file.
19. Przetestuj zadania zakończone sukcesem, bez danych wejściowych, z
    uszkodzonym plikiem oraz z zaznaczeniem w Eksploratorze. Otwórz menu
    Narzędzia NVDA po zaznaczeniu pliku i sprawdź, czy zapamiętane zaznaczenie
    zostaje przekazane do konwersji. Gdy zaznaczenia nie da się odzyskać, oba
    polecenia dotyczące zaznaczonych elementów mają otworzyć standardowe okno
    wyboru wielu plików. Sprawdź również osobne polecenia wyboru plików i
    folderu. NVDA ma odczytać odpowiednio „Wybierz pliki do konwersji” oraz
    „Wybierz folder do konwersji” wraz z aktywną kontrolką, bez wpisu o
    zamrożeniu w dzienniku.
20. Open and dismiss the destination selectors, folder confirmation, update
   dialog, and support page.
21. While the standalone settings window is already open, invoke its input
    gesture again and verify that focus returns to the existing window instead
    of creating a duplicate.
22. Review the NVDA log for add-on import, callback, and traceback errors.
23. Zamknij NVDA skrótem Insert+Q i przetestuj polecenie Uruchom ponownie
    NVDA. Dziennik ma kończyć się wpisem `NVDA exit`, bez zdarzenia `APPCRASH`
    ani informacji o uszkodzeniu sterty.

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
