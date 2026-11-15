# Rozbudowa opcji kodeków — 15 listopada 2026

## Cel i plan

Rozbudowa ustawień zaawansowanych o kontrolę przepływności oraz dostępne
flagi strumienia. Zachowujemy dotychczasowe ustawienia przy wyborze trybu
domyślnego. Profile MP3 będą osobne dla LAME, GOGO i Media Foundation.

1. Zweryfikować pomoc dołączonych FFmpeg 8.1.2 i GOGO 3.13 oraz źródła.
2. Dodać wspólny opis możliwości, walidację i budowanie argumentów.
3. Rozbudować dostępny edytor ustawień i zapisywanie profili.
4. Sprawdzić rzeczywiste kodowanie, nagłówki, ograniczenia i polskie etykiety.
5. Zbudować lokalną paczkę testową; publikacja i instalacja wymagają osobnej zgody.

## Ustalenia przed implementacją

| Enkoder | Dostępne tryby | Minimum/maksimum | Copyright i original | CRC |
| --- | --- | --- | --- | --- |
| LAME w FFmpeg | CBR, ABR, VBR | brak w interfejsie FFmpeg | tak | brak przełącznika |
| GOGO 3.13 | CBR, ABR, VBR | `-vb min max`; VBR może zejść poniżej minimum podczas ciszy | brak opcji konsolowych | brak opcji konsolowej |
| MP3 Media Foundation (Fraunhofer) | CBR | brak | brak | brak przełącznika |
| Ogg Vorbis | VBR, zarządzana przepływność ABR | w trybie zarządzanym | brak flag binarnych | suma Ogg automatycznie |
| Opus | CBR, VBR, ograniczone VBR | brak dowolnych granic | brak flag binarnych | suma Ogg automatycznie |
| AAC i M4A (natywny AAC) | CBR według bitrate, VBR według jakości | brak | brak tych przełączników | brak przełącznika |
| AC-3 i E-AC-3 | CBR | brak | tak | automatycznie |
| MP2, WMA, AMR-NB/WB | bitrate docelowy | brak przełącznika VBR | brak w dołączonych enkoderach | brak przełącznika |
| FLAC, WavPack, ALAC, PCM | kompresja bezstratna albo PCM | nie dotyczy | brak tych przełączników | zależnie od formatu, bez regulacji |

CBR AAC oznacza tryb sterowania bitrate według dokumentacji FFmpeg, nie równe
rozmiary wszystkich ramek. Ograniczone VBR Opus nie oznacza konfigurowalnych
granic minimum i maksimum. Copyright/original to bity strumienia, nie tag
tekstowy ani mechanizm ochrony przed kopiowaniem. CRC wykrywa część błędów
danych; nie potwierdza autorstwa ani „prawdziwości” nagrania.

Źródła odczytane przez podłączoną przeglądarkę:

- https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1.2/libavcodec/libmp3lame.c
- https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1.2/libavcodec/libvorbisenc.c
- https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1.2/libavcodec/mfenc.c
- https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1.2/libavcodec/mpegaudioenc.c
- https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1.2/libavcodec/eac3enc.c
- https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1.2/doc/encoders.texi
- https://learn.microsoft.com/en-us/windows/win32/medfound/mp3-audio-encoder
- https://github.com/teragonaudio/gogo-no-coda/blob/master/main.c

Kod GOGO jest archiwalnym lustrem; o udostępnieniu funkcji decyduje również
próba dołączonego pliku wykonywalnego. Bieżąca dokumentacja FFmpeg opisuje też
nowsze funkcje AAC nieobecne w 8.1.2 — nie przenosimy ich do interfejsu.

## Wdrożenie w kodzie

- `codec_options.py`: wspólne możliwości i walidacja, rozłączne argumenty
  CBR/ABR/VBR/CVBR, flagi strumienia i klucze profili MP3.
- `converter.py`, `gogo.py`: zastosowanie nowych opcji w rzeczywistych zadaniach,
  rozdzielenie jakości algorytmu i jakości VBR, sprawdzanie konfliktów ręcznych
  argumentów GOGO i szacowanie rozmiaru bez traktowania VBR jak CBR.
- `profiles.py`, `__init__.py`: odczyt dawnych profili, osobne klucze
  `mp3:lame`, `mp3:gogo`, `mp3:fraunhofer`, zachowanie opcji przy zapisie,
  eksporcie i imporcie. Dawny wspólny profil MP3 nadal działa dla LAME/MF,
  ale nie jest przenoszony na GOGO, które wcześniej go ignorowało.
- `settings_dialogs.py`: wspólny edytor w zakładce zaawansowanej i w oknie
  przygotowania konwersji; kontrolki zależne od enkodera, walidacja wszystkich
  profili przed zapisem dowolnej zakładki i brak zapisu po anulowaniu dialogu.
- `tools/generate_locales.py`, katalogi PO/MO i szablon POT: pełne nowe
  polskie etykiety i pomoc. Nowe komunikaty w pozostałych językach mają
  angielski tekst zastępczy; dotychczasowych tłumaczeń nie nadpisywano.
- Instrukcja polska, standardy kodu, kontrola zawartości pakietu i testy.
  Lokalny numer paczki zmieniono na 1.10.0; nie jest to publikacja.

Tryb domyślny zachowuje wcześniejsze zachowanie. Dla LAME i GOGO domyślna
jakość VBR wynosi 2; dla AAC także 2, z regulacją 0,1–5. Vorbis zachowuje
dotychczasową jakość presetu (lub dawny poziom kodeka), a jawny wybór jakości
VBR ma pierwszeństwo. Cel ABR Vorbis z wartością 0 pochodzi z presetu:
96, 128, 192 albo 320 kb/s. Opus zawsze zachowuje docelowy bitrate.

Badanie ramek ujawniło różnicę między ogólną dokumentacją Microsoftu
a zachowaniem dołączonej ścieżki FFmpeg/Windows: przy 44,1 kHz i stereo
żądanie 32–80 kb/s może dać 96 kb/s bez błędu procesu; żądanie 144 daje 160.
Przy 22,05 kHz żądanie 128 kb/s dało 80 kb/s. Kod `mfenc.c` wybiera najlepszy
dostępny typ wyjściowy zamiast gwarantować identyczny bitrate.
Jawny tryb CBR Fraunhofera sprawdza więc wynik przed uznaniem sukcesu i przed
usunięciem źródła. Niezgodny plik wynikowy jest usuwany, źródło pozostaje,
a komunikat podaje wybraną i uzyskaną przepływność oraz sugeruje zmianę
parametrów lub LAME. Nie ograniczono wszystkich komputerów do tabeli typów
z jednego systemu Windows. Ten test oznacza dodatkowy odczyt właściwości
wyniku tylko dla nowego, jawnie wybranego CBR Fraunhofera.

## Weryfikacja

Środowisko: Windows, Python 3.14, dołączone FFmpeg 8.1.2 i GOGO 3.13.
Próby korzystają wyłącznie z syntetycznych nagrań; plików użytkownika nie używano.
`TEMP` i `TMP` wskazują katalog próby w projekcie, a Python działa z `-B`.

- `python -B -X utf8 -m unittest discover -s tests`: 131 testów poprawnych.
  Obejmują mapowanie opcji, złe zakresy i typy, zgodność starych profili,
  eksport/import, izolację enkoderów MP3, stany kontrolek, błędy walidacji,
  brak częściowego zapisu, izolację walidacji kodeka od szablonu nazwy,
  zachowanie źródła przy niezgodnym CBR, nazwę dostępności pola liczbowego
  i pełny handler zapisu nazwanego profilu.
- `python -B -X utf8 tools/validate_rate_control.py`: rzeczywiste kodowanie,
  odczyt ramek MP3 i flag w nagłówkach MP3/AC-3/E-AC-3, dekodowanie wyników,
  porównanie wielkości pakietów Opus, nagłówki bitrate Vorbis, granice GOGO
  pojedynczo i łącznie, jakość AAC 0,1 i 5 oraz pełna ścieżka silnika.
  Wynik: 70 prób zgodnych z oczekiwaniami, w tym kontrolowane odrzucenie
  niezgodnego CBR Media Foundation z zachowaniem źródła.
- `python -B -X utf8 tools/validate_codecs.py`: 17 ścieżek enkoderów,
  22 poziomy kompresji bezstratnej, 4 próby kopiowania/remuksowania oraz
  metadane, układ folderów i wcześniejsze opcje zaawansowane — poprawne.
- `python -B -X utf8 tools/stress_test.py --files 250`: 250 plików,
  poprawne anulowanie i usunięcie niepełnego wyniku; ponowna próba 8,58 s,
  szczyt pamięci śledzonej przez Python 5,8 MB (nie jest to pomiar całego procesu).
- `python -B -X utf8 tools/poedit_catalog.py validate`: 75 katalogów poprawnych.
- `python -B -X utf8 -m tabnanny src tools tests`: bez błędów.
- `git diff --check`: bez błędów; jedynie informacja Git o konwersji LF/CRLF POT.
- `python -B -X utf8 tools/build_addon.py`: zbudowano i sprawdzono ZIP.
  Dodatkowo porównano wszystkie moduły paczki ze źródłami, odczytano polskie
  etykiety z zapakowanego MO, sprawdzono wersję i brak plików PYC. Kopia pod
  stałą nazwą jest identyczna bajtowo. Składnię wszystkich plików Python
  w `src`, `tools` i `tests` dodatkowo sprawdzono parserem AST.

W trakcie prac poprawiono błędne założenie o respektowaniu każdego CBR przez
Media Foundation, przesłanianie funkcji tłumaczącej przez lokalną zmienną
w obsłudze błędu walidacji oraz test zapisu ustawień wymagający uwzględnienia
nowej walidacji. Po poprawkach testy powtórzono.

## Kontrola okien przed wydaniem

Na polecenie użytkownika wykonano aktywną próbę rzeczywistych okien wxPython
4.2.5 / wxWidgets 3.2.9 w osobnym procesie. Użyto źródeł `guiHelper` i metody
budowania panelu z NVDA 2025.3.3; konfiguracja i pozostałe usługi NVDA były
odizolowanymi modelami w pamięci. Nie instalowano dodatku, nie restartowano
NVDA i nie zmieniano profili użytkownika. To nie jest potwierdzenie integracji
nowej paczki z działającym procesem NVDA ani odsłuchu jego syntezatora.

Próba uruchomienia skryptu wewnątrz NVDA nie została potwierdzona. Windows
odrzucił bezpośrednie wysyłanie komunikatów do konsoli, a próby zwykłej obsługi
konsoli nie utworzyły raportu. Nie zmieniano zabezpieczeń; zastosowano osobny
proces testowy. Nazwy, wartości i role aktywnych kontrolek odczytywano przez
MSAA, bez przechwytywania tekstu użytkownika. Nawigację Tab sprawdzono przez
zdarzenie nawigacji wx, nie przez wysyłanie klawiszy do innych aplikacji.

`tools/validate_wx_layout.py --nvda-source <źródła NVDA>` sprawdza niewidoczne
okna przy obszarze roboczym 1366×728 oraz po zmniejszeniu do 660×500.
Opcja `--interactive` uruchamia wspólny scenariusz
`tools/validate_nvda_codec_dialogs.py`: przełączanie kodeków i trybów, nazwy
pól VBR i granic, flagi, wartości ułamkowe AAC, osobne profile MP3,
OK/Anuluj, ponowne otwarcie, jednorazowy edytor oraz zapis nazwanego profilu.
Walidacja błędnych granic korzysta w tym środowisku z prawdziwego okna
`wx.GenericMessageDialog`. Raport:
[test-results/nvda-codec-dialogs.json](test-results/nvda-codec-dialogs.json).
Końcowy przebieg zakończył się stanem `completed`: 47 sprawdzeń poprawnych,
bez błędów; obejmuje także nazwy trzech pól głośności LUFS, dBTP i LU.

Wykryto i naprawiono cztery problemy:

- formularz konwersji ściskał przycisk do wysokości 0 przy małym ekranie;
  zawartość jest teraz przewijana, a przyciski pozostają poza nią;
- wyszukiwanie przycisku OK bez rodzica mogło zmieniać przycisk innego okna;
  wyszukiwanie jest ograniczone do własnego dialogu;
- wewnętrzne pole tekstowe `SpinCtrlDouble` nie miało nazwy MSAA;
  jawna nazwa obejmuje teraz także to pole, a referencje do jego obiektu
  dostępności i obudowy Python są zachowywane przez czas życia kontrolki;
- zapis nazwanego profilu kończył się `NameError` z powodu brakującego
  importu `NamedConversionProfile`; import przywrócono i dodano regresję.

W trakcie przygotowania próby poprawiono także błędy samego narzędzia:
nazwę modułu walidacji, odczyt faktycznego uchwytu edycji w polu liczbowym,
oczekiwaną polską etykietę przycisku i obsługę modalności okna komunikatu.
Nie zaliczano tych nieudanych przebiegów jako udanych testów dodatku.

## Stan i powrót do poprzedniej wersji

Kod przygotowany i zweryfikowany lokalnie; paczka wydania:
`dist/easyAudioConverter-1.10.0.nvda-addon`.
Stała kopia: `dist/easyAudioConverter.nvda-addon`.
Rozmiar: 41 148 379 bajtów. SHA-256 obu paczek:
`8b17e61fdc3ad87aa522f2cf48a3a3ce467a0ed76ee0920c37926d9f231b95e9`.
Punkt przywrócenia kodu: commit `6105ada`; przed zadaniem drzewo było czyste.
Użytkownik zlecił zatwierdzenie i publikację jako aktualizacji. Wydanie ma
oznaczenie `v1.10.0`; opis znajduje się w `release-notes-1.10.0.md`.
Opublikowano 15 listopada 2026 z commita `3543bc2` jako wydanie stabilne
i najnowsze, z obydwoma plikami `.nvda-addon`. Metadane GitHub potwierdziły
rozmiar i zgodne sumy SHA-256 obu plików przed publikacją.
Po publikacji niezmieniony kod aktualizatora z wersji 1.9.2 pobrał metadane
1.10.0 i rozpoznał je jako nowsze wydanie. Pobranie strumieniowe pod stałym
adresem `releases/latest/download/easyAudioConverter.nvda-addon` zwróciło
41 148 379 bajtów i zgodną sumę SHA-256; nie tworzono dodatkowej kopii na dysku.
Działająca instalacja NVDA pozostała niezmieniona. Powrót po ewentualnej
instalacji polega na użyciu zachowanej paczki 1.9.2. Nowe opcje i osobne
profile MP3 nie będą w niej obsługiwane; warto zachować eksport profili.

Dane dźwiękowe prób zostały usunięte przez zakończone testy. Jednorazowe
skrypty aktualizacji katalogów i pomiaru Media Foundation usunięto po zapisaniu
wyników powyżej; utrzymywalny test pozostaje w `tools/validate_rate_control.py`.
