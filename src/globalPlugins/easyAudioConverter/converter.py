"""FFmpeg-backed conversion engine with no dependency on NVDA."""

from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence


FORMAT_KEYS = (
	"mp3",
	"wav",
	"flac",
	"ogg",
	"opus",
	"m4a",
	"aac",
	"wma",
	"alac",
	"aiff",
	"ac3",
	"eac3",
	"wavpack",
	"mp2",
	"amr",
	"amrwb",
)

FORMAT_EXTENSIONS = {
	"mp3": ".mp3",
	"wav": ".wav",
	"flac": ".flac",
	"ogg": ".ogg",
	"opus": ".opus",
	"m4a": ".m4a",
	"aac": ".aac",
	"wma": ".wma",
	"alac": ".m4a",
	"aiff": ".aiff",
	"ac3": ".ac3",
	"eac3": ".eac3",
	"wavpack": ".wv",
	"mp2": ".mp2",
	"amr": ".amr",
	"amrwb": ".awb",
}

QUALITY_KEYS = ("economical", "standard", "high", "veryHigh")
MP3_ENCODER_KEYS = ("lame", "fraunhofer")

# Audio-only files and popular media containers from which FFmpeg can extract audio.
AUDIO_EXTENSIONS = frozenset(
	{
		".3g2",
		".3gp",
		".4xm",
		".8svx",
		".aac",
		".ac3",
		".aif",
		".aifc",
		".aiff",
		".alac",
		".amr",
		".ape",
		".asf",
		".au",
		".avi",
		".awb",
		".caf",
		".dff",
		".dsf",
		".dts",
		".eac3",
		".flac",
		".flv",
		".gsm",
		".it",
		".m2ts",
		".m4a",
		".m4b",
		".m4r",
		".mka",
		".mkv",
		".mod",
		".mov",
		".mp2",
		".mp3",
		".mp4",
		".mpa",
		".mpeg",
		".mpg",
		".mts",
		".mxf",
		".oga",
		".ogg",
		".oma",
		".opus",
		".ra",
		".ram",
		".rm",
		".rmvb",
		".s3m",
		".snd",
		".spx",
		".tak",
		".tta",
		".ts",
		".vob",
		".voc",
		".wav",
		".webm",
		".wma",
		".wmv",
		".wv",
		".xm",
	}
)


@dataclass(frozen=True)
class ConversionSettings:
	target_format: str = "mp3"
	quality: str = "high"
	mp3_encoder: str = "lame"
	same_folder: bool = True
	output_folder: str = ""
	include_subfolders: bool = True
	preserve_folder_structure: bool = True

	def validate(self) -> None:
		if self.target_format not in FORMAT_KEYS:
			raise ValueError(f"Unsupported target format: {self.target_format}")
		if self.quality not in QUALITY_KEYS:
			raise ValueError(f"Unsupported quality preset: {self.quality}")
		if self.mp3_encoder not in MP3_ENCODER_KEYS:
			raise ValueError(f"Unsupported MP3 encoder: {self.mp3_encoder}")
		if not self.same_folder and not str(self.output_folder).strip():
			raise ValueError("A destination folder is required")


@dataclass
class ConversionFailure:
	source_name: str
	message: str


@dataclass
class ConversionSummary:
	total: int = 0
	succeeded: int = 0
	failed: int = 0
	ignored: int = 0
	canceled: bool = False
	outputs: list[str] = field(default_factory=list)
	failures: list[ConversionFailure] = field(default_factory=list)


@dataclass(frozen=True)
class ConversionCallbacks:
	on_collected: Callable[[int, int], None] | None = None
	on_file_start: Callable[[int, int, str, str], None] | None = None
	on_file_done: Callable[[int, int, str, str], None] | None = None


def _safe_callback(callback: Callable | None, *args) -> None:
	if callback is None:
		return
	try:
		callback(*args)
	except Exception:
		# A status callback must never stop a conversion.
		pass


def _normal_path(path: str | os.PathLike[str]) -> str:
	return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_below(path: Path, roots: Sequence[Path]) -> bool:
	normalized = _normal_path(path)
	for root in roots:
		root_normalized = _normal_path(root)
		if normalized == root_normalized:
			return True
		if normalized.startswith(root_normalized.rstrip("\\/") + os.sep):
			return True
	return False


def collect_audio_files(
	paths: Iterable[str | os.PathLike[str]],
	*,
	recursive: bool = True,
	excluded_roots: Iterable[str | os.PathLike[str]] = (),
) -> tuple[list[Path], int]:
	"""Collect supported files while avoiding duplicate paths and output trees."""
	excluded = tuple(Path(path) for path in excluded_roots if str(path).strip())
	files: list[Path] = []
	seen: set[str] = set()
	ignored = 0

	def add_file(candidate: Path) -> None:
		nonlocal ignored
		if _is_below(candidate, excluded):
			return
		if candidate.suffix.lower() not in AUDIO_EXTENSIONS:
			ignored += 1
			return
		key = _normal_path(candidate)
		if key in seen:
			return
		seen.add(key)
		files.append(candidate)

	for raw_path in paths:
		candidate = Path(raw_path)
		try:
			if candidate.is_file():
				add_file(candidate)
				continue
			if not candidate.is_dir():
				ignored += 1
				continue
			if _is_below(candidate, excluded):
				continue
			if recursive:
				for root, directory_names, file_names in os.walk(candidate, followlinks=False):
					root_path = Path(root)
					directory_names[:] = [
						name
						for name in directory_names
						if not _is_below(root_path / name, excluded)
					]
					for file_name in file_names:
						add_file(root_path / file_name)
			else:
				for child in candidate.iterdir():
					if child.is_file():
						add_file(child)
		except OSError:
			ignored += 1

	files.sort(key=lambda path: _normal_path(path))
	return files, ignored


def build_codec_arguments(target_format: str, quality: str, mp3_encoder: str) -> list[str]:
	"""Return output codec arguments for a validated format and quality preset."""
	if target_format not in FORMAT_KEYS:
		raise ValueError(f"Unsupported target format: {target_format}")
	if quality not in QUALITY_KEYS:
		raise ValueError(f"Unsupported quality preset: {quality}")
	if mp3_encoder not in MP3_ENCODER_KEYS:
		raise ValueError(f"Unsupported MP3 encoder: {mp3_encoder}")
	index = QUALITY_KEYS.index(quality)

	if target_format == "mp3":
		codec = "libmp3lame" if mp3_encoder == "lame" else "mp3_mf"
		return ["-c:a", codec, "-b:a", ("96k", "160k", "224k", "320k")[index], "-write_xing", "1"]
	if target_format == "wav":
		return ["-c:a", ("pcm_s16le", "pcm_s16le", "pcm_s24le", "pcm_s32le")[index]]
	if target_format == "flac":
		return ["-c:a", "flac", "-compression_level", ("0", "5", "8", "12")[index]]
	if target_format == "ogg":
		return ["-c:a", "libvorbis", "-q:a", ("2", "4", "6", "9")[index]]
	if target_format == "opus":
		return [
			"-c:a",
			"libopus",
			"-b:a",
			("64k", "128k", "192k", "256k")[index],
			"-vbr",
			"on",
			"-application",
			"audio",
		]
	if target_format in {"m4a", "aac"}:
		return ["-c:a", "aac", "-b:a", ("96k", "160k", "256k", "320k")[index]]
	if target_format == "wma":
		return ["-c:a", "wmav2", "-b:a", ("64k", "128k", "192k", "256k")[index]]
	if target_format == "alac":
		return ["-c:a", "alac"]
	if target_format == "aiff":
		return ["-c:a", ("pcm_s16be", "pcm_s16be", "pcm_s24be", "pcm_s32be")[index]]
	if target_format == "ac3":
		return ["-c:a", "ac3", "-b:a", ("128k", "192k", "384k", "640k")[index]]
	if target_format == "eac3":
		return ["-c:a", "eac3", "-b:a", ("128k", "192k", "384k", "768k")[index]]
	if target_format == "wavpack":
		return ["-c:a", "wavpack", "-compression_level", ("0", "2", "4", "8")[index]]
	if target_format == "mp2":
		return ["-c:a", "mp2", "-b:a", ("96k", "160k", "256k", "384k")[index]]
	if target_format == "amr":
		return [
			"-c:a",
			"libopencore_amrnb",
			"-b:a",
			("5.9k", "7.95k", "10.2k", "12.2k")[index],
			"-ar",
			"8000",
			"-ac",
			"1",
		]
	if target_format == "amrwb":
		return [
			"-c:a",
			"libvo_amrwbenc",
			"-b:a",
			("8.85k", "12.65k", "18.25k", "23.85k")[index],
			"-ar",
			"16000",
			"-ac",
			"1",
			"-f",
			"amr",
		]
	raise AssertionError(f"Missing codec mapping for {target_format}")


def make_unique_output_path(
	source: Path,
	output_directory: Path,
	target_extension: str,
	reserved: set[str] | None = None,
) -> Path:
	"""Choose a non-destructive output name, including same-format conversions."""
	reserved = reserved if reserved is not None else set()
	base_name = source.stem
	candidate = output_directory / f"{base_name}{target_extension}"
	if _normal_path(candidate) == _normal_path(source):
		base_name = f"{base_name} - converted"
		candidate = output_directory / f"{base_name}{target_extension}"
	number = 2
	while candidate.exists() or _normal_path(candidate) in reserved:
		candidate = output_directory / f"{base_name} ({number}){target_extension}"
		number += 1
	reserved.add(_normal_path(candidate))
	return candidate


def _relative_parent(source: Path, source_root: Path | None) -> Path:
	if source_root is None:
		return Path()
	try:
		return source.parent.resolve().relative_to(source_root.resolve())
	except (OSError, ValueError):
		return Path()


def _redact_ffmpeg_error(message: str, source: Path, output: Path) -> str:
	cleaned = (message or "").strip()
	for value, replacement in ((str(source), "<source>"), (str(output), "<output>")):
		cleaned = cleaned.replace(value, replacement)
	if not cleaned:
		return "FFmpeg returned an error without details"
	return cleaned[-2000:]


class Converter:
	"""Run one sequential conversion job and allow it to be canceled safely."""

	def __init__(self, ffmpeg_path: str | os.PathLike[str]):
		self.ffmpeg_path = Path(ffmpeg_path)
		self._cancel_event = threading.Event()
		self._process_lock = threading.Lock()
		self._process: subprocess.Popen[str] | None = None

	def cancel(self) -> None:
		self._cancel_event.set()
		with self._process_lock:
			process = self._process
		if process is not None and process.poll() is None:
			try:
				process.terminate()
			except OSError:
				pass

	def run(
		self,
		paths: Iterable[str | os.PathLike[str]],
		settings: ConversionSettings,
		*,
		source_root: str | os.PathLike[str] | None = None,
		callbacks: ConversionCallbacks | None = None,
	) -> ConversionSummary:
		settings.validate()
		if not self.ffmpeg_path.is_file():
			raise FileNotFoundError("The bundled FFmpeg executable is missing")
		path_list = tuple(paths)
		callbacks = callbacks or ConversionCallbacks()
		root = Path(source_root) if source_root else None
		excluded_roots: tuple[Path, ...] = ()
		if not settings.same_folder and settings.output_folder:
			output_root = Path(settings.output_folder)
			output_normalized = _normal_path(output_root)
			input_directories = [Path(path) for path in path_list if Path(path).is_dir()]
			if any(
				output_normalized.startswith(_normal_path(directory).rstrip("\\/") + os.sep)
				for directory in input_directories
			):
				excluded_roots = (output_root,)
		files, ignored = collect_audio_files(
			path_list,
			recursive=settings.include_subfolders,
			excluded_roots=excluded_roots,
		)
		summary = ConversionSummary(total=len(files), ignored=ignored)
		_safe_callback(callbacks.on_collected, summary.total, ignored)
		if not files or self._cancel_event.is_set():
			summary.canceled = self._cancel_event.is_set()
			return summary

		reserved_outputs: set[str] = set()
		for index, source in enumerate(files, start=1):
			if self._cancel_event.is_set():
				summary.canceled = True
				break
			if settings.same_folder:
				output_directory = source.parent
			else:
				output_directory = Path(settings.output_folder)
				if settings.preserve_folder_structure:
					output_directory /= _relative_parent(source, root)
			try:
				output_directory.mkdir(parents=True, exist_ok=True)
				output = make_unique_output_path(
					source,
					output_directory,
					FORMAT_EXTENSIONS[settings.target_format],
					reserved_outputs,
				)
			except OSError as error:
				summary.failed += 1
				summary.failures.append(ConversionFailure(source.name, str(error)))
				continue

			_safe_callback(callbacks.on_file_start, index, summary.total, source.name, output.name)
			command = [
				str(self.ffmpeg_path),
				"-nostdin",
				"-hide_banner",
				"-loglevel",
				"error",
				"-n",
				"-i",
				str(source),
				"-map",
				"0:a:0?",
				"-vn",
				"-sn",
				"-dn",
				"-map_metadata",
				"0",
				*build_codec_arguments(
					settings.target_format,
					settings.quality,
					settings.mp3_encoder,
				),
				str(output),
			]
			return_code, error_message = self._run_process(command)
			if self._cancel_event.is_set():
				summary.canceled = True
				self._remove_partial_output(output)
				break
			if return_code == 0 and output.is_file() and output.stat().st_size > 0:
				summary.succeeded += 1
				summary.outputs.append(str(output))
				_safe_callback(callbacks.on_file_done, index, summary.total, source.name, output.name)
				continue
			self._remove_partial_output(output)
			summary.failed += 1
			summary.failures.append(
				ConversionFailure(
					source.name,
					_redact_ffmpeg_error(error_message, source, output),
				)
			)
		return summary

	def _run_process(self, command: list[str]) -> tuple[int, str]:
		creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
		process = subprocess.Popen(
			command,
			stdin=subprocess.DEVNULL,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.PIPE,
			text=True,
			encoding="utf-8",
			errors="replace",
			creationflags=creation_flags,
		)
		with self._process_lock:
			self._process = process
		error_message = ""
		try:
			while True:
				try:
					_, error_message = process.communicate(timeout=0.25)
					break
				except subprocess.TimeoutExpired:
					if self._cancel_event.is_set():
						try:
							process.terminate()
						except OSError:
							pass
			return process.returncode, error_message
		finally:
			with self._process_lock:
				if self._process is process:
					self._process = None

	@staticmethod
	def _remove_partial_output(output: Path) -> None:
		try:
			if output.is_file():
				output.unlink()
		except OSError:
			pass


def query_ffmpeg_version(ffmpeg_path: str | os.PathLike[str]) -> str:
	"""Return the first FFmpeg version line for diagnostics."""
	result = subprocess.run(
		[str(ffmpeg_path), "-hide_banner", "-version"],
		stdin=subprocess.DEVNULL,
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		encoding="utf-8",
		errors="replace",
		timeout=10,
		creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
		check=False,
	)
	return result.stdout.splitlines()[0] if result.stdout else ""
