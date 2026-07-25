# Easy Audio Converter for NVDA

Easy Audio Converter is an accessible NVDA add-on for converting one file,
multiple selected files, selected folders, or the current Windows Explorer
folder. It includes the official 64-bit Windows FFmpeg Essentials build, so no
separate codec installation is required.

## Main features

- converts popular audio and media inputs supported by FFmpeg;
- produces MP3, WAV, FLAC, Ogg Vorbis, Opus, M4A/AAC, AAC, WMA, ALAC,
  AIFF, AC-3, E-AC-3, WavPack, MP2, AMR-NB, and AMR-WB;
- offers economical, standard, high, and very high quality presets;
- provides LAME and Windows Media Foundation (Fraunhofer-compatible) MP3
  encoder choices;
- saves next to each source or in a selected destination folder;
- optionally includes subfolders and preserves their structure;
- skips files already using the target extension when scanning a folder,
  while still allowing an explicitly selected same-format file to be
  re-encoded;
- never overwrites source or existing destination files;
- shows quiet visual per-file and overall progress while conversion runs in a
  background thread, with a dedicated button for spoken status;
- plays a notification sound when the complete job finishes without errors;
- copies all, selected, or no source text metadata;
- stores independent advanced parameter profiles for each target codec;
- checks GitHub releases for verified add-on updates;
- exposes every action in NVDA's Input Gestures dialog for custom shortcuts;
- ships standard PO, MO, and POT files compatible with Poedit;
- includes the author's optional support prompt used by Sonic Pitch.

The add-on is authored by Kazimierz Parzych.

## Project layout

- `src` contains the installable add-on tree.
- `tests` contains unit tests for the conversion core.
- `tools/build_addon.py` creates the `.nvda-addon` package.
- `tools/poedit_catalog.py` creates the POT template, merges PO files,
  validates placeholders, and compiles MO catalogs.
- `tools/generate_locales.py` can fill missing translations while preserving
  translations already edited by people.
- `tools/validate_codecs.py` performs end-to-end checks with bundled FFmpeg.
- `tools/stress_test.py` tests large recursive jobs and active cancellation.

## Translating with Poedit

The template is `src/locale/EasyAudioConverter.pot`. To add a language, open
the POT in Poedit, create a translation, and save it as
`src/locale/<language>/LC_MESSAGES/nvda.po`. Enable automatic MO compilation
in Poedit or run:

```powershell
python tools/poedit_catalog.py compile
```

After changing source strings, update the template and merge existing
catalogs without discarding translations:

```powershell
python tools/poedit_catalog.py pot
python tools/poedit_catalog.py merge
```

See `docs/TRANSLATING.md` for the complete workflow.

## Build

Place the official Gyan FFmpeg release Essentials `ffmpeg.exe` in
`src/globalPlugins/easyAudioConverter/bin/ffmpeg.exe`, then run:

```powershell
python tools/build_addon.py
```

The package is written to `dist`.

Before a release, run:

```powershell
python -m unittest discover -s tests -v
python tools/validate_codecs.py
python tools/stress_test.py --files 250
python tools/poedit_catalog.py validate
python tools/build_addon.py
```
