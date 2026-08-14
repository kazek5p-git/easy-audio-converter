# Easy Audio Converter 1.9.0

This release adds an optional GOGO-no-coda MP3 backend for WAV/WAVE sources
and makes conversion progress easier to identify in the taskbar and window
list.

- Added the bundled GOGO-no-coda encoder as an MP3 backend for WAV/WAVE files.
- Added settings for a custom `gogo.exe`, bitrate presets, GOGO quality, and
  additional command-line arguments.
- Added GOGO command preview, executable help, validation, cancellation,
  output verification, profiles, queued jobs, and parallel conversion support.
- Kept the existing FFmpeg LAME and Fraunhofer/Windows Media Foundation
  backends unchanged.
- Added the overall conversion percentage at the beginning of every progress
  window title, followed by the conversion status and add-on name.

The release package contains the bundled encoder and is ready for installation
in NVDA.
