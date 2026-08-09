# Easy Audio Converter 1.6.0

This release improves conversion throughput on multi-core systems while
keeping the conversion workflow responsive and safe.

- Independent files can now be converted in parallel by bounded FFmpeg
  workers. The default automatically selects a suitable worker count from the
  available CPU cores, and the setting can be overridden with 1, 2, 4, 8, 16,
  or 32 workers.
- FFmpeg is explicitly allowed to select the optimal number of codec and
  filter threads for each process with `-threads 0`.
- Cancellation now propagates to every active FFmpeg process. A request to
  stop after the current file prevents additional files from being scheduled.
- GPU acceleration is not enabled because the add-on's supported encoders are
  audio encoders that run on the CPU; the new worker setting uses the CPU more
  effectively for independent files.
- Added Polish and catalog updates for the new processing options, together
  with expanded unit, codec, stress, and cancellation coverage.

The package remains compatible with the existing profiles and settings. The
new parallel-worker option defaults to automatic mode.
