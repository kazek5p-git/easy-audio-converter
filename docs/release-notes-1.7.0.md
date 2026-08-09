# Easy Audio Converter 1.7.0

This release improves conversion throughput, diagnostics, and shutdown
communication while preserving the add-on's safe output handling.

- Added a bounded, timestamp-aware probe cache for repeated technical and
  metadata reads.
- Added a safe fast path that skips preliminary probing when an ordinary encode
  does not need source information.
- Improved uneven batch scheduling with longest-processing-time-first ordering
  and work-weighted overall progress.
- Added stage timing to conversion results for probing, loudness analysis,
  encoding/output writing, and finalization.
- Kept automatic parallel conversion adaptive to sustained CPU and memory load.
- Added an accessible warning that closing or restarting NVDA interrupts the
  active conversion and that the Cancel button should be used instead.
- Added Polish translations and updated all Poedit-compatible catalogs.

The add-on continues to use CPU audio encoders. GPU acceleration is not used,
and the automatic worker limit avoids uncontrolled oversubscription while
explicit worker counts remain available.
