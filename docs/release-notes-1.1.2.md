# Easy Audio Converter 1.1.2

- Folder conversion now leaves files already using the target extension
  unchanged. Directly selected same-format files remain available for
  intentional re-encoding without overwriting the source.
- The `.wave` input extension is now recognized.
- Spoken collection and completion messages include the number of skipped
  files.
- Settings and advanced codec settings recover from a stale hidden NVDA
  Settings instance and always open the requested visible category.
- The bundled executable now uses the official FFmpeg 8.1.2 Essentials build.
  The executable fell from 242,496,512 to 101,897,728 bytes while all 16 output
  formats and both MP3 encoder paths remain available.

This release was tested through the actual Insert+N menu with NVDA Speech
Viewer. Validation included both normal and deliberately hidden settings
windows, mixed WAV/MP3 folder jobs, direct same-format conversion, all codec
paths, translations, stress, cancellation, and package integrity.
