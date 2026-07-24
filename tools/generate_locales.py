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
	"an": "es",
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
		f"https://api-edge.cognitive.microsofttranslator.com/translate?{query}",
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
		"Project-Id-Version: Easy Audio Converter 1.0.0\n"
		"Report-Msgid-Bugs-To: \n"
		"POT-Creation-Date: 2026-07-24 00:00+0200\n"
		"PO-Revision-Date: 2026-07-24 00:00+0200\n"
		"Language-Team: generated\n"
		f"Language: {locale}\n"
		"MIME-Version: 1.0\n"
		"Content-Type: text/plain; charset=UTF-8\n"
		"Content-Transfer-Encoding: 8bit\n"
		"Plural-Forms: nplurals=2; plural=(n != 1);\n"
	)
	lines = [
		"# Easy Audio Converter translation catalog.",
		"# Generated for NVDA; placeholders were validated automatically.",
		"msgid \"\"",
		f"msgstr {_po_quote(header)}",
		"",
	]
	for message in messages:
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
		"Project-Id-Version: Easy Audio Converter 1.0.0\n"
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
	arguments = parser.parse_args()
	selected_locales = tuple(arguments.locales) if arguments.locales else NVDA_LOCALES
	runtime_messages = extract_messages()
	all_messages = runtime_messages + [MANIFEST_DESCRIPTION]
	failures: list[str] = []
	edge_fallbacks: list[str] = []
	for position, locale in enumerate(selected_locales, start=1):
		if locale == "pl":
			translations = {message: POLISH.get(message, message) for message in all_messages}
		else:
			try:
				if arguments.provider == "edge":
					translations = translate_messages_edge(all_messages, locale)
				else:
					target = TRANSLATE_TARGETS.get(locale, locale)
					translations = translate_messages(all_messages, target)
			except Exception:
				if arguments.provider == "google":
					translations = {message: message for message in all_messages}
					failures.append(locale)
				else:
					try:
						translations = translate_messages_edge(all_messages, locale)
						edge_fallbacks.append(locale)
					except Exception:
						translations = {message: message for message in all_messages}
						failures.append(locale)
		runtime_catalog = {message: translations[message] for message in runtime_messages}
		write_po(locale, runtime_catalog, runtime_messages)
		compile_mo(locale, runtime_catalog)
		write_manifest(locale, translations)
		print(f"[{position:02d}/{len(selected_locales)}] {locale}: {len(runtime_catalog)} messages")
	if edge_fallbacks:
		print("Edge translation fallback used for:", ", ".join(edge_fallbacks))
	if failures:
		print("English fallback used for:", ", ".join(failures))
	print(f"Generated {len(selected_locales)} locales with {len(runtime_messages)} runtime messages each.")


if __name__ == "__main__":
	main()
