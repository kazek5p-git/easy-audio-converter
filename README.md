# Easy Audio Converter for NVDA

Easy Audio Converter is an accessible NVDA add-on for converting one file,
multiple selected files, selected folders, or the current Windows Explorer
folder. It includes a 64-bit Windows build of FFmpeg, so no separate codec
installation is required.

## Main features

- converts popular audio and media inputs supported by FFmpeg;
- produces MP3, WAV, FLAC, Ogg Vorbis, Opus, M4A/AAC, AAC, WMA, ALAC,
  AIFF, AC-3, E-AC-3, WavPack, MP2, AMR-NB, and AMR-WB;
- offers economical, standard, high, and very high quality presets;
- provides LAME and Windows Media Foundation (Fraunhofer-compatible) MP3
  encoder choices;
- saves next to each source or in a selected destination folder;
- optionally includes subfolders and preserves their structure;
- never overwrites source or existing destination files;
- runs conversion in a background thread and supports cancellation;
- exposes every action in NVDA's Input Gestures dialog for custom shortcuts;
- includes the author's optional support prompt used by Sonic Pitch.

The add-on is authored by Kazimierz Parzych.

## Project layout

- `src` contains the installable add-on tree.
- `tests` contains unit tests for the conversion core.
- `tools/build_addon.py` creates the `.nvda-addon` package.
- `tools/generate_locales.py` regenerates gettext catalogs.
- `tools/validate_codecs.py` performs end-to-end checks with bundled FFmpeg.

## Build

Place `ffmpeg.exe` in
`src/globalPlugins/easyAudioConverter/bin/ffmpeg.exe`, then run:

```powershell
python tools/build_addon.py
```

The package is written to `dist`.
