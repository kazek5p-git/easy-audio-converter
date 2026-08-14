# Copyright (C) 2026 Kazimierz Parzych
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bezpieczna integracja z dołączonym enkoderem GOGO-no-coda.

Moduł przygotowuje wyłącznie listę argumentów procesu i odczytuje jego
komunikaty. Dzięki temu ścieżki plików nie przechodzą przez powłokę systemową,
a backend może być używany niezależnie od interfejsu NVDA. Użytkownik może
zastąpić dołączony plik własną wersją, podając jej ścieżkę w ustawieniach.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


GOGO_BITRATE_PRESETS = (0, 64, 128, 160, 192, 256, 320)
GOGO_QUALITY_VALUES = tuple(range(10))
GOGO_MAX_EXTRA_ARGUMENTS = 32
GOGO_MAX_EXTRA_ARGUMENT_LENGTH = 2048
GOGO_WAVE_SUFFIXES = frozenset({".wav", ".wave"})


def bundled_gogo_path() -> Path:
	"""Zwróć ścieżkę do enkodera dołączonego do dodatku."""
	return Path(__file__).resolve().parent / "bin" / "gogo.exe"


def resolve_gogo_path(executable: str | os.PathLike[str] | None) -> Path:
	"""Wybierz własny enkoder albo wersję dołączoną do dodatku."""
	path_text = str(executable or "").strip()
	return Path(path_text) if path_text else bundled_gogo_path()


def validate_gogo_options(
	*,
	path: str | os.PathLike[str],
	bitrate: int,
	quality: int,
	extra_arguments: str,
	require_executable: bool = False,
) -> None:
	"""Sprawdź ustawienia GOGO bez uruchamiania procesu.

	``require_executable`` jest używane dopiero przy starcie zadania, aby
	sprawdzić dostępność wersji dołączonej albo wybranej przez użytkownika.
	"""
	path_text = str(path or "").strip()
	if len(path_text) > 32768:
		raise ValueError("The GOGO executable path is too long")
	if require_executable:
		executable = resolve_gogo_path(path_text)
		if not executable.is_file():
			raise FileNotFoundError(
				"The configured or bundled GOGO executable is missing"
			)
	try:
		bitrate_value = int(bitrate)
	except (TypeError, ValueError) as error:
		raise ValueError("Invalid GOGO bitrate preset") from error
	if (
		isinstance(bitrate, bool)
		or bitrate_value != bitrate
		or bitrate_value not in GOGO_BITRATE_PRESETS
	):
		raise ValueError("Unsupported GOGO bitrate preset")
	try:
		quality_value = int(quality)
	except (TypeError, ValueError) as error:
		raise ValueError("Invalid GOGO quality value") from error
	if (
		isinstance(quality, bool)
		or quality_value != quality
		or quality_value not in GOGO_QUALITY_VALUES
	):
		raise ValueError("GOGO quality must be between 0 and 9")
	if not isinstance(extra_arguments, str):
		raise ValueError("GOGO additional arguments must be text")
	if "\x00" in extra_arguments:
		raise ValueError("GOGO additional arguments cannot contain NUL bytes")
	if len(extra_arguments) > GOGO_MAX_EXTRA_ARGUMENT_LENGTH:
		raise ValueError("GOGO additional arguments are too long")
	parse_gogo_extra_arguments(extra_arguments)


def parse_gogo_extra_arguments(value: str) -> tuple[str, ...]:
	"""Podziel dodatkowe opcje GOGO bez używania powłoki systemowej.

	Parser Windowsowy zachowuje cytowane fragmenty jako pojedyncze argumenty.
	Cudzysłowy otaczające cały argument są usuwane, ponieważ później argumenty
	są przekazywane bezpośrednio do ``subprocess``.
	"""
	if not isinstance(value, str):
		raise ValueError("GOGO additional arguments must be text")
	try:
		tokens = shlex.split(value, posix=False)
	except ValueError as error:
		raise ValueError("GOGO additional arguments contain invalid quoting") from error
	if len(tokens) > GOGO_MAX_EXTRA_ARGUMENTS:
		raise ValueError("Too many GOGO additional arguments")
	cleaned: list[str] = []
	for token in tokens:
		if "\x00" in token:
			raise ValueError("GOGO additional arguments cannot contain NUL bytes")
		if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
			token = token[1:-1]
		if token:
			cleaned.append(token)
	return tuple(cleaned)


def gogo_bitrate_arguments(bitrate: int) -> tuple[str, ...]:
	"""Zwróć opcje bitrate i trybu stereo dla presetu GOGO."""
	validate_gogo_options(path="", bitrate=bitrate, quality=0, extra_arguments="")
	if int(bitrate) == 0:
		return ()
	mode = "s" if int(bitrate) >= 256 else "j"
	return ("-b", str(int(bitrate)), "-m", mode)


def build_gogo_command(
	executable: str | os.PathLike[str],
	source: str | os.PathLike[str],
	destination: str | os.PathLike[str],
	*,
	bitrate: int = 0,
	quality: int = 0,
	extra_arguments: str = "",
) -> list[str]:
	"""Zbuduj polecenie GOGO jako listę argumentów procesu.

	Źródło i wynik są zawsze ostatnimi argumentami, tak jak w GOGO-no-coda.
	Nie jest używany ``shell=True`` ani konkatenacja ścieżek w jeden tekst.
	"""
	resolved_executable = resolve_gogo_path(executable)
	validate_gogo_options(
		path=resolved_executable,
		bitrate=bitrate,
		quality=quality,
		extra_arguments=extra_arguments,
		require_executable=True,
	)
	source_path = Path(source)
	destination_path = Path(destination)
	return [
		str(resolved_executable),
		*gogo_bitrate_arguments(int(bitrate)),
		"-q",
		str(int(quality)),
		*parse_gogo_extra_arguments(extra_arguments),
		str(source_path),
		str(destination_path),
	]


def read_gogo_help(
	executable: str | os.PathLike[str],
	*,
	timeout: float = 10.0,
) -> str:
	"""Uruchom GOGO bez argumentów i zwróć tekst pomocy z wyjścia błędów."""
	path = resolve_gogo_path(executable)
	if not path.is_file():
		raise FileNotFoundError(
			"The configured or bundled GOGO executable is missing"
		)
	process = subprocess.run(
		[str(path)],
		stdin=subprocess.DEVNULL,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
		encoding="utf-8",
		errors="replace",
		timeout=timeout,
		creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
		check=False,
	)
	output = (process.stderr or process.stdout or "").strip()
	if not output:
		output = "GOGO did not return any help text."
	return output


def is_gogo_wav(path: str | os.PathLike[str]) -> bool:
	"""Sprawdź, czy ścieżka ma rozszerzenie obsługiwane przez GOGO."""
	return Path(path).suffix.casefold() in GOGO_WAVE_SUFFIXES
