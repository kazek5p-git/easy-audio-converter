# Easy Audio Converter 1.3.0

This release adds a professional planning and quality-control workflow while
keeping direct quick conversion available.

- Review an accessible conversion plan before folder and one-time jobs. It
  includes exact output paths, skipped files, destination, total duration,
  estimated output size, free disk space, and lossy-to-lossy warnings.
- Create safe filenames from metadata templates such as
  `{artist} - {title}`. Literal prefixes and suffixes are supported, invalid
  Windows characters are sanitized, and existing files remain protected.
- Read technical information for one selected file: container, codec,
  duration, bitrate, channels, sample rate, file size, text tags, cover
  artwork, and chapter count.
- Normalize loudness with a professional two-pass EBU R128 process using
  podcast (-16 LUFS), music/streaming (-14 LUFS), broadcast (-23 LUFS), or
  custom targets.
- Optionally preserve embedded cover artwork and chapters when supported.
- Optionally verify every output by decoding the complete file and comparing
  its duration with the source.
- Add more jobs while conversion is active. Jobs run sequentially and can be
  reported or cleared.
- Finish the active file and then stop the job, independently of immediate
  cancellation.
- Import and export complete user conversion profiles through bounded,
  versioned JSON files.
- Use separate configurable sounds for successful completion, errors, and
  cancellation/stopping.
- Extract the first original audio stream from video and other media without
  re-encoding. The add-on keeps the codec and selects an appropriate output
  extension automatically, using Matroska Audio only as a safe fallback.
- Remux AAC directly to M4A without re-encoding. A source whose first audio
  stream is not AAC is clearly reported and skipped.
- Configure the add-on from Tools, Easy Audio Converter, Settings. The
  standalone, resizable window has Standard, Advanced settings, and
  Processing and notifications tabs plus standard OK and Cancel buttons. It
  no longer adds an item to NVDA's main Preferences list.

The bundled FFmpeg remains self-contained. Source and existing output files
are never overwritten.
