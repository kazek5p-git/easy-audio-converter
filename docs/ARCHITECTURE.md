# Architecture

## Runtime components

- `globalPlugins/easyAudioConverter/__init__.py` integrates with NVDA,
  Windows Explorer, settings, scripts, menus, progress UI, and update prompts.
- `converter.py` is independent of NVDA. It collects files, builds validated
  FFmpeg commands, parses duration/progress/metadata, handles output naming,
  and owns cancellation and partial-file cleanup.
- `updater.py` is independent of NVDA. It reads GitHub release metadata,
  compares versions, downloads with bounded memory, verifies SHA-256 when
  GitHub supplies a digest, validates the ZIP and manifest, and rejects unsafe
  archive paths.
- `bin/ffmpeg.exe` is invoked as a separate process with argument arrays.
  Commands never use `shell=True`.

## Conversion lifecycle

1. The NVDA plug-in reads a snapshot of the settings.
2. The worker collects supported input files before writing outputs. Folder
   scans skip files whose extension already matches the target; an explicitly
   selected file remains eligible for intentional same-format conversion.
3. For each file, FFmpeg is queried for duration and, when needed, metadata.
4. A collision-free output path is reserved.
5. FFmpeg writes key/value progress to `pipe:1`; stderr is drained in parallel.
6. The worker stores the newest progress snapshot and updates the visual UI
   through `wx.CallAfter`.
7. Success is accepted only when FFmpeg exits with zero and creates a nonempty
   output. Failed or canceled partial outputs are removed.

## Metadata

The three modes are:

- `all`: FFmpeg maps all global text metadata;
- `selected`: FFmpeg exports global metadata to its `ffmetadata` format, the
  add-on filters the selected keys, then writes only those keys;
- `none`: source metadata mapping is disabled.

Artwork is a media stream rather than text metadata and is intentionally not
included by the metadata selector.

## Advanced codec profiles

Profiles are stored as JSON in the NVDA configuration, separately for each
target format. Only validated values are converted into FFmpeg arguments:

- bitrate;
- sample rate where the format permits an override;
- mono or stereo channel count;
- codec-specific compression, quality, or complexity level;
- PCM bit depth for WAV and AIFF.

Raw command-line fragments are not accepted.

## Settings-window recovery

NVDA allows only one `NVDASettingsDialog` instance. Before opening either
Easy Audio Converter category from the Tools menu, the add-on removes any
stale hidden instance left in wx and then opens the requested category. A
visible settings dialog is left untouched and receives NVDA's normal
single-instance behavior.

## Bundled FFmpeg

The package uses Gyan's official FFmpeg 8.1.2 Essentials static build. It
retains every decoder and encoder used by the add-on, including LAME, Media
Foundation MP3, Vorbis, Opus, AMR-NB, and AMR-WB, without the many additional
libraries present only in the full build.

## Update trust model

The updater accepts only the configured public GitHub repository. It:

1. reads the latest non-draft GitHub release;
2. selects a `.nvda-addon` asset;
3. streams it to a `.part` file;
4. verifies length and the GitHub SHA-256 digest when present;
5. verifies ZIP integrity, safe paths, add-on name, and version;
6. atomically renames the file;
7. opens NVDA's normal add-on installer, which still asks the user to confirm.
