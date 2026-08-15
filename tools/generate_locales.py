"""Generate gettext catalogs for the language set shipped by NVDA.

English source strings are translated in compact batches through the public
Google Translate endpoint. Placeholders are protected, and a curated Polish
catalog overrides machine output. Generated PO and MO files are committed so
building the add-on itself never requires network access.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
	from .poedit_catalog import extract_messages as extract_message_references
	from .poedit_catalog import parse_po
except ImportError:
	from poedit_catalog import extract_messages as extract_message_references
	from poedit_catalog import parse_po


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
LOCALE_ROOT = SOURCE_ROOT / "locale"

NVDA_LOCALES = (
	"af",
	"af_ZA",
	"am",
	"an",
	"ar",
	"as",
	"be",
	"bg",
	"bn",
	"bs",
	"ca",
	"ckb",
	"cs",
	"da",
	"de",
	"de_CH",
	"el",
	"es",
	"es_CO",
	"fa",
	"fi",
	"fr",
	"ga",
	"gl",
	"gu",
	"he",
	"hi",
	"hr",
	"hu",
	"id",
	"is",
	"it",
	"ja",
	"ka",
	"km",
	"kmr",
	"kn",
	"ko",
	"kok",
	"ky",
	"lb",
	"lt",
	"mk",
	"ml",
	"mn",
	"mni",
	"my",
	"nb",
	"nb_NO",
	"ne",
	"nl",
	"nn_NO",
	"pa",
	"pl",
	"pt",
	"pt_BR",
	"pt_PT",
	"ro",
	"ru",
	"sk",
	"sl",
	"so",
	"sq",
	"sr",
	"sv",
	"ta",
	"te",
	"th",
	"tr",
	"uk",
	"ur",
	"vi",
	"zh_CN",
	"zh_HK",
	"zh_TW",
)

TRANSLATE_TARGETS = {
	"af_ZA": "af",
	"de_CH": "de",
	"es_CO": "es",
	"kmr": "ku",
	"kok": "gom",
	"mni": "mni-Mtei",
	"nb": "no",
	"nb_NO": "no",
	"nn_NO": "no",
	"pt_BR": "pt",
	"pt_PT": "pt",
	"zh_CN": "zh-CN",
	"zh_HK": "zh-TW",
	"zh_TW": "zh-TW",
}

EDGE_TARGETS = {
	"af_ZA": "af",
	"an": "es",
	"ckb": "ku",
	"de_CH": "de",
	"es_CO": "es",
	"kmr": "ku",
	"kok": "gom",
	"mni": "mni",
	"nb": "nb",
	"nb_NO": "nb",
	"nn_NO": "nb",
	"pt_BR": "pt",
	"pt_PT": "pt",
	"sr": "sr-Cyrl",
	"zh_CN": "zh-Hans",
	"zh_HK": "zh-Hant",
	"zh_TW": "zh-Hant",
}

MANIFEST_SUMMARY = "Easy Audio Converter"
MANIFEST_DESCRIPTION = (
	"Accessible queued and independent-window audio conversion plus "
	"no-re-encoding stream extraction and remuxing with planning, filename "
	"templates, loudness normalization, verification, profiles, optional bundled "
	"GOGO WAV-to-MP3 encoding, and bundled FFmpeg."
)

POLISH = {
	"...and {count} more errors": "...oraz {count} dalszych błędów",
	"A conversion is already in progress": "Konwersja jest już w toku",
	"AAC": "AAC",
	"AC-3": "AC-3",
	"AIFF": "AIFF",
	"ALAC (Apple Lossless)": "ALAC (Apple Lossless)",
	"AMR narrowband": "AMR wąskopasmowy",
	"AMR wideband": "AMR szerokopasmowy",
	"Browse...": "Przeglądaj...",
	"Cancel conversion": "Anuluj konwersję",
	"Cancel the current audio conversion": "Anuluj bieżącą konwersję audio",
	"Canceling the conversion": "Anulowanie konwersji",
	"Cannot open the support page. Open this address manually: {url}": (
		"Nie można otworzyć strony wsparcia. Otwórz ten adres ręcznie: {url}"
	),
	"Change the conversion quality": "Zmień jakość konwersji",
	"Change the target audio format": "Zmień docelowy format audio",
	"Choose a folder to convert": "Wybierz folder do konwersji",
	"Choose files to convert": "Wybierz pliki do konwersji",
	"Choose the destination folder": "Wybierz folder docelowy",
	"Confirm folder conversion": "Potwierdź konwersję folderu",
	"Conversion canceled. Completed {done} of {total} files.": (
		"Konwersja anulowana. Ukończono {done} z {total} plików."
	),
	"Conversion complete: {done} succeeded, {failed} failed.": (
		"Konwersja zakończona: ukończono {done}, błędy: {failed}."
	),
	"Conversion complete. Succeeded: {done}. Failed: {failed}. Skipped: {skipped}.": (
		"Konwersja zakończona. Ukończone: {done}. Błędy: {failed}. "
		"Pominięte: {skipped}."
	),
	"Convert all supported audio files in {folder}, {scope}?": (
		"Przekonwertować wszystkie obsługiwane pliki audio w folderze {folder}, {scope}?"
	),
	"Convert every supported audio file in the current folder": (
		"Konwertuj wszystkie obsługiwane pliki audio w bieżącym folderze"
	),
	"Convert selected files or folders": "Konwertuj zaznaczone pliki lub foldery",
	"Convert the current folder": "Konwertuj bieżący folder",
	"Converting {index} of {total}: {name}": "Konwertowanie {index} z {total}: {name}",
	"Destination folder:": "Folder docelowy:",
	"Destination folder: {folder}": "Folder docelowy: {folder}",
	"E-AC-3": "E-AC-3",
	"Easy Audio Converter": "Easy Audio Converter",
	"Economical": "Oszczędna",
	"FLAC": "FLAC",
	"Files to convert: {count}. Skipped: {skipped}.": (
		"Pliki do konwersji: {count}. Pominięte: {skipped}."
	),
	"Found {count} files to convert": "Znaleziono pliki do konwersji: {count}",
	"Fraunhofer / Windows Media Foundation MP3": "Fraunhofer / Windows Media Foundation MP3",
	"GOGO-no-coda MP3 (bundled WAV encoder)": "GOGO-no-coda MP3 (dołączony enkoder WAV)",
	"GOGO executable (gogo.exe):": "Plik wykonywalny GOGO (gogo.exe):",
	"Browse for GOGO executable...": "Przeglądaj w poszukiwaniu pliku GOGO...",
	"GOGO bitrate:": "Przepływność GOGO:",
	"GOGO quality:": "Jakość GOGO:",
	"Additional GOGO arguments:": "Dodatkowe argumenty GOGO:",
	"Show GOGO commands": "Pokaż polecenia GOGO",
	"GOGO commands": "Polecenia GOGO",
	"Define manually in GOGO arguments": "Zdefiniuj ręcznie w argumentach GOGO",
	"64 kb/s joint stereo": "64 kb/s, joint stereo",
	"128 kb/s joint stereo": "128 kb/s, joint stereo",
	"160 kb/s joint stereo": "160 kb/s, joint stereo",
	"192 kb/s joint stereo": "192 kb/s, joint stereo",
	"256 kb/s stereo": "256 kb/s, stereo",
	"320 kb/s stereo": "320 kb/s, stereo",
	"GOGO Q {value} — highest quality": "GOGO Q {value} — najwyższa jakość",
	"GOGO Q {value} — fastest at Q9": "GOGO Q {value} — najszybciej przy Q9",
	"GOGO Q {value}": "GOGO Q {value}",
	"Choose the GOGO executable": "Wybierz plik wykonywalny GOGO",
	"Choose the GOGO executable first.": "Najpierw wybierz plik wykonywalny GOGO.",
	"Could not read GOGO help:\n{error}": "Nie można odczytać pomocy GOGO:\n{error}",
	"The configured or bundled GOGO executable is missing. Choose another gogo.exe in Easy Audio Converter settings.": (
		"Brakuje skonfigurowanego lub dołączonego pliku GOGO. Wybierz inny plik gogo.exe w ustawieniach Easy Audio Converter."
	),
	"GOGO encodes WAV/WAVE files to MP3 without metadata or loudness processing. The add-on includes GOGO-no-coda; leave the executable field empty to use it, or choose another gogo.exe.": (
		"GOGO koduje pliki WAV/WAVE do MP3 bez metadanych i przetwarzania głośności. "
		"Dodatek zawiera GOGO-no-coda; pozostaw pole pliku wykonywalnego puste, aby go użyć, "
		"albo wybierz inny plik gogo.exe."
	),
	"GOGO processing: WAV/WAVE input only; metadata, loudness, artwork, and chapters are not written.": (
		"Przetwarzanie GOGO: tylko pliki WAV/WAVE; metadane, głośność, okładki i rozdziały nie są zapisywane."
	),
	"Advanced codec overrides are not used by GOGO": "GOGO nie używa zaawansowanych ustawień kodeka",
	"GOGO can encode only WAV/WAVE source files": "GOGO może kodować tylko pliki źródłowe WAV/WAVE",
	"The GOGO output path already exists; no file was overwritten.": (
		"Ścieżka wyniku GOGO już istnieje; żaden plik nie został nadpisany."
	),
	"High": "Wysoka",
	"If Easy Audio Converter is useful to you and you want to support my work, "
	"you can buy me a coffee.\n\nDo you want to open the support page now?": (
		"Jeśli Easy Audio Converter jest dla Ciebie przydatny i chcesz wesprzeć "
		"moją pracę, możesz postawić mi kawę.\n\n"
		"Czy chcesz teraz otworzyć stronę wsparcia?"
	),
	"Include subfolders when converting a folder": "Uwzględniaj podfoldery podczas konwersji folderu",
	"LAME MP3": "LAME MP3",
	"M4A (AAC)": "M4A (AAC)",
	"MP2": "MP2",
	"MP3": "MP3",
	"MP3 encoder:": "Kodek MP3:",
	"No conversion is in progress": "Nie trwa żadna konwersja",
	"No files or folders are selected": "Nie zaznaczono plików ani folderów",
	"No files need conversion. Skipped: {skipped}.": (
		"Żadne pliki nie wymagają konwersji. Pominięte: {skipped}."
	),
	"No supported audio files were found": "Nie znaleziono obsługiwanych plików audio",
	"Ogg Vorbis": "Ogg Vorbis",
	"Open Easy Audio Converter settings": "Otwórz ustawienia Easy Audio Converter",
	"Open the author's support page": "Otwórz stronę wsparcia autora",
	"Opening the support page": "Otwieranie strony wsparcia",
	"Opus": "Opus",
	"Preparing the conversion": "Przygotowywanie konwersji",
	"Preserve the source folder structure in the destination": (
		"Zachowuj strukturę folderów źródłowych w folderze docelowym"
	),
	"Preserve source file creation and modification dates": (
		"Zachowuj daty utworzenia i modyfikacji plików źródłowych"
	),
	"The source file dates could not be preserved.": (
		"Nie udało się zachować dat pliku źródłowego."
	),
	"Quality:": "Jakość:",
	"Quality: {quality}": "Jakość: {quality}",
	"Quickly choose the destination folder": "Szybko wybierz folder docelowy",
	"Quickly convert selected files or folders": "Szybko konwertuj zaznaczone pliki lub foldery",
	"Report audio conversion status": "Odczytaj stan konwersji audio",
	"Report conversion status": "Odczytaj stan konwersji",
	"Timing:": "Czasy etapów:",
	"Total wall time: {value}": "Łączny czas rzeczywisty: {value}",
	"Input recognition: {value}": "Rozpoznawanie wejścia: {value}",
	"Loudness analysis: {value}": "Analiza głośności: {value}",
	"Encoding and output writing: {value}": "Kodowanie i zapis wyniku: {value}",
	"Verification and finalization: {value}": "Weryfikacja i finalizacja: {value}",
	"Probe cache hits: {count}; misses: {misses}": (
		"Trafienia pamięci podręcznej rozpoznania: {count}; chybienia: {misses}"
	),
	"When the plan is disabled, ordinary conversions use a fast path "
	"and skip the preliminary input scan when it is not needed.": (
		"Po wyłączeniu planu zwykłe konwersje używają szybkiej ścieżki i pomijają "
		"wstępne rozpoznanie wejścia, gdy nie jest ono potrzebne."
	),
	"Save converted files next to the source files": (
		"Zapisuj przekonwertowane pliki obok plików źródłowych"
	),
	"Settings...": "Ustawienia...",
	"Some files could not be converted:\n\n{details}": (
		"Nie udało się przekonwertować niektórych plików:\n\n{details}"
	),
	"Standard": "Standardowa",
	"Standard settings": "Ustawienia standardowe",
	"Support Easy Audio Converter": "Wesprzyj Easy Audio Converter",
	"Support the author": "Wesprzyj autora",
	"Target format:": "Format docelowy:",
	"Target format: {format}": "Format docelowy: {format}",
	"The bundled FFmpeg component is missing. Reinstall Easy Audio Converter.": (
		"Brakuje dołączonego składnika FFmpeg. Zainstaluj ponownie Easy Audio Converter."
	),
	"The conversion could not start:\n{error}": "Nie można rozpocząć konwersji:\n{error}",
	"Unknown error": "Nieznany błąd",
	"Very high": "Bardzo wysoka",
	"WAV": "WAV",
	"WMA": "WMA",
	"WavPack": "WavPack",
	"excluding subfolders": "bez podfolderów",
	"including subfolders": "wraz z podfolderami",
	"{count} selected folders": "zaznaczone foldery: {count}",
	"16 bit": "16 bitów",
	"24 bit": "24 bity",
	"32 bit": "32 bity",
	"Advanced codec settings...": "Zaawansowane ustawienia kodeków...",
	"Advanced settings": "Ustawienia zaawansowane",
	"Album": "Album",
	"Album artist": "Wykonawca albumu",
	"An update check is already in progress": "Sprawdzanie aktualizacji już trwa",
	"An update download is already in progress": "Pobieranie aktualizacji już trwa",
	"Artist": "Wykonawca",
	"Automatically check for add-on updates": "Automatycznie sprawdzaj aktualizacje dodatku",
	"Bitrate in kbps (0 uses the quality preset):": (
		"Przepływność w kb/s (0 używa ustawienia jakości):"
	),
	"Canceling...": "Anulowanie...",
	"Channels:": "Kanały:",
	"Check for Easy Audio Converter updates": "Sprawdź aktualizacje Easy Audio Converter",
	"Check for updates...": "Sprawdź aktualizacje...",
	"Checking for Easy Audio Converter updates": "Sprawdzanie aktualizacji Easy Audio Converter",
	"Close": "Zamknij",
	"Codec profile to edit:": "Profil kodeka do edycji:",
	"Codec-specific level (-1 uses the preset):": (
		"Poziom właściwy dla kodeka (-1 używa ustawienia jakości):"
	),
	"Comment": "Komentarz",
	"Composer": "Kompozytor",
	"Converting {index} of {total}: {name}. "
	"Current file time {processed}; elapsed {elapsed}.": (
		"Konwertowanie {index} z {total}: {name}. "
		"Czas bieżącego pliku {processed}; czas od rozpoczęcia {elapsed}."
	),
	"Converting {index} of {total}: {name}. "
	"Current file {filePercent}%, overall {overallPercent}%, elapsed {elapsed}.": (
		"Konwertowanie {index} z {total}: {name}. "
		"Bieżący plik {filePercent}%, łącznie {overallPercent}%, "
		"czas od rozpoczęcia {elapsed}."
	),
	"Copy all text metadata": "Kopiuj wszystkie metadane tekstowe",
	"Copy selected metadata fields": "Kopiuj wybrane pola metadanych",
	"Copyright": "Prawa autorskie",
	"Could not check for updates.\n\n{error}": (
		"Nie udało się sprawdzić aktualizacji.\n\n{error}"
	),
	"Could not open the NVDA add-on installer. The update was saved to:\n{path}": (
		"Nie udało się otworzyć instalatora dodatków NVDA. Aktualizację zapisano w:\n{path}"
	),
	"Current file progress: 100%": "Postęp bieżącego pliku: 100%",
	"Current file progress: waiting": "Postęp bieżącego pliku: oczekiwanie",
	"Current file progress: {percent}% ({processed} of {duration})": (
		"Postęp bieżącego pliku: {percent}% ({processed} z {duration})"
	),
	"Current file time: {processed}": "Czas bieżącego pliku: {processed}",
	"Date or year": "Data lub rok",
	"Disc number": "Numer płyty",
	"Do not copy metadata": "Nie kopiuj metadanych",
	"Download and install": "Pobierz i zainstaluj",
	"Downloaded {done:.1f} MB": "Pobrano {done:.1f} MB",
	"Downloaded {done:.1f} of {total:.1f} MB": (
		"Pobrano {done:.1f} z {total:.1f} MB"
	),
	"Downloading Easy Audio Converter update": "Pobieranie aktualizacji Easy Audio Converter",
	"Easy Audio Converter - Advanced": "Easy Audio Converter — zaawansowane",
	"Easy Audio Converter is up to date. Installed version: {version}.": (
		"Easy Audio Converter jest aktualny. Zainstalowana wersja: {version}."
	),
	"Easy Audio Converter update": "Aktualizacja Easy Audio Converter",
	"Easy Audio Converter update available": "Dostępna aktualizacja Easy Audio Converter",
	"Easy Audio Converter {newVersion} is available. "
	"You have version {currentVersion}.\n\n"
	"Do you want to download and install the update now?": (
		"Dostępna jest wersja {newVersion} dodatku Easy Audio Converter. "
		"Masz wersję {currentVersion}.\n\n"
		"Czy chcesz teraz pobrać i zainstalować aktualizację?"
	),
	"Easy Audio Converter {version} is available, but the release "
	"does not contain a direct add-on package. Open the release page?": (
		"Dostępna jest wersja {version} dodatku Easy Audio Converter, ale wydanie "
		"nie zawiera bezpośredniego pakietu dodatku. Otworzyć stronę wydania?"
	),
	"Elapsed time: 0:00": "Czas od rozpoczęcia: 0:00",
	"Elapsed time: {elapsed}": "Czas od rozpoczęcia: {elapsed}",
	"Enable advanced overrides for this codec": (
		"Włącz zaawansowane ustawienia dla tego kodeka"
	),
	"File {index} of {total}: {name}": "Plik {index} z {total}: {name}",
	"All FLAC levels are lossless. Level 0 is fastest; level 12 gives "
	"the strongest compression but is very slow.": (
		"Wszystkie poziomy FLAC są bezstratne. Poziom 0 jest najszybszy; "
		"poziom 12 zapewnia najsilniejszą kompresję, ale jest bardzo wolny."
	),
	"FLAC 0 — fastest encoding": "FLAC 0 — najszybsze kodowanie",
	"FLAC 12 — maximum compression, very slow": (
		"FLAC 12 — maksymalna kompresja, bardzo wolna"
	),
	"FLAC {level}": "FLAC {level}",
	"Fast, -f (FFmpeg level 0)": "Szybki, -f (poziom FFmpeg 0)",
	"For LAME MP3, level 0 is the slowest and highest algorithm quality; 9 is fastest.": (
		"Dla LAME MP3 poziom 0 jest najwolniejszy i daje najwyższą jakość algorytmu; "
		"poziom 9 jest najszybszy."
	),
	"For Ogg Vorbis, levels 0 to 10 select increasing variable-bitrate quality.": (
		"Dla Ogg Vorbis poziomy od 0 do 10 wybierają rosnącą jakość zmiennej przepływności."
	),
	"For Opus, levels 0 to 10 select increasing encoder complexity.": (
		"Dla Opus poziomy od 0 do 10 wybierają rosnącą złożoność kodera."
	),
	"Genre": "Gatunek",
	"High, -h (FFmpeg level 2)": "Wysoki, -h (poziom FFmpeg 2)",
	"Hide": "Ukryj",
	"Keep the source channel count": "Zachowaj liczbę kanałów źródła",
	"Keep the source sample rate": "Zachowaj częstotliwość próbkowania źródła",
	"Language": "Język",
	"Later": "Później",
	"Lyrics": "Tekst utworu",
	"Lossless compression profile:": "Profil kompresji bezstratnej:",
	"Maximum, -hhx6 (FFmpeg level 8)": "Maksymalny, -hhx6 (poziom FFmpeg 8)",
	"Metadata export:": "Eksport metadanych:",
	"Metadata fields to copy:": "Pola metadanych do skopiowania:",
	"Mono": "Mono",
	"Normal (FFmpeg level 1)": "Normalny (poziom FFmpeg 1)",
	"No conversion progress is available": "Brak dostępnych informacji o postępie konwersji",
	"Not used by this codec": "Nieużywane przez ten kodek",
	"Open advanced codec settings": "Otwórz zaawansowane ustawienia kodeków",
	"Overall progress: 100%": "Postęp całkowity: 100%",
	"Overall progress: waiting": "Postęp całkowity: oczekiwanie",
	"Overall progress: {percent}%": "Postęp całkowity: {percent}%",
	"PCM bit depth:": "Głębia bitowa PCM:",
	"Publisher": "Wydawca",
	"Release notes:": "Informacje o wydaniu:",
	"Sample rate:": "Częstotliwość próbkowania:",
	"Show conversion progress": "Pokaż postęp konwersji",
	"Show the audio conversion progress window": "Pokaż okno postępu konwersji audio",
	"Starting the download...": "Rozpoczynanie pobierania...",
	"Stereo": "Stereo",
	"The codec-specific level is not used by this format.": (
		"Ten format nie używa poziomu właściwego dla kodeka."
	),
	"The conversion could not start": "Nie można rozpocząć konwersji",
	"The update could not be downloaded or verified.\n\n{error}": (
		"Nie udało się pobrać lub zweryfikować aktualizacji.\n\n{error}"
	),
	"The update is ready. Opening the NVDA add-on installer.": (
		"Aktualizacja jest gotowa. Otwieranie instalatora dodatków NVDA."
	),
	"Title": "Tytuł",
	"Track number": "Numer utworu",
	"Update download canceled": "Pobieranie aktualizacji anulowane",
	"Use the quality preset": "Użyj ustawienia jakości",
	"Very high, -hh (FFmpeg level 3)": "Bardzo wysoki, -hh (poziom FFmpeg 3)",
	"Very high + extra 1, -hhx1 (FFmpeg level 4)": (
		"Bardzo wysoki + tryb dodatkowy 1, -hhx1 (poziom FFmpeg 4)"
	),
	"Very high + extra 2, -hhx2 (FFmpeg level 5)": (
		"Bardzo wysoki + tryb dodatkowy 2, -hhx2 (poziom FFmpeg 5)"
	),
	"Very high + extra 3, -hhx3 (FFmpeg level 6)": (
		"Bardzo wysoki + tryb dodatkowy 3, -hhx3 (poziom FFmpeg 6)"
	),
	"Very high + extra 4, -hhx4 (FFmpeg level 7)": (
		"Bardzo wysoki + tryb dodatkowy 4, -hhx4 (poziom FFmpeg 7)"
	),
	"WavPack profiles use FFmpeg levels 0 to 8. Level 8 corresponds "
	"to -hhx6 and is extremely slow.": (
		"Profile WavPack używają poziomów FFmpeg od 0 do 8. Poziom 8 "
		"odpowiada -hhx6 i jest wyjątkowo wolny."
	),
	MANIFEST_SUMMARY: "Easy Audio Converter",
	MANIFEST_DESCRIPTION: (
		"Dostępna kolejkowana i wielookienkowa konwersja audio oraz wyodrębnianie i remuksowanie "
		"strumieni bez ponownego kodowania, z planowaniem, szablonami nazw, "
		"normalizacją głośności, weryfikacją, profilami, opcjonalnym dołączonym "
		"kodowaniem GOGO WAV do MP3 i dołączonym FFmpeg."
	),
}

POLISH.update(
	{
		"...and {count} more skipped files": "...oraz {count} dalszych pominiętych plików",
		"A built-in profile already uses this name.": (
			"Profil wbudowany używa już tej nazwy."
		),
		"Access to the source or destination was denied.": (
			"Odmówiono dostępu do źródła lub miejsca docelowego."
		),
		"Additional skipped files: {count}": "Dodatkowe pominięte pliki: {count}",
		"Advanced codec overrides: disabled": (
			"Zaawansowane ustawienia kodeka: wyłączone"
		),
		"Advanced codec overrides: enabled": (
			"Zaawansowane ustawienia kodeka: włączone"
		),
		"Already uses the target format": "Plik ma już format docelowy",
		"Archive FLAC": "Archiwum FLAC",
		"At every file": "Przy każdym pliku",
		"At progress milestones": "W kolejnych etapach postępu",
		"Audiobook MP3": "Audiobook MP3",
		"Automatic progress announcements:": "Automatyczne komunikaty o postępie:",
		"Choose metadata fields": "Wybór pól metadanych",
		"Choose metadata fields...": "Wybierz pola metadanych...",
		"Conversion profile:": "Profil konwersji:",
		"Conversion report copied": "Skopiowano raport konwersji",
		"Conversion results": "Wyniki konwersji",
		"Convert": "Konwertuj",
		"Convert selected files or folders with one-time options": (
			"Konwertuj zaznaczone pliki lub foldery z ustawieniami jednorazowymi"
		),
		"Convert selected files or folders with options...": (
			"Konwertuj zaznaczone pliki lub foldery z opcjami..."
		),
		"Convert with options": "Konwertuj z opcjami",
		"Copy report": "Kopiuj raport",
		"Could not copy the conversion report.": (
			"Nie udało się skopiować raportu konwersji."
		),
		"Could not open the output folder.": "Nie udało się otworzyć folderu wynikowego.",
		"Delete conversion profile": "Usuń profil konwersji",
		"Delete profile": "Usuń profil",
		"Delete the profile “{name}”?": "Usunąć profil „{name}”?",
		"Details are limited to the first {limit} skipped files.": (
			"Szczegóły ograniczono do pierwszych {limit} pominiętych plików."
		),
		"Details:": "Szczegóły:",
		"Easy Audio Converter results": "Wyniki Easy Audio Converter",
		"Enter a name for this conversion profile:": (
			"Wprowadź nazwę tego profilu konwersji:"
		),
		"Estimated time remaining: 0:00": "Szacowany czas do zakończenia: 0:00",
		"Estimated time remaining: calculating": (
			"Szacowany czas do zakończenia: obliczanie"
		),
		"Estimated time remaining: {remaining}": (
			"Szacowany czas do zakończenia: {remaining}"
		),
		"Failed files:": "Pliki z błędami:",
		"Failed: {name}": "Błąd: {name}",
		"File or folder is unavailable": "Plik lub folder jest niedostępny",
		"No completion notification": "Bez powiadomienia o zakończeniu",
		"No conversion results are available": "Brak dostępnych wyników konwersji",
		"No failed files are available to retry": (
			"Brak plików z błędami, które można ponowić"
		),
		"No file details are available.": "Brak dostępnych szczegółów plików.",
		"One-time settings": "Ustawienia jednorazowe",
		"Only on demand": "Tylko na żądanie",
		"Open output folder": "Otwórz folder wynikowy",
		"Output files:": "Pliki wynikowe:",
		"Output:\n{output}": "Wynik:\n{output}",
		"Playing the completion sound": "Odtwarzanie dźwięku zakończenia",
		"Podcast Opus": "Podcast Opus",
		"Profile deleted": "Usunięto profil",
		"Profile saved: {name}": "Zapisano profil: {name}",
		"Replace the existing profile “{name}”?": (
			"Zastąpić istniejący profil „{name}”?"
		),
		"Retry failed files": "Ponów pliki z błędami",
		"Save conversion profile": "Zapisz profil konwersji",
		"Save profile...": "Zapisz profil...",
		"Select the text metadata fields to copy for this conversion.": (
			"Wybierz tekstowe pola metadanych do skopiowania podczas tej konwersji."
		),
		"Selected items: {count}": "Zaznaczone elementy: {count}",
		"Show last conversion results": "Pokaż wyniki ostatniej konwersji",
		"Show results": "Pokaż wyniki",
		"Show the last audio conversion results": (
			"Pokaż wyniki ostatniej konwersji audio"
		),
		"Skipped": "Pominięto",
		"Skipped files:": "Pominięte pliki:",
		"Skipped: {name}": "Pominięto: {name}",
		"Sound only": "Tylko dźwięk",
		"Source:\n{source}\n\nError:\n{error}": (
			"Źródło:\n{source}\n\nBłąd:\n{error}"
		),
		"Source:\n{source}\n\nOutput:\n{output}": (
			"Źródło:\n{source}\n\nWynik:\n{output}"
		),
		"Source:\n{source}\n\nReason:\n{reason}": (
			"Źródło:\n{source}\n\nPrzyczyna:\n{reason}"
		),
		"Speech and sound": "Mowa i dźwięk",
		"Speech only": "Tylko mowa",
		"Succeeded: {done}. Failed: {failed}. Skipped: {skipped}.": (
			"Ukończone: {done}. Błędy: {failed}. Pominięte: {skipped}."
		),
		"Success: {name}": "Sukces: {name}",
		"Successful completion notification:": (
			"Powiadomienie po poprawnym zakończeniu:"
		),
		"Successful files:": "Poprawnie ukończone pliki:",
		"Test completion sound": "Przetestuj dźwięk zakończenia",
		"The conversion was canceled.": "Konwersja została anulowana.",
		"The input does not contain a readable audio stream.": (
			"Plik wejściowy nie zawiera możliwej do odczytania ścieżki audio."
		),
		"The input file is damaged or uses an unsupported encoding.": (
			"Plik wejściowy jest uszkodzony lub używa nieobsługiwanego kodowania."
		),
		"The profile name cannot be empty.": "Nazwa profilu nie może być pusta.",
		"There is not enough free disk space.": "Brak wystarczającego miejsca na dysku.",
		"Unsupported file type": "Nieobsługiwany typ pliku",
		"Use these settings for future quick conversions": (
			"Używaj tych ustawień podczas przyszłych szybkich konwersji"
		),
		"calculating": "obliczanie",
		"{status} Estimated time remaining {remaining}.": (
			"{status} Szacowany czas do zakończenia: {remaining}."
		),
	}
)

POLISH.update(
	{
		"...and {count} more files": "...oraz {count} dalszych plików",
		"Analyzing loudness, first pass": "Analizowanie głośności, pierwszy przebieg",
		"Audio codec: {value}": "Kodek audio: {value}",
		"Audio file information": "Informacje o pliku audio",
		"Audio information copied": "Skopiowano informacje o pliku audio",
		"Audio information is already being read": "Informacje o pliku audio są już odczytywane",
		"Audio information ready. Codec {codec}, duration {duration}, sample rate {sampleRate}.": (
			"Informacje o pliku audio są gotowe. Kodek {codec}, czas {duration}, "
			"częstotliwość próbkowania {sampleRate}."
		),
		"Available fields: {source}, {title}, {artist}, {album}, {track}, {disc}, {index}, {format}.": (
			"Dostępne pola: {source}, {title}, {artist}, {album}, {track}, "
			"{disc}, {index}, {format}."
		),
		"Bitrate: {value}": "Przepływność: {value}",
		"Broadcast: -23 LUFS, -2 dBTP": "Emisja: -23 LUFS, -2 dBTP",
		"Building the conversion plan": "Tworzenie planu konwersji",
		"Channels: {value}": "Kanały: {value}",
		"Chapters: {value}": "Rozdziały: {value}",
		"Clear queued conversion jobs": "Wyczyść oczekujące zadania konwersji",
		"Clear queued jobs": "Wyczyść oczekujące zadania",
		"Cleared {count} queued conversion jobs": (
			"Wyczyszczono oczekujące zadania konwersji: {count}"
		),
		"Container: {value}": "Kontener: {value}",
		"Conversion job added to the queue. Queue position: {position}.": (
			"Dodano zadanie konwersji do kolejki. Pozycja w kolejce: {position}."
		),
		"Conversion plan": "Plan konwersji",
		"Conversion profiles exported": "Wyeksportowano profile konwersji",
		"Converting audio, second pass": "Konwertowanie dźwięku, drugi przebieg",
		"Copy chapter markers": "Kopiuj znaczniki rozdziałów",
		"Copy embedded cover artwork when supported": (
			"Kopiuj osadzoną okładkę, jeśli format ją obsługuje"
		),
		"Copy embedded cover artwork when the target supports it": (
			"Kopiuj osadzoną okładkę, jeśli obsługuje ją format docelowy"
		),
		"Copy information": "Kopiuj informacje",
		"Could not copy the audio information": (
			"Nie udało się skopiować informacji o pliku audio"
		),
		"Could not export profiles:\n{error}": "Nie udało się wyeksportować profili:\n{error}",
		"Could not import profiles:\n{error}": "Nie udało się zaimportować profili:\n{error}",
		"Could not read audio information:\n{error}": (
			"Nie udało się odczytać informacji o pliku audio:\n{error}"
		),
		"Custom EBU R128 target": "Własny poziom docelowy EBU R128",
		"Custom integrated loudness in LUFS:": "Własna głośność zintegrowana w LUFS:",
		"Custom loudness range in LU:": "Własny zakres głośności w LU:",
		"Custom true peak in dBTP:": "Własny szczyt rzeczywisty w dBTP:",
		"Deeply verify every output file": "Dokładnie weryfikuj każdy plik wynikowy",
		"Deeply verify output by decoding it and comparing duration": (
			"Dokładnie weryfikuj wynik przez dekodowanie i porównanie czasu"
		),
		"Destination: {destination}": "Miejsce docelowe: {destination}",
		"Disabled": "Wyłączona",
		"Duration: {value}": "Czas: {value}",
		"Embedded artwork: {value}": "Osadzona okładka: {value}",
		"Estimated output size: {size}": "Szacowany rozmiar wyników: {size}",
		"Example album": "Przykładowy album",
		"Example artist": "Przykładowy wykonawca",
		"Example filename: {name}": "Przykładowa nazwa pliku: {name}",
		"Example title": "Przykładowy tytuł",
		"Export conversion profiles": "Eksport profili konwersji",
		"Export profiles...": "Eksportuj profile...",
		"File size: {value}": "Rozmiar pliku: {value}",
		"Filename preview: {name}": "Podgląd nazwy pliku: {name}",
		"Files to convert: {count}": "Pliki do konwersji: {count}",
		"Free disk space: {size}": "Wolne miejsce na dysku: {size}",
		"GB": "GB",
		"Import conversion profiles": "Import profili konwersji",
		"Import profiles...": "Importuj profile...",
		"Imported {count} conversion profiles": "Zaimportowano profile konwersji: {count}",
		"Information about the selected audio file...": (
			"Informacje o zaznaczonym pliku audio..."
		),
		"Input size: {size}": "Rozmiar źródeł: {size}",
		"Invalid filename template: {error}": "Nieprawidłowy szablon nazwy: {error}",
		"JSON profile files (*.json)|*.json|All files (*.*)|*.*": (
			"Pliki profili JSON (*.json)|*.json|Wszystkie pliki (*.*)|*.*"
		),
		"KB": "KB",
		"Loudness normalization:": "Normalizacja głośności:",
		"MB": "MB",
		"Metadata:": "Metadane:",
		"Music and streaming: -14 LUFS, -1 dBTP": (
			"Muzyka i streaming: -14 LUFS, -1 dBTP"
		),
		"One conversion is active. Queued jobs: {count}.": (
			"Jedna konwersja jest aktywna. Oczekujące zadania: {count}."
		),
		"Output filename template:": "Szablon nazwy pliku wynikowego:",
		"Output verification failed because its duration differs from the source.": (
			"Weryfikacja wyniku nie powiodła się, ponieważ jego czas różni się od źródła."
		),
		"Path: {path}": "Ścieżka: {path}",
		"Planned output files:": "Planowane pliki wynikowe:",
		"Play a sound when a conversion fails": "Odtwarzaj dźwięk po błędzie konwersji",
		"Play a sound when a conversion is canceled or stopped": (
			"Odtwarzaj dźwięk po anulowaniu lub zatrzymaniu konwersji"
		),
		"Podcast: -16 LUFS, -1.5 dBTP": "Podcast: -16 LUFS, -1,5 dBTP",
		"Processing and notifications": "Przetwarzanie i powiadomienia",
		"Processing options": "Opcje przetwarzania",
		"Processing options...": "Opcje przetwarzania...",
		"Processing: loudness {loudness}; artwork {artwork}; chapters {chapters}; verification {verification}.": (
			"Przetwarzanie: głośność {loudness}; okładka {artwork}; "
			"rozdziały {chapters}; weryfikacja {verification}."
		),
		"Queued conversion jobs: {count}.": "Oczekujące zadania konwersji: {count}.",
		"Queued jobs: 0": "Oczekujące zadania: 0",
		"Queued jobs: {count}": "Oczekujące zadania: {count}",
		"Reading audio file information": "Odczytywanie informacji o pliku audio",
		"Reading audio information": "Odczytywanie informacji o dźwięku",
		"Report queued conversion jobs": "Odczytaj oczekujące zadania konwersji",
		"Review conversion plan": "Sprawdź plan konwersji",
		"Review the plan below. Size estimates are approximate. No source file will be overwritten.": (
			"Sprawdź poniższy plan. Rozmiary są przybliżone. "
			"Żaden plik źródłowy nie zostanie nadpisany."
		),
		"Sample rate: {value}": "Częstotliwość próbkowania: {value}",
		"Select exactly one audio file": "Zaznacz dokładnie jeden plik audio",
		"Show a conversion plan before starting": "Pokazuj plan konwersji przed rozpoczęciem",
		"Show technical information about the selected audio file": (
			"Pokaż informacje techniczne o zaznaczonym pliku audio"
		),
		"Show the conversion plan before starting": (
			"Pokaż plan konwersji przed rozpoczęciem"
		),
		"Skipped inputs: {count}": "Pominięte źródła: {count}",
		"Start conversion": "Rozpocznij konwersję",
		"Starting the next queued conversion. Jobs remaining: {count}.": (
			"Rozpoczynanie kolejnej konwersji z kolejki. Pozostałe zadania: {count}."
		),
		"Stop after current file": "Zatrzymaj po bieżącym pliku",
		"Stop after the current file": "Zatrzymaj po bieżącym pliku",
		"Stop the conversion after the current file": (
			"Zatrzymaj konwersję po bieżącym pliku"
		),
		"Stopped after the current file. Completed {done} of {total} files.": (
			"Zatrzymano po bieżącym pliku. Ukończono {done} z {total} plików."
		),
		"Stopping after this file...": "Zatrzymywanie po tym pliku...",
		"TB": "TB",
		"Test cancel sound": "Testuj dźwięk anulowania",
		"Test error sound": "Testuj dźwięk błędu",
		"Test success sound": "Testuj dźwięk sukcesu",
		"The conversion queue is empty": "Kolejka konwersji jest pusta",
		"The conversion will stop after the current file": (
			"Konwersja zatrzyma się po bieżącym pliku"
		),
		"The file does not contain valid conversion profiles.": (
			"Plik nie zawiera prawidłowych profili konwersji."
		),
		"The job was stopped after the current file.": (
			"Zadanie zatrzymano po bieżącym pliku."
		),
		"The profile file is too large.": "Plik profili jest zbyt duży.",
		"There are no user profiles to export": "Brak profili użytkownika do eksportu",
		"Total audio duration: {duration}": "Łączny czas nagrań: {duration}",
		"Verifying the output by decoding it": "Weryfikowanie wyniku przez dekodowanie",
		"Warning: the estimated output is larger than the available disk space.": (
			"Ostrzeżenie: szacowany rozmiar wyników przekracza wolne miejsce na dysku."
		),
		"Warning: {count} files will be converted from a lossy format to another lossy format, which can reduce quality.": (
			"Ostrzeżenie: pliki w liczbie {count} zostaną przekonwertowane z formatu "
			"stratnego do innego formatu stratnego, co może obniżyć jakość."
		),
		"bytes": "bajtów",
		"no": "nie",
		"off": "wyłączone",
		"on": "włączone",
		"source folders": "foldery źródłowe",
		"unknown": "nieznane",
		"yes": "tak",
		"{stage}. File {index} of {total}: {name}": (
			"{stage}. Plik {index} z {total}: {name}"
		),
		"{stage}. Queued jobs: {count}.": "{stage}. Oczekujące zadania: {count}.",
		"{stage}. {status} Queued jobs: {count}.": (
			"{stage}. {status} Oczekujące zadania: {count}."
		),
		"{value} Hz": "{value} Hz",
		"{value} kbps": "{value} kb/s",
	}
)

POLISH.update(
	{
		"BPM": "BPM",
		"Compilation": "Kompilacja",
		"Description": "Opis",
		"Edit metadata overrides": "Edytuj nadpisania metadanych",
		"Edit metadata overrides...": "Edytuj nadpisania metadanych...",
		"Encoder": "Enkoder",
		"Enter values to replace source tags for every converted file. Leave a field empty to keep its source value.": (
			"Wpisz wartości zastępujące tagi źródłowe we wszystkich konwertowanych plikach. "
			"Puste pole pozostawi wartość źródłową."
		),
		"Grouping": "Grupowanie",
		"ISRC": "ISRC",
		"Metadata overrides: {count} fields": "Nadpisania metadanych: pól {count}",
		"Sort album": "Sortowanie albumu",
		"Sort artist": "Sortowanie wykonawcy",
		"Sort title": "Sortowanie tytułu",
		"Total discs": "Łączna liczba płyt",
		"Total tracks": "Łączna liczba utworów",
		"Could not open Easy Audio Converter settings. See the NVDA log for details.": (
			"Nie udało się otworzyć ustawień Easy Audio Converter. "
			"Szczegóły znajdują się w dzienniku NVDA."
		),
		"Could not save Easy Audio Converter settings. See the NVDA log for details.": (
			"Nie udało się zapisać ustawień Easy Audio Converter. "
			"Szczegóły znajdują się w dzienniku NVDA."
		),
		"Easy Audio Converter settings": "Ustawienia Easy Audio Converter",
		"Advanced codec overrides are not used for stream copy": (
			"Zaawansowane ustawienia kodeka nie są używane podczas kopiowania strumienia"
		),
		"Extract original audio stream (no re-encoding)": (
			"Wyodrębnij oryginalny strumień audio (bez ponownego kodowania)"
		),
		"No advanced codec settings are used because the audio stream is copied without re-encoding.": (
			"Ustawienia zaawansowane kodeka nie są używane, ponieważ strumień "
			"audio jest kopiowany bez ponownego kodowania."
		),
		"No re-encoding: quality, loudness, and advanced codec settings are not used.": (
			"Bez ponownego kodowania: jakość, normalizacja głośności i "
			"zaawansowane ustawienia kodeka nie są używane."
		),
		"No re-encoding: quality, loudness, metadata, artwork, chapters, and advanced codec settings are not used.": (
			"Bez ponownego kodowania: jakość, normalizacja głośności, metadane, "
			"okładki, rozdziały i zaawansowane ustawienia kodeka nie są używane."
		),
		"No re-encoding: quality, loudness, source metadata, artwork, chapters, and advanced codec settings are not used. Explicit metadata overrides are still applied.": (
			"Bez ponownego kodowania: jakość, normalizacja głośności, metadane źródłowe, "
			"okładki, rozdziały i zaawansowane ustawienia kodeka nie są używane. "
			"Wprowadzone nadpisania metadanych są nadal stosowane."
		),
		"No readable audio stream was found": (
			"Nie znaleziono możliwego do odczytania strumienia audio"
		),
		"Quality is not used when copying audio without re-encoding": (
			"Jakość nie jest używana podczas kopiowania audio bez ponownego kodowania"
		),
		"Remux AAC to M4A (no re-encoding)": (
			"Remuksuj AAC do M4A (bez ponownego kodowania)"
		),
		"The first AAC audio stream will be remuxed into M4A without re-encoding. Sources whose first audio stream is not AAC are skipped.": (
			"Pierwszy strumień audio AAC zostanie przepakowany do M4A bez "
			"ponownego kodowania. Źródła, których pierwszy strumień audio nie "
			"jest AAC, zostaną pominięte."
		),
		"The first audio stream is not AAC, so it cannot be remuxed to M4A": (
			"Pierwszy strumień audio nie jest AAC, więc nie można go przepakować do M4A"
		),
		"The first audio stream will be extracted without re-encoding. Its codec and quality remain unchanged, and the output extension is selected automatically.": (
			"Pierwszy strumień audio zostanie wyodrębniony bez ponownego "
			"kodowania. Jego kodek i jakość pozostaną bez zmian, a rozszerzenie "
			"wyniku zostanie dobrane automatycznie."
		),
		"{name} (extension selected from the source audio codec)": (
			"{name} (rozszerzenie dobrane do kodeka źródłowego strumienia audio)"
		),
	}
)

POLISH.update(
	{
		"Converted output kept at: {output}": "Zachowany plik wynikowy: {output}",
		"Converted output kept at:\n{output}": (
			"Zachowany plik wynikowy:\n{output}"
		),
		"Replace source files": "Zastępowanie plików źródłowych",
		"Replace source files after successful conversion (permanently deletes originals)": (
			"Zastępuj pliki źródłowe po udanej konwersji "
			"(trwale usuwa oryginały)"
		),
		(
			"Replacing source files cannot be undone. After each output is "
			"created and checked successfully, its source file will be "
			"permanently deleted. Source files will be kept if conversion "
			"or verification fails. Continue?"
		): (
			"Zastępowania plików źródłowych nie można cofnąć. Po pomyślnym "
			"utworzeniu i sprawdzeniu każdego pliku wynikowego jego plik "
			"źródłowy zostanie trwale usunięty. Pliki źródłowe zostaną "
			"zachowane, jeśli konwersja lub weryfikacja się nie powiedzie. "
			"Kontynuować?"
		),
		(
			"Review the plan below. Size estimates are approximate. Source "
			"files will be permanently deleted after their outputs are "
			"completed successfully."
		): (
			"Sprawdź poniższy plan. Rozmiary są przybliżone. Pliki źródłowe "
			"zostaną trwale usunięte po pomyślnym utworzeniu odpowiadających "
			"im plików wynikowych."
		),
		"Do not close or restart NVDA while conversion is running. To stop safely, use the Cancel button.": (
			"Nie wyłączaj ani nie uruchamiaj ponownie NVDA podczas konwersji. "
			"Aby bezpiecznie przerwać, użyj przycisku „Anuluj”."
		),
		"The converted output was kept, but the source file could not be removed.": (
			"Przekonwertowany plik wynikowy został zachowany, ale nie udało "
			"się usunąć pliku źródłowego."
		),
		"Warning: source files will be permanently deleted after successful conversion.": (
			"Ostrzeżenie: po udanej konwersji pliki źródłowe zostaną trwale "
			"usunięte."
		),
	}
)

POLISH.update(
	{
		"16 files at a time": "16 plików naraz",
		"2 files at a time": "2 pliki naraz",
		"32 files at a time": "32 pliki naraz",
		"4 files at a time": "4 pliki naraz",
		"8 files at a time": "8 plików naraz",
		"Adaptive workers: {active} active, target {target}": (
			"Tryb adaptacyjny: aktywne {active}, cel {target}"
		),
		"Automatic (dynamic load balancing)": (
			"Automatycznie (dynamiczne dostosowanie obciążenia)"
		),
		"Automatic mode dynamically adjusts independent files using CPU and memory load.": (
			"Tryb automatyczny dynamicznie dostosowuje liczbę niezależnych plików "
			"do obciążenia procesora i pamięci."
		),
		"Automatic mode dynamically adjusts independent files using CPU and memory load. GPU acceleration is not used for audio encoding.": (
			"Tryb automatyczny dynamicznie dostosowuje liczbę niezależnych plików "
			"do obciążenia procesora i pamięci. Przyspieszanie GPU nie jest używane "
			"do kodowania dźwięku."
		),
		"Add new jobs to the queue": "Dodawaj nowe zadania do kolejki",
		"Run new jobs in separate progress windows": (
			"Uruchamiaj nowe zadania w osobnych oknach postępu"
		),
		"Separate progress windows run independently and may use more CPU and memory.": (
			"Osobne okna postępu działają niezależnie i mogą używać więcej procesora i pamięci."
		),
		"When another conversion is active:": "Gdy trwa już inna konwersja:",
		"Converting — Easy Audio Converter": "Konwertowanie — Easy Audio Converter",
		"Converting — Easy Audio Converter — separate job {id}": (
			"Konwertowanie — Easy Audio Converter — osobne zadanie {id}"
		),
		"Started a separate conversion window for the new job.": (
			"Nowe zadanie uruchomiono w osobnym oknie postępu."
		),
		"The separate conversion could not start:\n{error}": (
			"Nie można rozpocząć osobnej konwersji:\n{error}"
		),
		"Canceling {count} active conversions": (
			"Anulowanie aktywnych konwersji: {count}"
		),
		"The {count} active conversions will stop after their current files": (
			"Aktywne konwersje ({count}) zatrzymają się po bieżących plikach"
		),
		"One separate conversion is active. Queued jobs: {count}.": (
			"Jedna osobna konwersja jest aktywna. Oczekujące zadania: {count}."
		),
		"Active conversions: {active}. Queued jobs: {count}.": (
			"Aktywne konwersje: {active}. Oczekujące zadania: {count}."
		),
		"Active conversions: {count}.": "Aktywne konwersje: {count}.",
		"Main conversion": "Konwersja główna",
		"Separate conversion {index}": "Osobna konwersja {index}",
		"Queued jobs: {count}.": "Oczekujące zadania: {count}.",
		"{label}: {status}": "{label}: {status}",
		"{stage}. {status} Estimated time remaining {remaining}.": (
			"{stage}. {status} Szacowany czas do zakończenia: {remaining}."
		),
		"{status} Queued jobs: {count}.": "{status} Oczekujące zadania: {count}.",
		"{status}. Queued jobs: {count}.": "{status}. Oczekujące zadania: {count}.",
		"One file at a time": "Jeden plik naraz",
		"Parallel conversion jobs:": "Równoległe zadania konwersji:",
		"Parallel workers: finished": "Równoległe procesy: zakończono",
		"Parallel workers: waiting": "Równoległe procesy: oczekiwanie",
		"Parallel workers: {active} active of {target}": (
			"Równoległe procesy: aktywne {active} z {target}"
		),
		"{message}. Using {workers} parallel conversion workers.": (
			"{message}. Używam {workers} równoległych pracowników konwersji."
		),
		"{message}. Starting with {workers} adaptive conversion workers.": (
			"{message}. Rozpoczynam od {workers} adaptacyjnych pracowników konwersji."
		),
	}
)

PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]+\}")
PROTECTED_TOKEN_PATTERN = re.compile(
	r"\{[^{}]+\}|(?<!\w)-(?:hhx[1-6]|hh|h|f)\b|\b(?:FFmpeg|FLAC|WavPack)\b|\b\d+\b"
)


def extract_messages() -> list[str]:
	messages: set[str] = set()
	for path in SOURCE_ROOT.rglob("*.py"):
		tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
		for node in ast.walk(tree):
			if not (
				isinstance(node, ast.Call)
				and isinstance(node.func, ast.Name)
				and node.func.id == "_"
				and node.args
			):
				continue
			argument = node.args[0]
			if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
				messages.add(argument.value)
	return sorted(messages)


def _protect(message: str, message_index: int) -> tuple[str, dict[str, str]]:
	replacements: dict[str, str] = {}

	def replace(match: re.Match[str]) -> str:
		token = f"⟦EACPH{message_index:03d}_{len(replacements):02d}⟧"
		replacements[token] = match.group(0)
		return token

	return PROTECTED_TOKEN_PATTERN.sub(replace, message), replacements


def _preserves_lossless_profile_tokens(message: str, translation: str) -> bool:
	"""Sprawdza nieprzetłumaczalne nazwy i wartości profili kompresji."""
	if not (
		"FFmpeg level" in message
		or message.startswith("FLAC ")
		or message.startswith("All FLAC levels")
		or message.startswith("WavPack profiles")
	):
		return True
	return all(
		token in translation
		for token in PROTECTED_TOKEN_PATTERN.findall(message)
	)


def _restore_protected_tokens(result: str, replacements: dict[str, str]) -> str:
	"""Przywraca tokeny także wtedy, gdy tłumacz doda spację przed nawiasem."""
	for token, original in replacements.items():
		flexible_token = re.escape(token[:-1]) + r"\s*" + re.escape(token[-1])
		result = re.sub(flexible_token, lambda _match, value=original: value, result)
	return result


def _translate_request(payload: str, target: str) -> str:
	parameters = urllib.parse.urlencode(
		{
			"client": "gtx",
			"sl": "en",
			"tl": target,
			"dt": "t",
			"q": payload,
		}
	).encode("utf-8")
	request = urllib.request.Request(
		"https://translate.googleapis.com/translate_a/single",
		data=parameters,
		headers={"User-Agent": "Mozilla/5.0 EasyAudioConverterLocaleBuilder/1.0"},
		method="POST",
	)
	with urllib.request.urlopen(request, timeout=30) as response:
		data = json.loads(response.read().decode("utf-8"))
	return "".join(segment[0] for segment in data[0] if segment and segment[0])


def _translate_chunk(messages: list[str], target: str, offset: int) -> list[str]:
	protected_messages = []
	replacements: list[dict[str, str]] = []
	for local_index, message in enumerate(messages):
		protected, tokens = _protect(message, offset + local_index)
		protected_messages.append(protected)
		replacements.append(tokens)
	separators = [
		f"⟪EACSEP{offset + index:04d}⟫"
		for index in range(1, len(protected_messages))
	]
	parts: list[str] = []
	for index, message in enumerate(protected_messages):
		if index:
			parts.append(separators[index - 1])
		parts.append(message)
	payload = "\n".join(parts)

	last_error: Exception | None = None
	for attempt in range(3):
		try:
			translated = _translate_request(payload, target)
			break
		except (OSError, ValueError, urllib.error.URLError) as error:
			last_error = error
			time.sleep(1.5 * (attempt + 1))
	else:
		raise RuntimeError(f"translation request failed for {target}") from last_error

	results = [translated]
	for separator in separators:
		next_results: list[str] = []
		for result in results:
			if separator in result:
				left, right = result.split(separator, 1)
				next_results.extend((left, right))
			else:
				next_results.append(result)
		results = next_results
	if len(results) != len(messages):
		raise RuntimeError(
			f"translation separator mismatch for {target}: {len(results)} != {len(messages)}"
		)

	cleaned_results: list[str] = []
	for original, result, token_map in zip(messages, results, replacements):
		result = _restore_protected_tokens(result.strip(), token_map)
		if (
			"⟦EACPH" in result
			or sorted(PLACEHOLDER_PATTERN.findall(result))
			!= sorted(PLACEHOLDER_PATTERN.findall(original))
			or not _preserves_lossless_profile_tokens(original, result)
		):
			result = original
		cleaned_results.append(result)
	return cleaned_results


def translate_messages(messages: list[str], target: str) -> dict[str, str]:
	translations: list[str] = []
	chunk: list[str] = []
	chunk_size = 0
	offset = 0
	for message in messages:
		estimated = len(message.encode("utf-8")) + 30
		if chunk and chunk_size + estimated > 3000:
			translations.extend(_translate_chunk(chunk, target, offset))
			offset += len(chunk)
			chunk = []
			chunk_size = 0
		chunk.append(message)
		chunk_size += estimated
	if chunk:
		translations.extend(_translate_chunk(chunk, target, offset))
	return dict(zip(messages, translations))


def translate_messages_edge(messages: list[str], locale: str) -> dict[str, str]:
	"""Translate one catalog through the public translator used by Microsoft Edge."""
	user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/136.0"
	auth_request = urllib.request.Request(
		"https://edge.microsoft.com/translate/auth",
		headers={"User-Agent": user_agent},
	)
	with urllib.request.urlopen(auth_request, timeout=30) as response:
		token = response.read().decode("utf-8").strip()
	if not token:
		raise RuntimeError("Edge translation authorization returned no token")

	target = EDGE_TARGETS.get(locale, locale)
	protected_messages: list[str] = []
	replacements: list[dict[str, str]] = []
	for index, message in enumerate(messages):
		protected, token_map = _protect(message, index)
		protected_messages.append(protected)
		replacements.append(token_map)
	query = urllib.parse.urlencode(
		{
			"api-version": "3.0",
			"from": "en",
			"to": target,
		}
	)
	request = urllib.request.Request(
		f"https://api.cognitive.microsofttranslator.com/translate?{query}",
		data=json.dumps(
			[{"Text": message} for message in protected_messages],
			ensure_ascii=False,
		).encode("utf-8"),
		headers={
			"User-Agent": user_agent,
			"Authorization": f"Bearer {token}",
			"Content-Type": "application/json; charset=UTF-8",
		},
		method="POST",
	)
	with urllib.request.urlopen(request, timeout=45) as response:
		payload = json.loads(response.read().decode("utf-8"))
	if len(payload) != len(messages):
		raise RuntimeError(
			f"Edge translation result mismatch for {locale}: {len(payload)} != {len(messages)}"
		)

	translations: dict[str, str] = {}
	for original, item, token_map in zip(messages, payload, replacements):
		result = _restore_protected_tokens(
			str(item["translations"][0]["text"]).strip(),
			token_map,
		)
		if (
			"⟦EACPH" in result
			or sorted(PLACEHOLDER_PATTERN.findall(result))
			!= sorted(PLACEHOLDER_PATTERN.findall(original))
			or not _preserves_lossless_profile_tokens(original, result)
		):
			result = original
		translations[original] = result
	return translations


def _po_quote(value: str) -> str:
	return json.dumps(value, ensure_ascii=False)


def write_po(locale: str, catalog: dict[str, str], messages: list[str]) -> Path:
	directory = LOCALE_ROOT / locale / "LC_MESSAGES"
	directory.mkdir(parents=True, exist_ok=True)
	path = directory / "nvda.po"
	header = (
		"Project-Id-Version: Easy Audio Converter 1.9.1\n"
		"Report-Msgid-Bugs-To: https://github.com/kazek5p-git/easy-audio-converter/issues\n"
		"POT-Creation-Date: 2026-07-25 00:00+0200\n"
		"PO-Revision-Date: 2026-07-25 00:00+0200\n"
		"Language-Team: generated\n"
		f"Language: {locale}\n"
		"MIME-Version: 1.0\n"
		"Content-Type: text/plain; charset=UTF-8\n"
		"Content-Transfer-Encoding: 8bit\n"
		"Plural-Forms: nplurals=2; plural=(n != 1);\n"
		"X-Generator: Easy Audio Converter generate_locales.py\n"
		"X-Poedit-Basepath: ../../../..\n"
		"X-Poedit-KeywordsList: _\n"
		"X-Poedit-SearchPath-0: src\n"
	)
	lines = [
		"# Easy Audio Converter translation catalog.",
		"# Generated for NVDA; placeholders were validated automatically.",
		"msgid \"\"",
		f"msgstr {_po_quote(header)}",
		"",
	]
	references = extract_message_references()
	for message in messages:
		if references.get(message):
			lines.append("#: " + " ".join(references[message]))
		lines.extend(
			(
				f"msgid {_po_quote(message)}",
				f"msgstr {_po_quote(catalog.get(message, message))}",
				"",
			)
		)
	path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
	return path


def compile_mo(locale: str, catalog: dict[str, str]) -> Path:
	directory = LOCALE_ROOT / locale / "LC_MESSAGES"
	directory.mkdir(parents=True, exist_ok=True)
	path = directory / "nvda.mo"
	header = (
		"Project-Id-Version: Easy Audio Converter 1.9.1\n"
		f"Language: {locale}\n"
		"MIME-Version: 1.0\n"
		"Content-Type: text/plain; charset=UTF-8\n"
		"Content-Transfer-Encoding: 8bit\n"
	)
	complete_catalog = {"": header, **catalog}
	items = sorted(
		((key.encode("utf-8"), value.encode("utf-8")) for key, value in complete_catalog.items()),
		key=lambda item: item[0],
	)
	count = len(items)
	original_table_offset = 7 * 4
	translation_table_offset = original_table_offset + count * 8
	string_offset = translation_table_offset + count * 8
	original_data = b""
	translation_data = b""
	original_table = []
	translation_table = []
	for original, _translation in items:
		original_table.append((len(original), string_offset + len(original_data)))
		original_data += original + b"\0"
	translation_offset = string_offset + len(original_data)
	for _original, translation in items:
		translation_table.append((len(translation), translation_offset + len(translation_data)))
		translation_data += translation + b"\0"
	output = [
		struct.pack(
			"<7I",
			0x950412DE,
			0,
			count,
			original_table_offset,
			translation_table_offset,
			0,
			0,
		),
		b"".join(struct.pack("<2I", *entry) for entry in original_table),
		b"".join(struct.pack("<2I", *entry) for entry in translation_table),
		original_data,
		translation_data,
	]
	path.write_bytes(b"".join(output))
	return path


def write_manifest(locale: str, translations: dict[str, str]) -> None:
	path = LOCALE_ROOT / locale / "manifest.ini"
	summary = translations.get(MANIFEST_SUMMARY, MANIFEST_SUMMARY).replace('"', "'")
	description = translations.get(MANIFEST_DESCRIPTION, MANIFEST_DESCRIPTION).replace('"""', "'''")
	path.write_text(
		f'summary = "{summary}"\n'
		f'description = """{description}"""\n',
		encoding="utf-8",
		newline="\n",
	)


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument(
		"--locales",
		nargs="*",
		choices=NVDA_LOCALES,
		help="Regenerate only the listed NVDA locales.",
	)
	parser.add_argument(
		"--provider",
		choices=("auto", "google", "edge"),
		default="auto",
		help="Translation provider; auto falls back from Google to Edge.",
	)
	parser.add_argument(
		"--retry-english",
		action="store_true",
		help="Retry entries whose translation is still identical to English.",
	)
	parser.add_argument(
		"--offline",
		action="store_true",
		help="Do not contact translation services; use English fallback for missing entries.",
	)
	arguments = parser.parse_args()
	selected_locales = tuple(arguments.locales) if arguments.locales else NVDA_LOCALES
	runtime_messages = extract_messages()
	failures: list[str] = []
	edge_fallbacks: list[str] = []
	for position, locale in enumerate(selected_locales, start=1):
		po_path = LOCALE_ROOT / locale / "LC_MESSAGES" / "nvda.po"
		try:
			existing_catalog, _header = parse_po(po_path)
		except (OSError, ValueError):
			existing_catalog = {}
		translations = {
			message: existing_catalog.get(message, "")
			for message in runtime_messages
		}
		missing_messages = [
			message
			for message in runtime_messages
			if not translations.get(message)
			or not _preserves_lossless_profile_tokens(
				message,
				translations.get(message, ""),
			)
			or (
				locale == "pl"
				and message in POLISH
				and translations.get(message) == message
				and POLISH[message] != message
			)
			or (
				arguments.retry_english
				and translations.get(message) == message
			)
		]
		if locale == "pl":
			manual = {
				message: POLISH[message]
				for message in runtime_messages
				if message in POLISH
			}
			translations.update(manual)
			missing_messages = [
				message
				for message in runtime_messages
				if not translations.get(message)
			]
		if missing_messages and arguments.offline:
			new_translations = {message: message for message in missing_messages}
		elif missing_messages:
			try:
				if arguments.provider == "edge":
					new_translations = translate_messages_edge(missing_messages, locale)
				else:
					target = TRANSLATE_TARGETS.get(locale, locale)
					new_translations = translate_messages(missing_messages, target)
			except Exception:
				if arguments.provider == "google":
					new_translations = {message: message for message in missing_messages}
					failures.append(locale)
				else:
					try:
						new_translations = translate_messages_edge(missing_messages, locale)
						edge_fallbacks.append(locale)
					except Exception:
						new_translations = {message: message for message in missing_messages}
						failures.append(locale)
			translations.update(new_translations)
		runtime_catalog = {
			message: translations.get(message) or message
			for message in runtime_messages
		}
		write_po(locale, runtime_catalog, runtime_messages)
		compile_mo(locale, runtime_catalog)
		if not (LOCALE_ROOT / locale / "manifest.ini").is_file():
			write_manifest(
				locale,
				{
					MANIFEST_SUMMARY: MANIFEST_SUMMARY,
					MANIFEST_DESCRIPTION: MANIFEST_DESCRIPTION,
				},
			)
		print(
			f"[{position:02d}/{len(selected_locales)}] {locale}: "
			f"{len(runtime_catalog)} messages, {len(missing_messages)} added"
		)
	if edge_fallbacks:
		print("Edge translation fallback used for:", ", ".join(edge_fallbacks))
	if failures:
		print("English fallback used for:", ", ".join(failures))
	print(f"Generated {len(selected_locales)} locales with {len(runtime_messages)} runtime messages each.")


if __name__ == "__main__":
	main()
