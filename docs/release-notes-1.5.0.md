# Easy Audio Converter 1.5.0

This release adds an optional, profile-aware source replacement mode with
multiple safeguards against accidental data loss.

- A new “Replace source files after successful conversion” option is
  available in the standard settings and in the one-time conversion dialog.
- The option is stored in custom conversion profiles and is disabled by
  default for existing and new configurations.
- Every destructive job requires a separate irreversible-action warning. The
  warning defaults to No and is shown before a job starts or enters the queue.
- A source is permanently deleted only after FFmpeg succeeds, creates a
  nonempty output, optional deep verification passes, and requested source
  dates have been copied.
- Conversion errors, failed verification, date-preservation errors, and
  cancellation always keep the source file.
- If a completed output is valid but the source cannot be removed, the output
  is retained and its exact path is shown in the results window and report.
  This case is excluded from failed-file retry to avoid duplicate outputs.
- The conversion plan explicitly warns when source replacement is enabled.

Existing output files remain protected by collision-free naming, and no
result is ever written directly over its source.
