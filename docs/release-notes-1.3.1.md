# Easy Audio Converter 1.3.1

To wydanie naprawia usterki wpływające na podstawową obsługę dodatku.

- NVDA zamyka się i uruchamia ponownie prawidłowo. Element podmenu dodatku jest
  usuwany razem ze swoim podmenu w jednej operacji, co eliminuje podwójne
  zwolnienie pamięci i awarię `0xc0000374`.
- Polecenia konwersji odzyskują zaznaczenie z okna Eksploratora aktywnego przed
  otwarciem menu NVDA.
- Jeśli nie ma zaznaczenia, otwiera się standardowe okno Windows do wyboru
  wielu plików zamiast niejasnego komunikatu „nieznane”.
- Okna wyboru plików, folderu oraz folderu docelowego nie blokują już skryptu
  wejściowego. NVDA prawidłowo odczytuje tytuł i aktywną kontrolkę, a jego
  mechanizm nadzoru nie zgłasza zamrożenia.
- W menu Narzędzia i Zdarzeniach wejścia są dostępne osobne polecenia wyboru
  plików oraz folderu.

Konwersja, kolejka zadań, ustawienia i formaty wprowadzone w wersji 1.3.0
pozostają bez zmian.
