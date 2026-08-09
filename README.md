# Easy Audio Converter for NVDA

Easy Audio Converter is an accessible NVDA add-on for converting one file,
multiple selected files, selected folders, or the current Windows Explorer
folder. It includes the official 64-bit Windows FFmpeg Essentials build, so no
separate codec installation is required.

## Main features

- converts popular audio and media inputs supported by FFmpeg;
- keeps the Explorer selection available after the NVDA Tools menu opens and
  falls back to a native multiple-file picker when no selection can be found;
- produces 16 encoded formats: MP3, WAV, FLAC, Ogg Vorbis, Opus, M4A/AAC,
  AAC, WMA, ALAC, AIFF, AC-3, E-AC-3, WavPack, MP2, AMR-NB, and AMR-WB;
- extracts the first original audio stream from a video or other media file
  without re-encoding, automatically choosing a safe extension for its codec;
- remuxes an AAC stream directly to M4A without changing its encoded audio;
- offers economical, standard, high, and very high quality presets;
- provides LAME and Windows Media Foundation (Fraunhofer-compatible) MP3
  encoder choices;
- saves next to each source or in a selected destination folder;
- optionally includes subfolders and preserves their structure;
- can preserve each source file's creation and modification dates on the
  completed output, including through named profiles;
- can optionally replace source files after successful conversion, with an
  irreversible-action warning that defaults to No and automatic protection
  after conversion, verification, or cancellation failures;
- skips files already using the target extension when scanning a folder,
  while still allowing an explicitly selected same-format file to be
  re-encoded;
- never writes a result over its source or an existing destination file;
- previews folder and one-time jobs with exact input/output paths, skipped
  counts, destination, duration, estimated size, free space, and
  lossy-to-lossy warnings;
- builds safe output names from metadata templates such as
  `{artist} - {title}`, including literal prefixes and suffixes;
- offers both unchanged quick conversion and an accessible one-time options
  dialog;
- includes complete named job profiles, with three built-in profiles and
  editable user profiles that can be imported and exported as bounded,
  versioned JSON;
- provides professional two-pass EBU R128 loudness normalization presets for
  podcasts, music/streaming, broadcast, and custom targets;
- can preserve embedded cover artwork and chapters when the target container
  supports them;
- can deeply verify each output by decoding it and comparing its duration;
- uses bounded parallel FFmpeg workers for independent files, with an
	automatic load-balancing mode that adapts to CPU and memory use, plus an
	explicit worker-count override; schedules the longest files first and weights
	batch progress by estimated work;
- uses a safe fast path without preliminary input probing when the plan is
	disabled and no codec, metadata, or loudness decision requires source
	information; reuses unchanged probes through a bounded cache;
- includes stage timing in the results report for input recognition, loudness
	analysis, encoding/output writing, and finalization;
- queues additional conversion jobs and supports both immediate cancellation
  and stopping after the current file;
- reports codec, container, duration, bitrate, channels, sample rate, size,
  tags, artwork, and chapters for one selected file;
- shows quiet visual per-file and overall progress while conversion runs in a
  background thread, with spoken status and estimated remaining time;
- lets the user choose milestone, per-file, or on-demand progress
  announcements;
- provides an accessible results window with details, report copying, output
  folder access, and retry of failed files;
- makes success speech/sound configurable and provides separate optional
  sounds for errors and cancellation;
- copies all, selected, or no source text metadata;
- lets each job or named profile override common tags such as title, BPM,
  description, compilation, ISRC, track/disc totals, and sort fields;
- stores independent advanced parameter profiles for each target codec,
  including FLAC levels 0–12 and named WavPack modes through `-hhx6`;
- asks FFmpeg to use its automatic thread selection and explains why GPU
  acceleration is not applicable to the add-on's audio encoders;
- provides one standalone, resizable settings window under NVDA's Tools menu,
  with three accessible tabs and standard OK and Cancel buttons;
- provides direct Tools-menu commands for choosing multiple files or one
  folder through standard Windows dialogs;
- checks GitHub releases for verified add-on updates;
- exposes every action in NVDA's Input Gestures dialog for custom shortcuts;
- ships standard PO, MO, and POT files compatible with Poedit;
- includes the author's optional support prompt used by Sonic Pitch.

The add-on is authored by Kazimierz Parzych.

## Project layout

- `src` contains the installable add-on tree.
- `tests` contains unit tests for the conversion core.
- `profiles.py` validates and serializes complete named conversion profiles.
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
