# Standardy kodu

Ten dokument opisuje konwencje stosowane w źródłach dodatku Easy Audio Converter.

## Autorstwo i licencja

Pliki źródłowe dodatku zawierają nagłówek praw autorskich autora:

`Copyright (C) 2026 Kazimierz Parzych`

Kod jest udostępniany na licencji GPL-3.0-or-later, zgodnie z plikiem
`LICENSE.txt` i manifestem dodatku.

## Nazwy

- funkcje i metody pomocnicze używają `snake_case`;
- klasy używają `PascalCase`;
- stałe modułowe używają `UPPER_SNAKE_CASE`;
- pojedyncze podkreślenie na początku nazwy oznacza element prywatny, przeznaczony
  do użytku wewnątrz modułu;
- nazwy metod skryptów NVDA zachowują wymagany przez API NVDA zapis, na przykład
  `script_convertSelection`, ponieważ NVDA rozpoznaje te metody jako punkty
  wejścia skryptów.
- nazwy metod wymaganych przez API NVDA i wxPython, takich jak `makeSettings`,
  `onSave`, `isValid` i `GetChildCount`, pozostają zgodne z tymi API.

Podkreślenie w nazwie nie oznacza automatycznie błędu stylistycznego. Stosuje
się je do odróżnienia publicznego interfejsu dodatku od szczegółów implementacji.
Nowe funkcje, które nie są skryptami NVDA, powinny jednak konsekwentnie używać
zapisu `snake_case`.

## Podział odpowiedzialności

- `__init__.py` zawiera wspólną konfigurację, stałe i funkcje integrujące pakiet;
  eksportuje też publiczne elementy dla zachowania zgodności z wcześniejszym
  importem dodatku;
- `plugin.py` zawiera klasę `GlobalPlugin`, skrypty NVDA, kolejkę i cykl życia
  zadań;
- `settings_dialogs.py` zawiera strony ustawień oraz dialogi profili i opcji;
- `conversion_dialogs.py` zawiera okna planu, postępu, wyników i informacji;
- `converter.py` pozostaje niezależnym od NVDA silnikiem FFmpeg;
- `profiles.py` obsługuje bezpieczny zapis profili;
- `updater.py` obsługuje sprawdzanie, pobieranie i weryfikację aktualizacji.

Moduły interfejsu mogą korzystać ze wspólnych stałych i funkcji z pakietu, ale
nie powinny importować klasy `GlobalPlugin`. Dzięki temu logika konwersji i
okna interfejsu można testować bez uruchamiania pełnego cyklu życia NVDA.

## Zmiany utrzymaniowe

Przy refaktoryzacji należy zachować publiczne nazwy skryptów, ustawienia NVDA,
format profili oraz działanie istniejących skrótów. Zmiany organizacyjne powinny
być sprawdzane testami jednostkowymi i importem dodatku z udokumentowanym
minimalnym API NVDA.
