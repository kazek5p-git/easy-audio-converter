# Translating Easy Audio Converter with Poedit

The add-on uses the standard GNU gettext layout expected by NVDA and Poedit:

```text
src/
  locale/
    EasyAudioConverter.pot
    pl/
      manifest.ini
      LC_MESSAGES/
        nvda.po
        nvda.mo
```

## Create a new translation

1. Open `src/locale/EasyAudioConverter.pot` in Poedit.
2. Choose **Create new translation** and select the NVDA language.
3. Save the file as
   `src/locale/<NVDA-language-code>/LC_MESSAGES/nvda.po`.
4. Keep every placeholder unchanged, including braces and spelling:
   `{count}`, `{name}`, `{version}`, `{done:.1f}`, and similar values.
5. Save in Poedit. Poedit can generate `nvda.mo` automatically.
6. Add `src/locale/<NVDA-language-code>/manifest.ini` with translated
   `summary` and `description` values.
7. Validate and compile all catalogs:

   ```powershell
   python tools/poedit_catalog.py validate
   python tools/poedit_catalog.py compile
   ```

## Update translations after source changes

Regenerate the POT template and merge its messages into every existing PO
catalog:

```powershell
python tools/poedit_catalog.py pot
python tools/poedit_catalog.py merge
```

The merge command preserves existing `msgstr` values, adds source references,
and leaves new messages empty for translators. Open the PO in Poedit, translate
the new entries, save, then compile and validate again.

## Catalog rules

- Files must be UTF-8.
- Do not translate format names such as MP3 unless the target language has an
  established localized form.
- Do not add, remove, or rename placeholders.
- Keep keyboard accelerators readable if an ampersand is present.
- Check long messages with a screen reader, not only visually.
- Human corrections in PO files are preserved by the normal Poedit workflow.
  `generate_locales.py` only fills messages that have no translation.

## Poedit project settings

The POT and generated PO headers already contain:

- base path `../..` in the POT and `../../../..` in each PO, both pointing
  to the project root;
- source search path `src`;
- gettext keyword `_`;
- UTF-8 encoding.

No private service, token, or network access is required to edit or compile a
translation.
