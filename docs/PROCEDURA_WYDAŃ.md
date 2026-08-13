# Procedura wydań

## Stały adres pobierania

Każde wydanie dodatku musi zawierać dwa pliki pakietu:

- plik wersjonowany, na przykład `easyAudioConverter-1.8.2.nvda-addon`;
- plik o stałej nazwie `easyAudioConverter.nvda-addon`.

Stały plik umożliwia używanie niezmiennego adresu na stronach projektu:

`https://github.com/kazek5p-git/easy-audio-converter/releases/latest/download/easyAudioConverter.nvda-addon`

Polecenie `python tools/build_addon.py` tworzy oba pliki w katalogu `dist`.
Przy publikowaniu wydania należy dołączyć do niego także plik o stałej nazwie.

Ta sama zasada obowiązuje przy publikowaniu pozostałych aplikacji i dodatków:
asset przeznaczony do stałego linku nie może zawierać numeru wersji w nazwie.
