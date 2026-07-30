# Easy Audio Converter 1.3.1

This maintenance release resolves issues affecting essential add-on
interaction.

- NVDA now shuts down and restarts correctly. The add-on's root menu item and
  submenu are destroyed in a single operation, eliminating a double free and
  the resulting `0xc0000374` heap-corruption crash.
- Conversion commands recover the selection from the Explorer window that was
  active before the NVDA menu opened.
- If no selection can be recovered, a standard Windows multiple-file dialog
  opens instead of the ambiguous “unknown” announcement.
- File, folder, and destination selectors no longer block the input script.
  NVDA announces their titles and focused controls, and its watchdog does not
  report a frozen main thread.
- Separate file and folder selection commands are available from the Tools
  menu and NVDA Input Gestures.

Conversion, job queue, settings, and format features introduced in version
1.3.0 remain unchanged.
