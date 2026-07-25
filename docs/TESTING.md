# Testing

## Fast checks

```powershell
python -m compileall -q src tools tests
python -m tabnanny src tools tests
python -m unittest discover -s tests -v
```

The unit suite covers formats, metadata filtering and escaping, progress
parsing, output collision handling, advanced overrides, updater version
comparison, download cancellation, checksums, manifest validation, and ZIP
path traversal rejection.

## End-to-end codec validation

```powershell
python tools/validate_codecs.py
```

This generates a Unicode-named source and tests all 16 target formats plus
both MP3 encoders. It also checks recursive output layout, folder-level
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
   commands. Verify that each opens the same Easy Audio Converter category on
   the requested standard or advanced tab. Confirm that NVDA Settings lists
   only one Easy Audio Converter category, then traverse every enabled control
   and both tabs.
3. Select “Copy selected metadata fields” and verify that every field is
   announced as a check box with its checked state.
4. Start a multi-file job and verify that visual progress does not flood
   speech with automatic percentages.
5. Test the report, hide, reopen, cancel, and close buttons in the progress
   window.
6. Test successful, empty-input, corrupt-input, and Explorer-selection jobs.
7. Open and dismiss the destination selectors, folder confirmation, update
   dialog, and support page.
8. Review the NVDA log for add-on import, callback, and traceback errors.
9. Hide an existing `NVDASettingsDialog` through the NVDA Python console and
   verify that each add-on settings command discards it and opens the unified
   category on the requested tab.

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
