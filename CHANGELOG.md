# Changelog

## 1.9.1 - 2026-08-15

- Fixed add-on termination when NVDA is restarted or reloaded without active
  independent conversion jobs.
- Fixed cleanup so every independent job queue is cleared during termination.
- Kept the built-in update mechanism unchanged.

## 1.9.0 - 2026-08-14

- Added the overall conversion percentage at the start of the progress-window
  title, followed by the conversion status and add-on name.
- Added an optional GOGO-no-coda MP3 backend for WAV/WAVE sources with safe
  argument parsing, bitrate presets, `-q` quality selection, custom options,
  executable help, cancellation, verification, profiles, queues, and parallel
  jobs. The GOGO-no-coda 3.13 executable is now bundled; a custom executable
  may still be selected in the settings.

## 1.8.2 - 2026-08-12

- Added explicit GPL copyright and SPDX headers identifying Kazimierz Parzych
  in the add-on's Python source files.
- Split the NVDA integration, settings dialogs, and conversion dialogs into
  focused modules while preserving the public scripts and compatibility
  exports.
- Documented the naming conventions and module responsibilities in
  `docs/STANDARDY_KODU.md` and updated the architecture guide.

## 1.8.1 - 2026-08-12

- Marked the stable release as tested with stable NVDA 2026.1.1 so it can be
  submitted to the NVDA Add-on Store.

## 1.8.0 - 2026-08-12

- Added a configurable busy-job policy: new conversion requests are queued by
  default or can run in independent progress windows.
- Added independent controllers with separate FFmpeg workers, progress and
  results windows, while global cancellation, stop-after-current, status, and
  progress commands cover all active jobs.
- Retained completed independent-job results until NVDA shuts down and added
  lifecycle cleanup for every controller during NVDA termination.

## 1.7.0 - 2026-08-09

- Changed automatic parallel conversion from a one-time CPU estimate to an
  adaptive scheduler that reacts to sustained CPU and memory load between
  files without interrupting active conversions.
- Renamed the automatic worker choice to “Automatic (dynamic load balancing)”
  and documented its behavior in the settings and user guide.
- Added per-job and profile-aware metadata overrides with common extended tag
  fields such as BPM, description, compilation, ISRC, track/disc totals, and
  sort fields.
- Added a bounded, timestamp-aware probe cache for repeated technical and
  metadata reads.
- Added a safe fast path that skips preliminary probing when an ordinary encode
  does not need source information, while retaining probes for stream-copy,
  metadata-aware naming, selected metadata, and loudness analysis.
- Improved uneven batch scheduling with longest-processing-time-first ordering
  and work-weighted overall progress.
- Added stage timing to conversion results, covering input recognition,
  loudness analysis, encoding/output writing, and finalization.
- Added an accessible warning that restarting or closing NVDA interrupts an
  active conversion; the progress window now points users to the Cancel button.

## 1.6.0

- Added CPU-aware parallel conversion workers for independent files, with an
  automatic default and validated choices from one through 32 workers.
- Added safe cancellation propagation across all active FFmpeg processes and
  prevented new files from being scheduled after a boundary-stop request.
- Explicitly delegates codec and filter thread selection to FFmpeg with
  `-threads 0`; GPU acceleration remains disabled because the add-on's target
  codecs encode audio on the CPU.

## 1.5.0

- Added an optional, profile-aware source replacement mode. Every job requires
  an irreversible-action warning that defaults to No, and a source is deleted
  only after conversion, output checks, optional verification, and date
  preservation succeed.
- Kept completed outputs when source deletion fails, reported their exact
  paths, and excluded those cases from failed-file retry to prevent duplicate
  conversions.

## 1.4.0

- Added an optional, profile-aware setting that copies each source file's
  creation and modification dates to the completed output.
- Added named lossless-compression choices to each advanced codec profile:
  FLAC levels 0–12 and WavPack modes from fast through `-hhx6`.

## 1.3.1

- Fixed an NVDA crash during shutdown or restart by ensuring that the add-on
  submenu is destroyed exactly once.
- Restored Explorer selection detection after opening the NVDA menu by using
  the focus saved before entering the menu.
- When no selection can be recovered, conversion commands now open the
  standard Windows multiple-file selection dialog.
- Native file, folder, and destination selectors are now opened after the
  input script finishes. NVDA announces their titles and focused controls
  without reporting a frozen main thread.
- Added separate “Choose files to convert...” and “Choose a folder to
  convert...” commands to the Tools menu and NVDA Input Gestures.

## 1.3.0

- Added an accessible preflight plan with actual output names, skipped counts,
  destination, total duration, estimated output size, free disk space, and a
  lossy-to-lossy quality warning.
- Added metadata-aware output filename templates with Windows-safe
  sanitization, collision protection, and previews.
- Added selected-file technical information for codec, container, duration,
  bitrate, channels, sample rate, size, metadata, artwork, and chapters.
- Added professional two-pass EBU R128 loudness normalization with podcast,
  music/streaming, broadcast, and custom targets.
- Added optional embedded-cover and chapter copying plus deep output
  verification by full decode and duration comparison.
- Added a sequential job queue, queue reporting/clearing, and “stop after the
  current file” alongside immediate cancellation.
- Added safe JSON import and export for complete named profiles.
- Added separate configurable and testable success, error, and cancellation
  sounds.
- Added extraction of the first original audio stream without re-encoding,
  with automatic codec-aware output extensions and a safe Matroska fallback.
- Added direct AAC-to-M4A remuxing without re-encoding; non-AAC sources are
  identified and skipped before FFmpeg starts.
- Moved add-on settings out of the main NVDA Preferences list into one
  standalone, resizable window under Tools, with three accessible tabs and
  standard OK and Cancel buttons. Both settings commands open the requested
  tab in this same window.

## 1.2.0

- Added an accessible “Convert with options” workflow for one-time format,
  quality, destination, folder, metadata, and codec-profile choices without
  changing quick-conversion defaults.
- Added complete named conversion profiles with Audiobook MP3, Podcast Opus,
  and Archive FLAC built-ins plus safe user profile save, replace, and delete
  operations.
- Added an accessible results window listing successful, failed, and skipped
  files, with detailed reasons, a clipboard report, output-folder access, and
  retry of only the failed source files using the original job settings.
- Added friendly explanations for common permission, disk-space, damaged-file,
  and missing-audio-stream errors.
- Added configurable successful-completion notification modes: speech and
  sound, speech only, sound only, or none, with a sound-test button.
- Added automatic progress announcement modes for milestones, every file, or
  on-demand reporting only.
- Added estimated remaining time to the progress window and spoken status.
- Preserved bounded skipped-file details while retaining accurate totals for
  very large folder jobs.

## 1.1.3

- Combined the standard and advanced options into one Easy Audio Converter
  category in NVDA Settings, with separate accessible tabs.
- Kept both Tools-menu commands: each opens the unified category on the
  corresponding tab.
- Added a bundled notification sound that plays once when every file in a
  conversion job finishes successfully.

## 1.1.2

- Folder jobs now skip files that already use the selected target extension,
  while explicitly selected same-format files can still be re-encoded safely.
- Added the `.wave` input extension.
- Added spoken skipped-file counts to collection and completion summaries.
- Recovered automatically from a stale hidden NVDA Settings window, so both
  settings commands always produce a visible dialog from the NVDA Tools menu.
- Replaced the 242.5 MB full FFmpeg executable with the official 101.9 MB
  Essentials build while retaining every exposed input and output codec path.
- Re-tested the NVDA menu, both settings pages, mixed WAV/MP3 folders, all
  codecs, and error recovery with NVDA Speech Viewer.

## 1.1.1

- Replaced the metadata checklist with individually accessible check boxes
  whose checked states are spoken correctly by NVDA.
- Prevented visual progress bars from flooding speech with alternating
  percentages during batch conversion.
- Added a dedicated “Report conversion status” button to the progress window.
- Kept spoken status synchronized with the newest worker progress snapshot.
- Improved focus when opening, canceling, and completing a conversion.
- Corrected the Polish completion summary and validated the complete live UI
  with NVDA Speech Viewer.

## 1.1.0

- Added an accessible modeless progress window with per-file and overall
  FFmpeg progress, elapsed time, status reporting, hiding, and cancellation.
- Added metadata modes for copying all tags, selected text fields, or no
  source metadata.
- Added separate advanced profiles for every target codec: bitrate, sample
  rate, channels, codec-specific level, and PCM bit depth where supported.
- Added automatic and manual update checks through GitHub Releases with
  SHA-256 digest verification, archive validation, and NVDA's installer.
- Added a Poedit-ready POT template, source references, editable PO catalogs,
  MO compilation utility, and translator documentation.
- Expanded unit, integration, metadata, update-security, stress, Unicode,
  collision, and cancellation testing.
- Expanded English and Polish help and project documentation.

## 1.0.0

- Initial release.
- Single-file, selection, and recursive folder conversion.
- Sixteen target formats and four quality presets.
- LAME and Windows Media Foundation MP3 encoders.
- Configurable output location, custom NVDA gestures, cancellation, and status.
- Localized interface catalogs for NVDA languages.
- Optional author support prompt during installation.
