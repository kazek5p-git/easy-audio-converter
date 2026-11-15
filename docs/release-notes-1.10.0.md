# Easy Audio Converter 1.10.0

This release adds encoder-specific bitrate controls and a shared advanced codec
editor, available both in settings and before an individual conversion.

- Choose CBR, ABR or VBR for LAME and GOGO, with separate profiles for each MP3
  encoder. GOGO also supports minimum and maximum bitrate limits in VBR and ABR.
- Configure Vorbis VBR or managed ABR with optional limits, Opus CBR/VBR/CVBR,
  and AAC/M4A bitrate-based or quality-based encoding.
- Set copyright and original stream flags where the bundled encoder supports
  them: LAME, AC-3 and E-AC-3.
- Save the new options in named profiles, including JSON import and export.
  Existing profiles and default encoding behavior remain compatible.
- Validate unsupported modes, inconsistent limits and conflicting GOGO
  arguments before starting a conversion or saving settings.
- Verify the actual output bitrate when explicit CBR is selected for Media
  Foundation MP3. If Windows chooses a different bitrate, the conversion reports
  the mismatch and preserves the source file.
- Keep the Convert and Cancel buttons visible on smaller screens by scrolling
  the options form. Button lookup is scoped to its own window, preventing an
  unrelated dialog's OK button from being changed.
- Expose explicit accessible names for decimal edit fields, including VBR
  quality and custom loudness targets.
- Fix an exception that could prevent saving a named conversion profile.

The editor only offers controls supported by the bundled encoder interfaces.
Media Foundation MP3 supports CBR only. FFmpeg's LAME interface does not expose
VBR bitrate limits or a CRC switch. GOGO VBR may use a bitrate below the selected
minimum for silence. Copyright and original flags are header bits, not metadata
tags or copy protection.

Author: Kazimierz Parzych.

The versioned package and `easyAudioConverter.nvda-addon` contain the same add-on.
The permanent download link remains:
https://github.com/kazek5p-git/easy-audio-converter/releases/latest/download/easyAudioConverter.nvda-addon
