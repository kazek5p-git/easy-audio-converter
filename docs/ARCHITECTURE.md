# Architecture

## Runtime components

- `globalPlugins/easyAudioConverter/__init__.py` integrates with NVDA,
  Windows Explorer, settings, scripts, menus, progress UI, and update prompts.
- `converter.py` is independent of NVDA. It collects files, builds validated
  FFmpeg commands, parses duration/progress/metadata, handles output naming,
  and owns cancellation and partial-file cleanup.
- `profiles.py` is independent of NVDA. It validates, bounds, versions, and
  deterministically serializes complete named conversion snapshots.
- `updater.py` is independent of NVDA. It reads GitHub release metadata,
  compares versions, downloads with bounded memory, verifies SHA-256 when
  GitHub supplies a digest, validates the ZIP and manifest, and rejects unsafe
  archive paths.
- `bin/ffmpeg.exe` is invoked as a separate process with argument arrays.
  Commands never use `shell=True`.

## Conversion lifecycle

1. The NVDA plug-in reads a snapshot of the settings.
2. The worker collects supported input files before writing outputs. For
   encoded targets, folder scans skip files whose extension already matches
   the target; an explicitly selected file remains eligible for intentional
   same-format conversion. Original-stream extraction has no fixed target
   extension, so every supported source remains eligible.
3. For each file, FFmpeg is queried for duration and, when needed, metadata.
4. A collision-free output path is reserved.
5. FFmpeg writes key/value progress to `pipe:1`; stderr is drained in parallel.
6. The worker stores the newest progress snapshot and updates the visual UI
   through `wx.CallAfter`.
7. Success is accepted only when FFmpeg exits with zero and creates a nonempty
   output. Failed or canceled partial outputs are removed.
8. Optional deep verification and source-date copying finish before the
   source-replacement policy is applied. Replacement requires a separate
   warning that defaults to No. A source is deleted only after every enabled
   success check passes; deletion failure keeps the completed output and
   records its path as a non-retryable failure.
9. The summary retains bounded details for successful, failed, and skipped
   inputs, including source paths required for a safe failed-file retry.
10. When every planned file succeeds, NVDA applies the configured completion
   notification mode and can play the bundled sound asynchronously through
   its configured sound output device.

## One-time jobs and named profiles

Quick conversion continues to read the standard NVDA configuration. “Convert
with options” instead creates an immutable settings snapshot for one job. It
can optionally write that snapshot back as the future quick-conversion
default.

Named profiles use a versioned JSON object stored as one NVDA string setting.
Each entry includes format, quality, MP3 encoder, destination and source
replacement policies, subfolder and structure behavior, metadata mode and
fields, and the validated advanced codec options. Loading rejects unknown
schema versions, invalid keys, duplicate or empty names, and values outside
supported bounds. The list is limited to 50 profiles and names to 80
characters.

## Results and retry

The results window is modeless and retains the most recent summary. It lists
successful outputs, failed sources with friendly error explanations, and up
to 500 skipped-file details while preserving the full skipped count. A retry
uses only stored failed source paths together with the immutable settings and
source root from the original job. Existing outputs remain protected by the
normal collision-free naming logic.
When source deletion fails after a valid output has been produced, that output
is shown with its path and can be opened, but it is excluded from retry to
avoid creating an unnecessary second converted copy.

## Progress and notifications

Remaining time is estimated from elapsed time and bounded overall progress;
very early or implausibly long estimates are reported as still calculating.
Automatic speech can occur at milestones, for every file, or only when the
user requests status. Successful completion supports speech and sound,
speech only, sound only, or no completion notification. Failure and
cancellation summaries remain spoken for safety.

## Metadata

The three modes are:

- `all`: FFmpeg maps all global text metadata;
- `selected`: FFmpeg exports global metadata to its `ffmetadata` format, the
  add-on filters the selected keys, then writes only those keys;
- `none`: source metadata mapping is disabled.

Artwork is a media stream rather than text metadata and is intentionally not
included by the metadata selector.

## Stream-copy modes

Both no-re-encoding modes probe the first audio stream during planning, map
exactly `0:a:0`, and pass `-c:a copy` to FFmpeg. They never apply quality
presets, loudness filters, resampling, channel conversion, or advanced codec
overrides.

Original-stream extraction chooses an output extension from the detected
codec, including AAC, MP3, Opus, Vorbis, FLAC, ALAC, WAV PCM, and AIFF PCM.
An uncommon stream that has no dedicated raw extension is placed in `.mka`,
which is the safe generic audio-container fallback. This mode deliberately
strips text metadata, artwork, video, and chapters so the result contains only
the unchanged first audio stream.

AAC-to-M4A remuxing accepts only a detected AAC first stream. Other codecs and
files without audio become explicit preflight skips instead of failed FFmpeg
jobs. M4A metadata, artwork, and chapters can follow the normal preservation
settings because the target container is known. Deep verification checks both
decodability/duration and that the output codec still matches the source.

## Advanced codec profiles

Profiles are stored as JSON in the NVDA configuration, separately for each
target format. Only validated values are converted into FFmpeg arguments:

- bitrate;
- sample rate where the format permits an override;
- mono or stereo channel count;
- codec-specific compression, quality, or complexity level;
- PCM bit depth for WAV and AIFF.

Lossless compression uses named, bounded choices. FLAC accepts levels 0–12.
The native FFmpeg WavPack encoder accepts levels 0–8, mapped to fast, normal,
high (`-h`), very high (`-hh`), extra `-hhx1` through `-hhx4`, and maximum
`-hhx6` profiles. The WavPack command names are descriptions; only the
validated FFmpeg `-compression_level` integer is passed to the process.

Raw command-line fragments are not accepted.
Stream-copy modes always disable these overrides.

## Standalone settings window

The add-on does not register a category in
`NVDASettingsDialog.categoryClasses`. Both settings commands live under
Tools, Easy Audio Converter and open one standalone modal `wx.Dialog`. Its
native notebook contains scrollable Standard, Advanced settings, and
Processing and notifications pages; the command selects the requested tab.
The notebook exposes its real three-page count to MSAA.

OK validates the filename template, saves all three pages, and persists the
NVDA configuration. Cancel or Escape closes the dialog without calling any
page's save method. A retained dialog reference prevents duplicates, and
NVDA's `prePopup` and `postPopup` lifecycle calls remain balanced.

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
