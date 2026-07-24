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
	"Accessible single-file and batch audio conversion from Windows Explorer, "
	"powered by bundled FFmpeg."
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
	"Choose the destination folder": "Wybierz folder docelowy",
	"Confirm folder conversion": "Potwierdź konwersję folderu",
	"Conversion canceled. Completed {done} of {total} files.": (
		"Konwersja anulowana. Ukończono {done} z {total} plików."
	),
	"Conversion complete: {done} succeeded, {failed} failed.": (
		"Konwersja zakończona: powodzenie dla {done}, błędy dla {failed}."
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
	"Found {count} files to convert": "Znaleziono pliki do konwersji: {count}",
	"Fraunhofer / Windows Media Foundation MP3": "Fraunhofer / Windows Media Foundation MP3",
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
	"Quality:": "Jakość:",
	"Quality: {quality}": "Jakość: {quality}",
	"Quickly choose the destination folder": "Szybko wybierz folder docelowy",
	"Quickly convert selected files or folders": "Szybko konwertuj zaznaczone pliki lub foldery",
	"Report audio conversion status": "Odczytaj stan konwersji audio",
	"Report conversion status": "Odczytaj stan konwersji",
	"Save converted files next to the source files": (
		"Zapisuj przekonwertowane pliki obok plików źródłowych"
	),
	"Settings...": "Ustawienia...",
	"Some files could not be converted:\n\n{details}": (
		"Nie udało się przekonwertować niektórych plików:\n\n{details}"
	),
	"Standard": "Standardowa",
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
	"Easy Audio Converter progress": "Postęp Easy Audio Converter",
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
	"For FLAC, level 0 is fastest and level 12 gives the strongest compression.": (
		"Dla FLAC poziom 0 jest najszybszy, a poziom 12 zapewnia najsilniejszą kompresję."
	),
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
	"For WavPack, levels 0 to 8 select increasing compression effort.": (
		"Dla WavPack poziomy od 0 do 8 wybierają rosnący stopień kompresji."
	),
	"Genre": "Gatunek",
	"Hide": "Ukryj",
	"Keep the source channel count": "Zachowaj liczbę kanałów źródła",
	"Keep the source sample rate": "Zachowaj częstotliwość próbkowania źródła",
	"Language": "Język",
	"Later": "Później",
	"Lyrics": "Tekst utworu",
	"Metadata export:": "Eksport metadanych:",
	"Metadata fields to copy:": "Pola metadanych do skopiowania:",
	"Mono": "Mono",
	"No conversion progress is available": "Brak dostępnych informacji o postępie konwersji",
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
	MANIFEST_SUMMARY: "Easy Audio Converter",
	MANIFEST_DESCRIPTION: (
		"Dostępna konwersja pojedynczych plików i konwersja masowa audio "
		"z Eksploratora Windows przy użyciu dołączonego FFmpeg."
	),
}

PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]+\}")


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

	return PLACEHOLDER_PATTERN.sub(replace, message), replacements


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
		result = result.strip()
		for token, placeholder in token_map.items():
			result = result.replace(token, placeholder)
		if sorted(PLACEHOLDER_PATTERN.findall(result)) != sorted(PLACEHOLDER_PATTERN.findall(original)):
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
		result = str(item["translations"][0]["text"]).strip()
		for placeholder_token, placeholder in token_map.items():
			result = result.replace(placeholder_token, placeholder)
		if sorted(PLACEHOLDER_PATTERN.findall(result)) != sorted(PLACEHOLDER_PATTERN.findall(original)):
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
		"Project-Id-Version: Easy Audio Converter 1.1.0\n"
		"Report-Msgid-Bugs-To: https://github.com/kazek5p-git/easy-audio-converter/issues\n"
		"POT-Creation-Date: 2026-07-24 00:00+0200\n"
		"PO-Revision-Date: 2026-07-24 00:00+0200\n"
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
		"Project-Id-Version: Easy Audio Converter 1.1.0\n"
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
				for message in missing_messages
				if message in POLISH
			}
			translations.update(manual)
			missing_messages = [
				message
				for message in missing_messages
				if not translations.get(message)
			]
		if missing_messages:
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
