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
both MP3 encoders. It also checks recursive output layout, same-format source
protection, all/selected/no metadata modes, real FFmpeg progress, and advanced
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
