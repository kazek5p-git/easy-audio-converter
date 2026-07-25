# Changelog

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
