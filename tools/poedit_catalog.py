"""Poedit-compatible gettext catalog maintenance for Easy Audio Converter."""

from __future__ import annotations

import argparse
import ast
import json
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
LOCALE_ROOT = SOURCE_ROOT / "locale"
POT_PATH = LOCALE_ROOT / "EasyAudioConverter.pot"
VERSION = "1.8.2"
PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]+\}")


@dataclass
class PoEntry:
	msgid: str = ""
	msgstr: str = ""
	flags: set[str] = field(default_factory=set)


def extract_messages() -> dict[str, list[str]]:
	"""Extract literal gettext calls and their source references."""
	messages: dict[str, list[str]] = {}
	for path in sorted(SOURCE_ROOT.rglob("*.py")):
		tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
		relative = path.relative_to(PROJECT_ROOT).as_posix()
		for node in ast.walk(tree):
			if not (
				isinstance(node, ast.Call)
				and isinstance(node.func, ast.Name)
				and node.func.id == "_"
				and node.args
			):
				continue
			argument = node.args[0]
			if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
				continue
			reference = f"{relative}:{node.lineno}"
			messages.setdefault(argument.value, []).append(reference)
	return dict(sorted(messages.items()))


def _decode_po_string(value: str) -> str:
	try:
		decoded = ast.literal_eval(value.strip())
	except (SyntaxError, ValueError) as error:
		raise ValueError(f"Invalid PO string: {value}") from error
	if not isinstance(decoded, str):
		raise ValueError(f"Invalid PO string: {value}")
	return decoded


def parse_po(path: Path) -> tuple[dict[str, str], str]:
	"""Read the non-plural subset used by this add-on, including Poedit wrapping."""
	entries: list[PoEntry] = []
	current: PoEntry | None = None
	active_field: str | None = None

	def finish() -> None:
		nonlocal current, active_field
		if current is not None:
			entries.append(current)
		current = None
		active_field = None

	for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
		line = raw_line.strip()
		if not line:
			finish()
			continue
		if line.startswith("#~"):
			continue
		if line.startswith("#,"):
			if current is None:
				current = PoEntry()
			current.flags.update(flag.strip() for flag in line[2:].split(","))
			continue
		if line.startswith("#"):
			continue
		if line.startswith("msgid "):
			if current is not None and (current.msgid or current.msgstr):
				finish()
			current = current or PoEntry()
			current.msgid = _decode_po_string(line[6:])
			active_field = "msgid"
			continue
		if line.startswith("msgstr "):
			current = current or PoEntry()
			current.msgstr = _decode_po_string(line[7:])
			active_field = "msgstr"
			continue
		if line.startswith("msgid_plural") or line.startswith("msgstr["):
			raise ValueError(f"Plural entries are not supported: {path}:{line_number}")
		if line.startswith('"') and active_field and current is not None:
			value = _decode_po_string(line)
			setattr(current, active_field, getattr(current, active_field) + value)
			continue
		raise ValueError(f"Unsupported PO syntax: {path}:{line_number}: {raw_line}")
	finish()

	catalog: dict[str, str] = {}
	header = ""
	for entry in entries:
		if entry.msgid == "":
			header = entry.msgstr
			continue
		if "fuzzy" in entry.flags:
			catalog[entry.msgid] = ""
		else:
			catalog[entry.msgid] = entry.msgstr
	return catalog, header


def _po_quote(value: str) -> str:
	return json.dumps(value, ensure_ascii=False)


def _header(language: str = "", base_path: str = "../..") -> str:
	now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M%z")
	return (
		f"Project-Id-Version: Easy Audio Converter {VERSION}\n"
		"Report-Msgid-Bugs-To: https://github.com/kazek5p-git/easy-audio-converter/issues\n"
		f"POT-Creation-Date: {now}\n"
		"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
		"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
		"Language-Team: LANGUAGE <LL@li.org>\n"
		f"Language: {language}\n"
		"MIME-Version: 1.0\n"
		"Content-Type: text/plain; charset=UTF-8\n"
		"Content-Transfer-Encoding: 8bit\n"
		"Plural-Forms: nplurals=2; plural=(n != 1);\n"
		"X-Generator: Easy Audio Converter poedit_catalog.py\n"
		f"X-Poedit-Basepath: {base_path}\n"
		"X-Poedit-KeywordsList: _\n"
		"X-Poedit-SearchPath-0: src\n"
	)


def write_pot(messages: dict[str, list[str]]) -> None:
	LOCALE_ROOT.mkdir(parents=True, exist_ok=True)
	lines = [
		"# Easy Audio Converter translation template.",
		"# Open this file in Poedit to create a new translation.",
		"msgid \"\"",
		f"msgstr {_po_quote(_header())}",
		"",
	]
	for message, references in messages.items():
		lines.append("#: " + " ".join(references))
		lines.append(f"msgid {_po_quote(message)}")
		lines.append('msgstr ""')
		lines.append("")
	POT_PATH.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def merge_po(path: Path, messages: dict[str, list[str]]) -> None:
	existing, _old_header = parse_po(path)
	locale = path.parents[1].name
	lines = [
		"# Easy Audio Converter translation.",
		"# Edit and save this file with Poedit; then run the compile command.",
		"msgid \"\"",
		f"msgstr {_po_quote(_header(locale, '../../../..'))}",
		"",
	]
	for message, references in messages.items():
		lines.append("#: " + " ".join(references))
		lines.append(f"msgid {_po_quote(message)}")
		lines.append(f"msgstr {_po_quote(existing.get(message, ''))}")
		lines.append("")
	path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def compile_mo(path: Path, catalog: dict[str, str], header: str) -> None:
	complete_catalog = {"": header, **{key: value for key, value in catalog.items() if value}}
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


def validate_catalog(
	path: Path,
	catalog: dict[str, str],
	messages: dict[str, list[str]],
	header: str,
) -> list[str]:
	errors: list[str] = []
	locale = path.parents[1].name
	if f"Language: {locale}\n" not in header:
		errors.append(f"{path}: header language does not match {locale!r}")
	if "X-Poedit-Basepath: ../../../..\n" not in header:
		errors.append(f"{path}: incorrect Poedit base path")
	for msgid in messages:
		if msgid not in catalog:
			errors.append(f"{path}: missing msgid: {msgid!r}")
			continue
		msgstr = catalog[msgid]
		if not msgstr:
			errors.append(f"{path}: untranslated msgid: {msgid!r}")
			continue
		if sorted(PLACEHOLDER_PATTERN.findall(msgid)) != sorted(
			PLACEHOLDER_PATTERN.findall(msgstr)
		):
			errors.append(f"{path}: placeholder mismatch: {msgid!r}")
	return errors


def locale_po_files() -> list[Path]:
	return sorted(LOCALE_ROOT.glob("*/LC_MESSAGES/nvda.po"))


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Maintain Poedit-compatible Easy Audio Converter catalogs.",
	)
	parser.add_argument(
		"command",
		choices=("pot", "merge", "compile", "validate", "all"),
		nargs="?",
		default="all",
	)
	arguments = parser.parse_args()
	messages = extract_messages()
	if arguments.command in {"pot", "all"}:
		write_pot(messages)
		print(f"Wrote {POT_PATH} with {len(messages)} messages")
	if arguments.command in {"merge", "all"}:
		for po_path in locale_po_files():
			merge_po(po_path, messages)
		print(f"Merged {len(locale_po_files())} PO catalogs")
	if arguments.command in {"compile", "validate", "all"}:
		errors: list[str] = []
		catalogs = []
		po_files = locale_po_files()
		for po_path in po_files:
			catalog, header = parse_po(po_path)
			errors.extend(validate_catalog(po_path, catalog, messages, header))
			catalogs.append((po_path, catalog, header))
		if errors:
			maximum_reported_errors = 100
			for error in errors[:maximum_reported_errors]:
				print(error)
			if len(errors) > maximum_reported_errors:
				print(
					f"... and {len(errors) - maximum_reported_errors} more validation errors"
				)
			print(f"Catalog validation failed with {len(errors)} errors")
			return 1
		if arguments.command in {"compile", "all"}:
			for po_path, catalog, header in catalogs:
				compile_mo(po_path.with_suffix(".mo"), catalog, header)
			print(f"Compiled {len(po_files)} MO catalogs")
		print(f"Validated {len(po_files)} catalogs")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
