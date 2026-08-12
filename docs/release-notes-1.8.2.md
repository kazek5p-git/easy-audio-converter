# Easy Audio Converter 1.8.2

This maintenance release improves the add-on's code organization while keeping
the existing conversion workflow and public NVDA commands compatible.

- Split the NVDA integration, settings dialogs, and conversion dialogs into
  focused modules that are easier to review and maintain.
- Kept the existing public scripts and compatibility exports, including the
  conversion queue, independent conversion windows, profiles, and updater.
- Added explicit GPL-3.0-or-later copyright and SPDX headers naming Kazimierz
  Parzych in the add-on's Python source files.
- Documented module responsibilities and coding standards for contributors.
- Updated the packaged version and translation catalog headers to 1.8.2.

All automated tests pass, and the add-on package was built and checked locally.
