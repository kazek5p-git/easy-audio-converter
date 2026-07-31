# Easy Audio Converter 1.4.0

This release adds profile-aware source-date preservation and named lossless
compression choices.

- A new “Preserve source file creation and modification dates” option is
  available in the standard settings and in the one-time conversion dialog.
- The option is stored in custom conversion profiles and retained by the
  built-in profiles as part of the user's output policy.
- After a successful conversion, original-stream extraction, or AAC-to-M4A
  remux, the completed output receives the source file's creation and
  modification dates.
- Windows creation dates are copied with the native `SetFileTime` API, so the
  value displayed by File Explorer is preserved as well.
- Advanced FLAC profiles now provide a named level list from 0 through 12.
- Advanced WavPack profiles expose the native FFmpeg mappings as accessible
  choices: fast, normal, high (`-h`), very high (`-hh`), `-hhx1` through
  `-hhx4`, and maximum `-hhx6`.

Date preservation is disabled by default, so existing user configurations
keep their previous behavior after updating.
