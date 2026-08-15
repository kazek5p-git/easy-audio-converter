# Easy Audio Converter 1.9.1

This maintenance release fixes add-on cleanup during NVDA restart and reload.

- Fixed an `UnboundLocalError` when the add-on was terminated without an active
  independent conversion job.
- Fixed cleanup of all independent job queues during termination.
- Kept the built-in update mechanism unchanged.

The release is intended to replace version 1.9.0 in the NV Access Add-on Store
submission.
