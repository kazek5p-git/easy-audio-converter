"""FFmpeg-backed conversion engine with no dependency on NVDA."""

from __future__ import annotations

import os
import re
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


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
METADATA_MODE_KEYS = ("none", "all", "selected")
METADATA_FIELD_KEYS = (
	"title",
	"artist",
	"album",
	"album_artist",
	"composer",
	"genre",
	"date",
	"track",
	"disc",
	"comment",
	"copyright",
	"lyrics",
	"language",
	"publisher",
)
DEFAULT_METADATA_FIELDS = (
	"title",
	"artist",
	"album",
	"album_artist",
	"composer",
	"genre",
	"date",
	"track",
	"disc",
)
ADVANCED_SAMPLE_RATES = (0, 8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200, 96000, 192000)
ADVANCED_CHANNEL_COUNTS = (0, 1, 2)
ADVANCED_BIT_DEPTHS = (0, 16, 24, 32)

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
	metadata_mode: str = "all"
	metadata_fields: tuple[str, ...] = DEFAULT_METADATA_FIELDS
	advanced_options: Mapping[str, Any] = field(default_factory=dict)

	def validate(self) -> None:
		if self.target_format not in FORMAT_KEYS:
			raise ValueError(f"Unsupported target format: {self.target_format}")
		if self.quality not in QUALITY_KEYS:
			raise ValueError(f"Unsupported quality preset: {self.quality}")
		if self.mp3_encoder not in MP3_ENCODER_KEYS:
			raise ValueError(f"Unsupported MP3 encoder: {self.mp3_encoder}")
		if self.metadata_mode not in METADATA_MODE_KEYS:
			raise ValueError(f"Unsupported metadata mode: {self.metadata_mode}")
		if any(field_name not in METADATA_FIELD_KEYS for field_name in self.metadata_fields):
			raise ValueError("Unsupported metadata field")
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
	on_progress: Callable[[int, int, str, float | None, float, float, float | None], None] | None = None
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


def _build_base_codec_arguments(target_format: str, quality: str, mp3_encoder: str) -> list[str]:
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


def _replace_argument(arguments: list[str], option: str, value: str) -> None:
	try:
		index = arguments.index(option)
	except ValueError:
		arguments.extend((option, value))
	else:
		if index + 1 < len(arguments):
			arguments[index + 1] = value
		else:
			arguments.append(value)


def _integer_option(options: Mapping[str, Any], name: str, default: int = 0) -> int:
	try:
		return int(options.get(name, default))
	except (TypeError, ValueError):
		return default


def _nearest_rate(value: int, supported: Sequence[float]) -> float:
	return min(supported, key=lambda candidate: abs(candidate - value))


def apply_advanced_codec_arguments(
	arguments: list[str],
	target_format: str,
	mp3_encoder: str,
	options: Mapping[str, Any] | None,
) -> list[str]:
	"""Apply validated per-codec overrides without accepting raw command text."""
	arguments = list(arguments)
	if not options or not bool(options.get("enabled", False)):
		return arguments

	bitrate = max(0, _integer_option(options, "bitrate"))
	bitrate_limits = {
		"mp3": 320,
		"opus": 512,
		"m4a": 512,
		"aac": 512,
		"wma": 320,
		"ac3": 640,
		"eac3": 1536,
		"mp2": 384,
		"amr": 13,
		"amrwb": 24,
	}
	if bitrate and target_format in bitrate_limits:
		bitrate = min(bitrate, bitrate_limits[target_format])
		if target_format == "amr":
			rate = _nearest_rate(bitrate, (4.75, 5.15, 5.9, 6.7, 7.4, 7.95, 10.2, 12.2))
			bitrate_value = f"{rate:g}k"
		elif target_format == "amrwb":
			rate = _nearest_rate(
				bitrate,
				(6.6, 8.85, 12.65, 14.25, 15.85, 18.25, 19.85, 23.05, 23.85),
			)
			bitrate_value = f"{rate:g}k"
		else:
			bitrate_value = f"{bitrate}k"
		_replace_argument(arguments, "-b:a", bitrate_value)

	sample_rate = _integer_option(options, "sampleRate")
	if sample_rate in ADVANCED_SAMPLE_RATES and sample_rate and target_format not in {"amr", "amrwb", "opus"}:
		_replace_argument(arguments, "-ar", str(sample_rate))

	channels = _integer_option(options, "channels")
	if channels in ADVANCED_CHANNEL_COUNTS and channels and target_format not in {"amr", "amrwb"}:
		_replace_argument(arguments, "-ac", str(channels))

	level = _integer_option(options, "codecLevel", -1)
	if level >= 0:
		if target_format == "mp3" and mp3_encoder == "lame":
			_replace_argument(arguments, "-compression_level", str(min(level, 9)))
		elif target_format == "flac":
			_replace_argument(arguments, "-compression_level", str(min(level, 12)))
		elif target_format == "ogg":
			_replace_argument(arguments, "-q:a", str(min(level, 10)))
		elif target_format == "opus":
			_replace_argument(arguments, "-compression_level", str(min(level, 10)))
		elif target_format == "wavpack":
			_replace_argument(arguments, "-compression_level", str(min(level, 8)))

	bit_depth = _integer_option(options, "bitDepth")
	if bit_depth in ADVANCED_BIT_DEPTHS and bit_depth:
		if target_format == "wav":
			_replace_argument(arguments, "-c:a", f"pcm_s{bit_depth}le")
		elif target_format == "aiff":
			_replace_argument(arguments, "-c:a", f"pcm_s{bit_depth}be")
	return arguments


def build_codec_arguments(
	target_format: str,
	quality: str,
	mp3_encoder: str,
	advanced_options: Mapping[str, Any] | None = None,
) -> list[str]:
	"""Return preset arguments with optional validated advanced overrides."""
	base_arguments = _build_base_codec_arguments(target_format, quality, mp3_encoder)
	return apply_advanced_codec_arguments(
		base_arguments,
		target_format,
		mp3_encoder,
		advanced_options,
	)


_DURATION_PATTERN = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_METADATA_ALIASES = {
	"album artist": "album_artist",
	"albumartist": "album_artist",
	"year": "date",
	"tracknumber": "track",
	"discnumber": "disc",
	"description": "comment",
}


def parse_duration(text: str) -> float | None:
	match = _DURATION_PATTERN.search(text or "")
	if not match:
		return None
	hours, minutes, seconds = match.groups()
	return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_progress_time(value: str) -> float | None:
	try:
		hours, minutes, seconds = value.strip().split(":", 2)
		return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
	except (TypeError, ValueError):
		return None


def _is_escaped(value: str, index: int) -> bool:
	backslashes = 0
	index -= 1
	while index >= 0 and value[index] == "\\":
		backslashes += 1
		index -= 1
	return bool(backslashes % 2)


def _split_ffmetadata_pair(line: str) -> tuple[str, str] | None:
	for index, character in enumerate(line):
		if character == "=" and not _is_escaped(line, index):
			return line[:index], line[index + 1 :]
	return None


def _unescape_ffmetadata(value: str) -> str:
	result: list[str] = []
	index = 0
	while index < len(value):
		if value[index] == "\\" and index + 1 < len(value):
			index += 1
		result.append(value[index])
		index += 1
	return "".join(result)


def parse_ffmetadata(text: str) -> dict[str, str]:
	"""Parse global tags from FFmpeg's ffmetadata output."""
	logical_lines: list[str] = []
	buffer = ""
	for raw_line in (text or "").splitlines():
		line = f"{buffer}{raw_line}"
		if line.endswith("\\") and not line.endswith("\\\\"):
			buffer = f"{line[:-1]}\n"
			continue
		logical_lines.append(line)
		buffer = ""
	if buffer:
		logical_lines.append(buffer)

	metadata: dict[str, str] = {}
	for line in logical_lines:
		if not line or line == ";FFMETADATA1" or line.startswith(("#", ";")):
			continue
		if line.startswith("["):
			break
		pair = _split_ffmetadata_pair(line)
		if pair is None:
			continue
		key, value = pair
		normalized_key = _unescape_ffmetadata(key).strip().lower()
		normalized_key = _METADATA_ALIASES.get(normalized_key, normalized_key)
		if normalized_key:
			metadata[normalized_key] = _unescape_ffmetadata(value)
	return metadata


def build_metadata_arguments(
	mode: str,
	selected_fields: Sequence[str],
	source_metadata: Mapping[str, str] | None = None,
) -> list[str]:
	if mode == "all":
		return ["-map_metadata", "0"]
	if mode == "none":
		return ["-map_metadata", "-1"]
	if mode != "selected":
		raise ValueError(f"Unsupported metadata mode: {mode}")
	arguments = ["-map_metadata", "-1"]
	source_metadata = source_metadata or {}
	for field_name in selected_fields:
		if field_name not in METADATA_FIELD_KEYS or field_name not in source_metadata:
			continue
		arguments.extend(("-metadata", f"{field_name}={source_metadata[field_name]}"))
	return arguments


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
			duration = self._probe_duration(source)
			if self._cancel_event.is_set():
				summary.canceled = True
				break
			source_metadata: dict[str, str] = {}
			if settings.metadata_mode == "selected" and settings.metadata_fields:
				source_metadata = self._probe_metadata(source)
				if self._cancel_event.is_set():
					summary.canceled = True
					break
			start_overall_fraction = (index - 1) / max(1, summary.total)
			_safe_callback(
				callbacks.on_progress,
				index,
				summary.total,
				source.name,
				0.0 if duration else None,
				start_overall_fraction,
				0.0,
				duration,
			)
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
				*build_metadata_arguments(
					settings.metadata_mode,
					settings.metadata_fields,
					source_metadata,
				),
				*build_codec_arguments(
					settings.target_format,
					settings.quality,
					settings.mp3_encoder,
					settings.advanced_options,
				),
				"-progress",
				"pipe:1",
				"-nostats",
				str(output),
			]

			def report_progress(processed_seconds: float) -> None:
				if duration and duration > 0:
					file_fraction: float | None = max(0.0, min(1.0, processed_seconds / duration))
				else:
					file_fraction = None
				overall_fraction = (
					(index - 1) + (file_fraction if file_fraction is not None else 0.0)
				) / max(1, summary.total)
				_safe_callback(
					callbacks.on_progress,
					index,
					summary.total,
					source.name,
					file_fraction,
					max(0.0, min(1.0, overall_fraction)),
					processed_seconds,
					duration,
				)

			return_code, error_message = self._run_process(command, report_progress)
			if self._cancel_event.is_set():
				summary.canceled = True
				self._remove_partial_output(output)
				break
			if return_code == 0 and output.is_file() and output.stat().st_size > 0:
				summary.succeeded += 1
				summary.outputs.append(str(output))
				_safe_callback(
					callbacks.on_progress,
					index,
					summary.total,
					source.name,
					1.0,
					index / max(1, summary.total),
					duration or 0.0,
					duration,
				)
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

	def _start_process(self, command: list[str], **kwargs) -> subprocess.Popen[str]:
		creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
		process = subprocess.Popen(
			command,
			stdin=subprocess.DEVNULL,
			text=True,
			encoding="utf-8",
			errors="replace",
			creationflags=creation_flags,
			**kwargs,
		)
		with self._process_lock:
			self._process = process
		if self._cancel_event.is_set() and process.poll() is None:
			try:
				process.terminate()
			except OSError:
				pass
		return process

	def _clear_process(self, process: subprocess.Popen[str]) -> None:
		with self._process_lock:
			if self._process is process:
				self._process = None

	def _capture_process(
		self,
		command: list[str],
		*,
		timeout: float = 15,
	) -> tuple[int, str, str]:
		process = self._start_process(
			command,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
		)
		try:
			try:
				stdout, stderr = process.communicate(timeout=timeout)
			except subprocess.TimeoutExpired:
				try:
					process.terminate()
					stdout, stderr = process.communicate(timeout=2)
				except (OSError, subprocess.TimeoutExpired):
					try:
						process.kill()
					except OSError:
						pass
					stdout, stderr = process.communicate()
			return int(process.returncode or 0), stdout or "", stderr or ""
		finally:
			self._clear_process(process)

	def _probe_duration(self, source: Path) -> float | None:
		if self._cancel_event.is_set():
			return None
		_command = [
			str(self.ffmpeg_path),
			"-nostdin",
			"-hide_banner",
			"-i",
			str(source),
		]
		_return_code, _stdout, stderr = self._capture_process(_command)
		return parse_duration(stderr)

	def _probe_metadata(self, source: Path) -> dict[str, str]:
		if self._cancel_event.is_set():
			return {}
		command = [
			str(self.ffmpeg_path),
			"-nostdin",
			"-hide_banner",
			"-loglevel",
			"error",
			"-i",
			str(source),
			"-map_metadata",
			"0",
			"-f",
			"ffmetadata",
			"-",
		]
		_return_code, stdout, _stderr = self._capture_process(command)
		return parse_ffmetadata(stdout)

	def _run_process(
		self,
		command: list[str],
		on_progress: Callable[[float], None] | None = None,
	) -> tuple[int, str]:
		process = self._start_process(
			command,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			bufsize=1,
		)
		error_lines: deque[str] = deque(maxlen=200)

		def read_errors() -> None:
			if process.stderr is None:
				return
			for line in process.stderr:
				error_lines.append(line)

		error_thread = threading.Thread(
			target=read_errors,
			name="EasyAudioConverterErrorReader",
			daemon=True,
		)
		error_thread.start()
		try:
			if process.stdout is not None:
				for raw_line in process.stdout:
					if self._cancel_event.is_set() and process.poll() is None:
						try:
							process.terminate()
						except OSError:
							pass
					key, separator, value = raw_line.strip().partition("=")
					if not separator or key != "out_time":
						continue
					seconds = parse_progress_time(value)
					if seconds is not None and on_progress is not None:
						try:
							on_progress(seconds)
						except Exception:
							pass
			process.wait()
			error_thread.join(timeout=2)
			return int(process.returncode or 0), "".join(error_lines)
		finally:
			self._clear_process(process)

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
