# Easy Audio Converter 1.8.0

This release adds independent conversion jobs while keeping the safe queue as
the default behavior when another conversion is already running.

- Added a configurable busy-job policy: queue new conversion requests or start
  them in independent progress windows.
- Added independent conversion controllers with their own FFmpeg workers,
  progress windows, and result reports.
- Kept cancellation, stop-after-current, progress, status, and queue commands
  available across active jobs.
- Preserved completed results from independent jobs until NVDA shuts down and
  added lifecycle cleanup for every conversion controller.
- Added accessible status messages for queued jobs and separate conversions.
- Updated the add-on version and all packaged translation catalog headers.

The add-on continues to use CPU audio encoders. GPU acceleration is not used
for MP3, AAC, FLAC, Opus, or WavPack encoding.
