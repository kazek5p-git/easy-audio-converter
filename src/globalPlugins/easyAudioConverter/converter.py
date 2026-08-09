"""FFmpeg-backed conversion engine with no dependency on NVDA."""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import string
import subprocess
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from collections import OrderedDict, deque
from dataclasses import dataclass, field, replace
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
	"copyAudio",
	"aacM4a",
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
	# The actual copyAudio suffix is selected from the probed source codec.
	"copyAudio": ".mka",
	"aacM4a": ".m4a",
}

QUALITY_KEYS = ("economical", "standard", "high", "veryHigh")
MP3_ENCODER_KEYS = ("lame", "fraunhofer")
METADATA_MODE_KEYS = ("none", "all", "selected")
PARALLEL_JOB_COUNTS = (0, 1, 2, 4, 8, 16, 32)
MAX_PARALLEL_JOBS = PARALLEL_JOB_COUNTS[-1]
ORIGINAL_AUDIO_COPY_FORMAT = "copyAudio"
AAC_M4A_COPY_FORMAT = "aacM4a"
STREAM_COPY_FORMATS = frozenset(
	{ORIGINAL_AUDIO_COPY_FORMAT, AAC_M4A_COPY_FORMAT}
)
STREAM_COPY_CODEC_EXTENSIONS = {
	"aac": ".aac",
	"ac3": ".ac3",
	"ac4": ".ac4",
	"adpcm_ima_wav": ".wav",
	"adpcm_ms": ".wav",
	"alac": ".m4a",
	"amr_nb": ".amr",
	"amr_wb": ".awb",
	"dts": ".dts",
	"eac3": ".eac3",
	"flac": ".flac",
	"mlp": ".mlp",
	"mp1": ".mp1",
	"mp2": ".mp2",
	"mp3": ".mp3",
	"opus": ".opus",
	"speex": ".spx",
	"truehd": ".thd",
	"tta": ".tta",
	"vorbis": ".ogg",
	"wavpack": ".wv",
	"wmalossless": ".wma",
	"wmapro": ".wma",
	"wmav1": ".wma",
	"wmav2": ".wma",
	"wmavoice": ".wma",
}
LOUDNESS_PRESET_KEYS = ("off", "podcast", "music", "broadcast", "custom")
LOUDNESS_PRESETS = {
	"podcast": (-16.0, -1.5, 11.0),
	"music": (-14.0, -1.0, 11.0),
	"broadcast": (-23.0, -2.0, 7.0),
}
OUTPUT_NAME_FIELDS = (
	"source",
	"title",
	"artist",
	"album",
	"track",
	"disc",
	"index",
	"format",
)
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
	"track_total",
	"disc_total",
	"compilation",
	"bpm",
	"description",
	"grouping",
	"encoder",
	"isrc",
	"sort_artist",
	"sort_album",
	"sort_title",
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
MAX_METADATA_VALUE_LENGTH = 4096
MAX_METADATA_OVERRIDES = 32
ADVANCED_SAMPLE_RATES = (0, 8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200, 96000, 192000)
ADVANCED_CHANNEL_COUNTS = (0, 1, 2)
ADVANCED_BIT_DEPTHS = (0, 16, 24, 32)
FLAC_COMPRESSION_LEVELS = tuple(range(13))
# Profile natywnego enkodera FFmpeg i odpowiadająca mu składnia programu WavPack.
WAVPACK_COMPRESSION_PROFILES = (
	(0, "fast", "-f"),
	(1, "normal", ""),
	(2, "high", "-h"),
	(3, "veryHigh", "-hh"),
	(4, "veryHighExtra1", "-hhx1"),
	(5, "veryHighExtra2", "-hhx2"),
	(6, "veryHighExtra3", "-hhx3"),
	(7, "veryHighExtra4", "-hhx4"),
	(8, "veryHighExtra6", "-hhx6"),
)
MAX_SKIPPED_FILE_DETAILS = 500
MAX_PROBE_CACHE_ENTRIES = 128
MAX_OUTPUT_NAME_TEMPLATE_LENGTH = 240
MAX_SAFE_FILENAME_LENGTH = 180
ARTWORK_TARGET_FORMATS = frozenset({"mp3", "m4a", "alac", "flac", AAC_M4A_COPY_FORMAT})
LOSSY_TARGET_FORMATS = frozenset(
	{"mp3", "ogg", "opus", "m4a", "aac", "wma", "ac3", "eac3", "mp2", "amr", "amrwb"}
)
LOSSY_SOURCE_EXTENSIONS = frozenset(
	{
		".aac",
		".ac3",
		".amr",
		".awb",
		".eac3",
		".m4a",
		".m4b",
		".mp2",
		".mp3",
		".mp4",
		".oga",
		".ogg",
		".opus",
		".ra",
		".wma",
	}
)
LOSSY_CODEC_NAMES = frozenset(
	{
		"aac",
		"ac3",
		"amr_nb",
		"amr_wb",
		"eac3",
		"mp2",
		"mp3",
		"opus",
		"vorbis",
		"wmav1",
		"wmav2",
	}
)

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
		".wave",
		".webm",
		".wma",
		".wmv",
		".wv",
		".xm",
	}
)


class StreamCopySourceError(ValueError):
	"""A source cannot be used by the selected no-re-encoding mode."""

	def __init__(self, reason: str, message: str):
		super().__init__(message)
		self.reason = reason


def _normalized_codec_name(codec: str) -> str:
	parts = str(codec or "").strip().casefold().split(maxsplit=1)
	return parts[0].rstrip(",") if parts else ""


def output_extension_for(target_format: str, source_codec: str = "") -> str:
	"""Return the real output suffix, validating stream-copy compatibility."""
	if target_format not in FORMAT_KEYS:
		raise ValueError(f"Unsupported target format: {target_format}")
	codec = _normalized_codec_name(source_codec)
	if target_format == AAC_M4A_COPY_FORMAT:
		if not codec:
			raise StreamCopySourceError(
				"noAudioStream",
				"No readable audio stream was found",
			)
		if codec != "aac":
			raise StreamCopySourceError(
				"requiresAac",
				"AAC audio is required for remuxing to M4A without re-encoding",
			)
		return ".m4a"
	if target_format != ORIGINAL_AUDIO_COPY_FORMAT:
		return FORMAT_EXTENSIONS[target_format]
	if not codec:
		raise StreamCopySourceError(
			"noAudioStream",
			"No readable audio stream was found",
		)
	if re.fullmatch(r"pcm_(?:[suf]\d+)(?:le|be)?", codec):
		return ".aiff" if codec.endswith("be") else ".wav"
	return STREAM_COPY_CODEC_EXTENSIONS.get(codec, ".mka")


def output_format_name_for(target_format: str, source_codec: str = "") -> str:
	"""Return a useful value for the ``{format}`` filename-template field."""
	if target_format == ORIGINAL_AUDIO_COPY_FORMAT:
		return _normalized_codec_name(source_codec) or "audio"
	if target_format == AAC_M4A_COPY_FORMAT:
		return "m4a"
	return target_format


@dataclass(frozen=True)
class ConversionSettings:
	target_format: str = "mp3"
	quality: str = "high"
	mp3_encoder: str = "lame"
	same_folder: bool = True
	output_folder: str = ""
	include_subfolders: bool = True
	preserve_folder_structure: bool = True
	preserve_timestamps: bool = False
	replace_source_files: bool = False
	metadata_mode: str = "all"
	metadata_fields: tuple[str, ...] = DEFAULT_METADATA_FIELDS
	advanced_options: Mapping[str, Any] = field(default_factory=dict)
	output_name_template: str = "{source}"
	loudness_preset: str = "off"
	loudness_target_i: float = -16.0
	loudness_target_tp: float = -1.5
	loudness_target_lra: float = 11.0
	copy_artwork: bool = False
	copy_chapters: bool = True
	verify_output: bool = False
	show_preflight: bool = True
	# Zero oznacza automatyczny tryb dynamicznego dostosowania obciążenia.
	parallel_jobs: int = 0
	metadata_overrides: Mapping[str, str] = field(default_factory=dict)

	def validate(self) -> None:
		if self.target_format not in FORMAT_KEYS:
			raise ValueError(f"Unsupported target format: {self.target_format}")
		if self.quality not in QUALITY_KEYS:
			raise ValueError(f"Unsupported quality preset: {self.quality}")
		if self.mp3_encoder not in MP3_ENCODER_KEYS:
			raise ValueError(f"Unsupported MP3 encoder: {self.mp3_encoder}")
		try:
			parallel_jobs = int(self.parallel_jobs)
		except (TypeError, ValueError) as error:
			raise ValueError("Invalid parallel conversion worker count") from error
		if (
			isinstance(self.parallel_jobs, bool)
			or parallel_jobs != self.parallel_jobs
			or parallel_jobs not in PARALLEL_JOB_COUNTS
		):
			raise ValueError(
				f"Parallel conversion jobs must be between 0 and {MAX_PARALLEL_JOBS}"
			)
		if self.metadata_mode not in METADATA_MODE_KEYS:
			raise ValueError(f"Unsupported metadata mode: {self.metadata_mode}")
		if any(field_name not in METADATA_FIELD_KEYS for field_name in self.metadata_fields):
			raise ValueError("Unsupported metadata field")
		if not isinstance(self.metadata_overrides, Mapping):
			raise ValueError("Metadata overrides must be a mapping")
		if len(self.metadata_overrides) > MAX_METADATA_OVERRIDES:
			raise ValueError("Too many metadata overrides")
		for field_name, value in self.metadata_overrides.items():
			if field_name not in METADATA_FIELD_KEYS:
				raise ValueError("Unsupported metadata override field")
			if not isinstance(value, str):
				raise ValueError("Metadata override values must be text")
			if "\x00" in value:
				raise ValueError("Metadata override values cannot contain NUL bytes")
			if len(value) > MAX_METADATA_VALUE_LENGTH:
				raise ValueError("Metadata override value is too long")
		if not self.same_folder and not str(self.output_folder).strip():
			raise ValueError("A destination folder is required")
		validate_output_name_template(self.output_name_template)
		if self.loudness_preset not in LOUDNESS_PRESET_KEYS:
			raise ValueError(f"Unsupported loudness preset: {self.loudness_preset}")
		if not -70.0 <= float(self.loudness_target_i) <= -5.0:
			raise ValueError("The loudness target must be between -70 and -5 LUFS")
		if not -9.0 <= float(self.loudness_target_tp) <= 0.0:
			raise ValueError("The true peak target must be between -9 and 0 dBTP")
		if not 1.0 <= float(self.loudness_target_lra) <= 50.0:
			raise ValueError("The loudness range target must be between 1 and 50 LU")


@dataclass
class ConversionFailure:
	source_name: str
	message: str
	source_path: str = ""
	output_path: str = ""


@dataclass(frozen=True)
class ConversionSuccess:
	source_path: str
	output_path: str


@dataclass(frozen=True)
class SkippedFile:
	source_path: str
	reason: str


@dataclass
class ConversionSummary:
	total: int = 0
	succeeded: int = 0
	failed: int = 0
	ignored: int = 0
	canceled: bool = False
	stopped_after_current: bool = False
	outputs: list[str] = field(default_factory=list)
	failures: list[ConversionFailure] = field(default_factory=list)
	successes: list[ConversionSuccess] = field(default_factory=list)
	skipped_files: list[SkippedFile] = field(default_factory=list)
	timing: ConversionTiming = field(default_factory=lambda: ConversionTiming())


@dataclass(frozen=True)
class MediaInfo:
	"""Audio properties reported by FFmpeg for one selected file."""

	source_path: str
	container: str = ""
	codec: str = ""
	duration: float | None = None
	bitrate_kbps: int | None = None
	channels: str = ""
	sample_rate: int | None = None
	size_bytes: int = 0
	metadata: Mapping[str, str] = field(default_factory=dict)
	has_artwork: bool = False
	chapter_count: int = 0


@dataclass
class ConversionTiming:
	"""Pomiar etapów zadania, używany w raporcie diagnostycznym."""

	wall_seconds: float = 0.0
	probe_seconds: float = 0.0
	analysis_seconds: float = 0.0
	encode_seconds: float = 0.0
	finalize_seconds: float = 0.0
	probe_cache_hits: int = 0
	probe_cache_misses: int = 0

	def copy(self) -> "ConversionTiming":
		return ConversionTiming(
			wall_seconds=self.wall_seconds,
			probe_seconds=self.probe_seconds,
			analysis_seconds=self.analysis_seconds,
			encode_seconds=self.encode_seconds,
			finalize_seconds=self.finalize_seconds,
			probe_cache_hits=self.probe_cache_hits,
			probe_cache_misses=self.probe_cache_misses,
		)

	def add(self, other: "ConversionTiming") -> None:
		self.probe_seconds += other.probe_seconds
		self.analysis_seconds += other.analysis_seconds
		self.encode_seconds += other.encode_seconds
		self.finalize_seconds += other.finalize_seconds
		self.probe_cache_hits += other.probe_cache_hits
		self.probe_cache_misses += other.probe_cache_misses


@dataclass(frozen=True)
class _ProbeCacheEntry:
	signature: tuple[int, int]
	info: MediaInfo
	metadata_loaded: bool = False


_PROBE_CACHE: OrderedDict[str, _ProbeCacheEntry] = OrderedDict()
_PROBE_CACHE_LOCK = threading.RLock()


def _probe_file_signature(source: Path) -> tuple[int, int] | None:
	"""Return a cheap invalidation signature for one input file."""
	try:
		stat = source.stat()
	except OSError:
		return None
	return (int(stat.st_size), int(stat.st_mtime_ns))


@dataclass(frozen=True)
class ConversionPlanItem:
	source_path: str
	output_path: str
	duration: float | None
	input_size: int
	estimated_output_size: int | None
	metadata: Mapping[str, str] = field(default_factory=dict)
	# None oznacza, że szybka ścieżka nie wykonywała rozpoznania źródła.
	has_artwork: bool | None = False
	codec: str = ""


@dataclass(frozen=True)
class ConversionPlan:
	items: tuple[ConversionPlanItem, ...]
	ignored: int
	skipped_files: tuple[SkippedFile, ...]
	input_bytes: int
	estimated_output_bytes: int | None
	total_duration: float | None
	destination: str
	free_space_bytes: int | None
	lossy_to_lossy_count: int
	replace_source_files: bool = False
	timing: ConversionTiming = field(default_factory=ConversionTiming)

	@property
	def total(self) -> int:
		return len(self.items)


@dataclass(frozen=True)
class ConversionCallbacks:
	on_collected: Callable[[int, int], None] | None = None
	on_file_start: Callable[[int, int, str, str], None] | None = None
	on_progress: Callable[[int, int, str, float | None, float, float, float | None], None] | None = None
	on_file_done: Callable[[int, int, str, str], None] | None = None
	on_stage: Callable[[int, int, str, str], None] | None = None
	on_parallelism: Callable[[int, int, bool], None] | None = None


@dataclass(frozen=True)
class SystemResourceUsage:
	"""Ostatni zmierzony udział zasobów systemowych w procentach."""

	cpu_percent: float | None = None
	memory_percent: float | None = None


def _safe_callback(callback: Callable | None, *args) -> None:
	if callback is None:
		return
	try:
		callback(*args)
	except Exception:
		# A status callback must never stop a conversion.
		pass


def copy_source_file_timestamps(
	source: str | os.PathLike[str],
	destination: str | os.PathLike[str],
) -> None:
	"""Kopiuje datę utworzenia i modyfikacji źródła do gotowego wyniku."""
	source_path = Path(source)
	destination_path = Path(destination)
	if os.name != "nt":
		# Systemy POSIX zwykle nie pozwalają zmienić daty utworzenia. Zachowujemy
		# datę modyfikacji bez zmiany czasu ostatniego dostępu do wyniku.
		source_stat = source_path.stat()
		destination_stat = destination_path.stat()
		os.utime(
			destination_path,
			ns=(destination_stat.st_atime_ns, source_stat.st_mtime_ns),
		)
		return

	# NVDA działa w Windows, gdzie potrzebne jest SetFileTime, ponieważ os.utime
	# nie ustawia daty utworzenia wyświetlanej w Eksploratorze.
	import ctypes
	from ctypes import wintypes

	kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
	create_file = kernel32.CreateFileW
	create_file.argtypes = (
		wintypes.LPCWSTR,
		wintypes.DWORD,
		wintypes.DWORD,
		wintypes.LPVOID,
		wintypes.DWORD,
		wintypes.DWORD,
		wintypes.HANDLE,
	)
	create_file.restype = wintypes.HANDLE
	get_file_time = kernel32.GetFileTime
	get_file_time.argtypes = (
		wintypes.HANDLE,
		ctypes.POINTER(wintypes.FILETIME),
		ctypes.POINTER(wintypes.FILETIME),
		ctypes.POINTER(wintypes.FILETIME),
	)
	get_file_time.restype = wintypes.BOOL
	set_file_time = kernel32.SetFileTime
	set_file_time.argtypes = get_file_time.argtypes
	set_file_time.restype = wintypes.BOOL
	close_handle = kernel32.CloseHandle
	close_handle.argtypes = (wintypes.HANDLE,)
	close_handle.restype = wintypes.BOOL

	file_read_attributes = 0x0080
	file_write_attributes = 0x0100
	file_share_all = 0x0001 | 0x0002 | 0x0004
	open_existing = 3
	file_attribute_normal = 0x0080
	invalid_handle_value = ctypes.c_void_p(-1).value

	def open_attributes(path: Path, access: int):
		handle = create_file(
			str(path),
			access,
			file_share_all,
			None,
			open_existing,
			file_attribute_normal,
			None,
		)
		if handle == invalid_handle_value:
			error_code = ctypes.get_last_error()
			raise OSError(
				error_code,
				f"Could not open file attributes: {ctypes.FormatError(error_code).strip()}",
				str(path),
			)
		return handle

	source_handle = open_attributes(source_path, file_read_attributes)
	try:
		creation_time = wintypes.FILETIME()
		modification_time = wintypes.FILETIME()
		if not get_file_time(
			source_handle,
			ctypes.byref(creation_time),
			None,
			ctypes.byref(modification_time),
		):
			error_code = ctypes.get_last_error()
			raise OSError(
				error_code,
				f"Could not read source file dates: {ctypes.FormatError(error_code).strip()}",
				str(source_path),
			)
		destination_handle = open_attributes(destination_path, file_write_attributes)
		try:
			if not set_file_time(
				destination_handle,
				ctypes.byref(creation_time),
				None,
				ctypes.byref(modification_time),
			):
				error_code = ctypes.get_last_error()
				raise OSError(
					error_code,
					f"Could not preserve source file dates: {ctypes.FormatError(error_code).strip()}",
					str(destination_path),
				)
		finally:
			close_handle(destination_handle)
	finally:
		close_handle(source_handle)


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


def _collect_audio_files(
	paths: Iterable[str | os.PathLike[str]],
	*,
	recursive: bool = True,
	excluded_roots: Iterable[str | os.PathLike[str]] = (),
	folder_excluded_extensions: Iterable[str] = (),
) -> tuple[list[Path], int, list[SkippedFile]]:
	"""Collect supported files and bounded details about skipped inputs.

	Extensions in ``folder_excluded_extensions`` are skipped only when files
	are discovered inside a folder. A file selected explicitly is always kept,
	so an intentional same-format conversion remains possible.
	"""
	path_list = tuple(paths)
	excluded = tuple(Path(path) for path in excluded_roots if str(path).strip())
	folder_excluded = frozenset(
		f".{str(extension).lstrip('.').lower()}"
		for extension in folder_excluded_extensions
		if str(extension).strip().lstrip(".")
	)
	explicit_files: set[str] = set()
	for raw_path in path_list:
		candidate = Path(raw_path)
		try:
			if candidate.is_file():
				explicit_files.add(_normal_path(candidate))
		except OSError:
			continue
	files: list[Path] = []
	seen: set[str] = set()
	ignored = 0
	skipped_files: list[SkippedFile] = []

	def skip(candidate: Path, reason: str) -> None:
		nonlocal ignored
		ignored += 1
		if len(skipped_files) < MAX_SKIPPED_FILE_DETAILS:
			skipped_files.append(
				SkippedFile(
					source_path=str(candidate),
					reason=reason,
				)
			)

	def add_file(candidate: Path, *, from_folder: bool) -> None:
		if _is_below(candidate, excluded):
			return
		suffix = candidate.suffix.lower()
		if suffix not in AUDIO_EXTENSIONS:
			skip(candidate, "unsupported")
			return
		key = _normal_path(candidate)
		if key in seen:
			return
		if from_folder and suffix in folder_excluded and key not in explicit_files:
			seen.add(key)
			skip(candidate, "targetFormat")
			return
		seen.add(key)
		files.append(candidate)

	for raw_path in path_list:
		candidate = Path(raw_path)
		try:
			if candidate.is_file():
				add_file(candidate, from_folder=False)
				continue
			if not candidate.is_dir():
				skip(candidate, "unavailable")
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
						add_file(root_path / file_name, from_folder=True)
			else:
				for child in candidate.iterdir():
					if child.is_file():
						add_file(child, from_folder=True)
		except OSError:
			skip(candidate, "unavailable")

	files.sort(key=lambda path: _normal_path(path))
	return files, ignored, skipped_files


def collect_audio_files(
	paths: Iterable[str | os.PathLike[str]],
	*,
	recursive: bool = True,
	excluded_roots: Iterable[str | os.PathLike[str]] = (),
	folder_excluded_extensions: Iterable[str] = (),
) -> tuple[list[Path], int]:
	"""Collect supported files while preserving the original public result."""
	files, ignored, _skipped_files = _collect_audio_files(
		paths,
		recursive=recursive,
		excluded_roots=excluded_roots,
		folder_excluded_extensions=folder_excluded_extensions,
	)
	return files, ignored


def collect_audio_files_detailed(
	paths: Iterable[str | os.PathLike[str]],
	*,
	recursive: bool = True,
	excluded_roots: Iterable[str | os.PathLike[str]] = (),
	folder_excluded_extensions: Iterable[str] = (),
) -> tuple[list[Path], int, list[SkippedFile]]:
	"""Collect supported files with details suitable for the results window."""
	return _collect_audio_files(
		paths,
		recursive=recursive,
		excluded_roots=excluded_roots,
		folder_excluded_extensions=folder_excluded_extensions,
	)


def _build_base_codec_arguments(target_format: str, quality: str, mp3_encoder: str) -> list[str]:
	"""Return output codec arguments for a validated format and quality preset."""
	if target_format not in FORMAT_KEYS:
		raise ValueError(f"Unsupported target format: {target_format}")
	if quality not in QUALITY_KEYS:
		raise ValueError(f"Unsupported quality preset: {quality}")
	if mp3_encoder not in MP3_ENCODER_KEYS:
		raise ValueError(f"Unsupported MP3 encoder: {mp3_encoder}")
	index = QUALITY_KEYS.index(quality)

	if target_format in STREAM_COPY_FORMATS:
		return ["-c:a", "copy"]
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
	if target_format in STREAM_COPY_FORMATS:
		return arguments
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
			_replace_argument(
				arguments,
				"-compression_level",
				str(min(level, FLAC_COMPRESSION_LEVELS[-1])),
			)
		elif target_format == "ogg":
			_replace_argument(arguments, "-q:a", str(min(level, 10)))
		elif target_format == "opus":
			_replace_argument(arguments, "-compression_level", str(min(level, 10)))
		elif target_format == "wavpack":
			_replace_argument(
				arguments,
				"-compression_level",
				str(min(level, WAVPACK_COMPRESSION_PROFILES[-1][0])),
			)

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
_INPUT_FORMAT_PATTERN = re.compile(r"Input #\d+,\s*([^,]+(?:,[^,]+)*?),\s+from ", re.IGNORECASE)
_AUDIO_STREAM_PATTERN = re.compile(r"Audio:\s*([^,\s]+)(.*)", re.IGNORECASE)
_SAMPLE_RATE_PATTERN = re.compile(r"(\d+)\s+Hz", re.IGNORECASE)
_BITRATE_PATTERN = re.compile(r"(\d+)\s+kb/s", re.IGNORECASE)
_CHANNEL_WORDS = (
	"mono",
	"stereo",
	"2.1",
	"3.0",
	"4.0",
	"5.0",
	"5.1",
	"6.1",
	"7.1",
)
_LOUDNORM_JSON_PATTERN = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)
_METADATA_ALIASES = {
	"album artist": "album_artist",
	"albumartist": "album_artist",
	"year": "date",
	"tracknumber": "track",
	"track number": "track",
	"tracktotal": "track_total",
	"track total": "track_total",
	"discnumber": "disc",
	"disc number": "disc",
	"disctotal": "disc_total",
	"disc total": "disc_total",
	"description": "comment",
	"synopsis": "description",
	"encoded_by": "encoder",
	"encodedby": "encoder",
	"sortartist": "sort_artist",
	"sortalbum": "sort_album",
	"sorttitle": "sort_title",
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


def parse_media_info(
	text: str,
	*,
	source_path: str = "",
	size_bytes: int = 0,
	metadata: Mapping[str, str] | None = None,
) -> MediaInfo:
	"""Parse stable, user-facing audio properties from FFmpeg probe output."""
	text = text or ""
	container_match = _INPUT_FORMAT_PATTERN.search(text)
	container = container_match.group(1).strip() if container_match else ""
	audio_match = _AUDIO_STREAM_PATTERN.search(text)
	codec = ""
	stream_details = ""
	if audio_match:
		codec = audio_match.group(1).strip()
		stream_details = audio_match.group(2)
	sample_rate_match = _SAMPLE_RATE_PATTERN.search(stream_details)
	sample_rate = int(sample_rate_match.group(1)) if sample_rate_match else None
	bitrate_matches = _BITRATE_PATTERN.findall(stream_details)
	if not bitrate_matches:
		bitrate_matches = _BITRATE_PATTERN.findall(text)
	bitrate_kbps = int(bitrate_matches[-1]) if bitrate_matches else None
	details_casefold = stream_details.casefold()
	channels = next((word for word in _CHANNEL_WORDS if word in details_casefold), "")
	if not channels:
		channel_match = re.search(r"\b(\d+)\s+channels?\b", stream_details, re.IGNORECASE)
		if channel_match:
			channels = channel_match.group(1)
	has_artwork = "attached pic" in text.casefold()
	chapter_count = len(re.findall(r"^\s*Chapter #", text, re.MULTILINE))
	return MediaInfo(
		source_path=source_path,
		container=container,
		codec=codec,
		duration=parse_duration(text),
		bitrate_kbps=bitrate_kbps,
		channels=channels,
		sample_rate=sample_rate,
		size_bytes=max(0, int(size_bytes)),
		metadata=dict(metadata or {}),
		has_artwork=has_artwork,
		chapter_count=chapter_count,
	)


def parse_loudnorm_measurement(text: str) -> dict[str, float]:
	"""Extract and validate the JSON block emitted by FFmpeg's loudnorm filter."""
	for match in reversed(tuple(_LOUDNORM_JSON_PATTERN.finditer(text or ""))):
		try:
			raw = json.loads(match.group(0))
			values = {
				name: float(raw[name])
				for name in (
					"input_i",
					"input_tp",
					"input_lra",
					"input_thresh",
					"target_offset",
				)
			}
		except (KeyError, TypeError, ValueError, json.JSONDecodeError):
			continue
		if all(value == value and abs(value) != float("inf") for value in values.values()):
			return values
	raise ValueError("FFmpeg did not return valid loudness measurements")


def loudness_targets(settings: ConversionSettings) -> tuple[float, float, float] | None:
	"""Return the selected EBU R128 targets, or ``None`` when disabled."""
	if settings.loudness_preset == "off":
		return None
	if settings.loudness_preset in LOUDNESS_PRESETS:
		return LOUDNESS_PRESETS[settings.loudness_preset]
	return (
		float(settings.loudness_target_i),
		float(settings.loudness_target_tp),
		float(settings.loudness_target_lra),
	)


def build_loudnorm_filter(
	settings: ConversionSettings,
	measurement: Mapping[str, float] | None = None,
) -> str:
	"""Build first- or second-pass loudnorm arguments from validated settings."""
	targets = loudness_targets(settings)
	if targets is None:
		return ""
	target_i, target_tp, target_lra = targets
	options = [
		f"I={target_i:g}",
		f"TP={target_tp:g}",
		f"LRA={target_lra:g}",
	]
	if measurement is None:
		options.append("print_format=json")
	else:
		options.extend(
			(
				f"measured_I={float(measurement['input_i']):g}",
				f"measured_TP={float(measurement['input_tp']):g}",
				f"measured_LRA={float(measurement['input_lra']):g}",
				f"measured_thresh={float(measurement['input_thresh']):g}",
				f"offset={float(measurement['target_offset']):g}",
				"linear=true",
				"print_format=summary",
			)
		)
	return f"loudnorm={':'.join(options)}"


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
			unescaped_value = _unescape_ffmetadata(value)
			metadata[normalized_key] = unescaped_value
			if normalized_key in {"track", "disc"} and "/" in unescaped_value:
				_number, total = unescaped_value.split("/", 1)
				if total and f"{normalized_key}_total" not in metadata:
					metadata[f"{normalized_key}_total"] = total
	return metadata


def normalize_metadata_overrides(
	value: Mapping[str, Any] | None,
) -> dict[str, str]:
	"""Zwróć ograniczone i ujednolicone wartości tagów dla FFmpeg."""
	if not isinstance(value, Mapping):
		return {}
	normalized: dict[str, str] = {}
	for raw_key, raw_value in value.items():
		key = str(raw_key or "").strip().casefold()
		if key not in METADATA_FIELD_KEYS:
			key = _METADATA_ALIASES.get(key, key)
		if key not in METADATA_FIELD_KEYS or raw_value is None:
			continue
		text_value = str(raw_value)
		if not text_value:
			continue
		text_value = text_value.replace("\x00", "")[:MAX_METADATA_VALUE_LENGTH]
		if text_value:
			normalized[key] = text_value
	return {
		field_name: normalized[field_name]
		for field_name in METADATA_FIELD_KEYS
		if field_name in normalized
	}


def build_metadata_arguments(
	mode: str,
	selected_fields: Sequence[str],
	source_metadata: Mapping[str, str] | None = None,
	metadata_overrides: Mapping[str, Any] | None = None,
) -> list[str]:
	if mode not in METADATA_MODE_KEYS:
		raise ValueError(f"Unsupported metadata mode: {mode}")
	arguments = ["-map_metadata", "0" if mode == "all" else "-1"]
	source_metadata = source_metadata or {}
	overrides = normalize_metadata_overrides(metadata_overrides)
	if mode == "all":
		selected_values: dict[str, str] = {}
	else:
		selected_values = {}
		if mode == "selected":
			for field_name in selected_fields:
				if field_name not in METADATA_FIELD_KEYS:
					continue
				if field_name in source_metadata:
					selected_values[field_name] = str(source_metadata[field_name])
		for field_name, value in overrides.items():
			selected_values[field_name] = value
	if mode == "all":
		selected_values.update(overrides)
	for field_name in METADATA_FIELD_KEYS:
		if field_name in selected_values:
			arguments.extend(("-metadata", f"{field_name}={selected_values[field_name]}"))
	return arguments


def validate_output_name_template(template: str) -> None:
	"""Reject malformed or unbounded filename templates before conversion."""
	template = str(template or "")
	if not template.strip():
		raise ValueError("The output name template cannot be empty")
	if len(template) > MAX_OUTPUT_NAME_TEMPLATE_LENGTH:
		raise ValueError("The output name template is too long")
	try:
		parts = tuple(string.Formatter().parse(template))
	except ValueError as error:
		raise ValueError("The output name template contains unmatched braces") from error
	for _literal, field_name, format_spec, conversion in parts:
		if field_name is None:
			continue
		if field_name not in OUTPUT_NAME_FIELDS:
			raise ValueError(f"Unsupported output name field: {field_name}")
		if format_spec or conversion:
			raise ValueError("Output name fields do not support format specifiers")


def sanitize_windows_filename(
	value: str,
	*,
	fallback: str = "converted",
	max_length: int = MAX_SAFE_FILENAME_LENGTH,
) -> str:
	"""Return a safe filename stem without changing directories or extensions."""
	value = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", str(value or ""))
	value = re.sub(r"\s+", " ", value).strip().rstrip(". ")
	value = re.sub(r"_+", "_", value)
	if not value:
		value = fallback
	reserved_names = {
		"con",
		"prn",
		"aux",
		"nul",
		*(f"com{number}" for number in range(1, 10)),
		*(f"lpt{number}" for number in range(1, 10)),
	}
	if value.split(".", 1)[0].casefold() in reserved_names:
		value = f"_{value}"
	if len(value) > max(1, int(max_length)):
		value = value[: max(1, int(max_length))].rstrip(". ")
	return value or fallback


def render_output_name(
	template: str,
	source: Path,
	target_format: str,
	metadata: Mapping[str, str] | None = None,
	*,
	index: int = 1,
) -> str:
	"""Render a validated metadata-aware output filename stem."""
	validate_output_name_template(template)
	metadata = metadata or {}
	values = {
		"source": source.stem,
		"title": metadata.get("title") or source.stem,
		"artist": metadata.get("artist") or "",
		"album": metadata.get("album") or "",
		"track": metadata.get("track") or "",
		"disc": metadata.get("disc") or "",
		"index": str(max(1, int(index))),
		"format": target_format,
	}
	return sanitize_windows_filename(template.format_map(values), fallback=source.stem)


def make_unique_output_path(
	source: Path,
	output_directory: Path,
	target_extension: str,
	reserved: set[str] | None = None,
	*,
	base_name: str | None = None,
) -> Path:
	"""Choose a non-destructive output name, including same-format conversions."""
	reserved = reserved if reserved is not None else set()
	base_name = sanitize_windows_filename(base_name or source.stem, fallback=source.stem)
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


def _output_directory(
	source: Path,
	settings: ConversionSettings,
	source_root: Path | None,
) -> Path:
	if settings.same_folder:
		return source.parent
	output_directory = Path(settings.output_folder)
	if settings.preserve_folder_structure:
		output_directory /= _relative_parent(source, source_root)
	return output_directory


def _estimated_output_size(
	source_size: int,
	duration: float | None,
	settings: ConversionSettings,
	audio_bitrate_kbps: int | None = None,
) -> int | None:
	"""Estimate output bytes using the effective codec preset and duration."""
	source_size = max(0, int(source_size))
	if settings.target_format in STREAM_COPY_FORMATS:
		if duration and duration > 0 and audio_bitrate_kbps and audio_bitrate_kbps > 0:
			return max(
				1,
				int(duration * int(audio_bitrate_kbps) * 1000 / 8 * 1.02),
			)
		return None
	if not duration or duration <= 0:
		return source_size or None
	arguments = build_codec_arguments(
		settings.target_format,
		settings.quality,
		settings.mp3_encoder,
		settings.advanced_options,
	)
	try:
		bitrate_value = arguments[arguments.index("-b:a") + 1].lower().rstrip("k")
		bitrate_kbps = float(bitrate_value)
	except (ValueError, IndexError):
		bitrate_kbps = 0.0
	if bitrate_kbps > 0:
		return max(1, int(duration * bitrate_kbps * 1000 / 8 * 1.02))

	options = settings.advanced_options if settings.advanced_options.get("enabled", False) else {}
	sample_rate = _integer_option(options, "sampleRate") or 44100
	channels = _integer_option(options, "channels") or 2
	bit_depth = _integer_option(options, "bitDepth")
	quality_index = QUALITY_KEYS.index(settings.quality)
	if settings.target_format in {"wav", "aiff"}:
		if not bit_depth:
			bit_depth = (16, 16, 24, 32)[quality_index]
		return max(1, int(duration * sample_rate * channels * bit_depth / 8 + 65536))
	if settings.target_format in {"flac", "alac", "wavpack"}:
		pcm_depth = bit_depth or (16, 16, 24, 24)[quality_index]
		pcm_size = duration * sample_rate * channels * pcm_depth / 8
		return max(1, int(pcm_size * 0.62))
	return source_size or None


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


def _windows_system_times() -> tuple[int, int, int] | None:
	"""Zwróć czasy bezczynności, jądra i użytkownika systemu Windows."""
	if os.name != "nt":
		return None

	class _FileTime(ctypes.Structure):
		_fields_ = [
			("dwLowDateTime", ctypes.c_ulong),
			("dwHighDateTime", ctypes.c_ulong),
		]

	idle = _FileTime()
	kernel = _FileTime()
	user = _FileTime()
	try:
		if not ctypes.windll.kernel32.GetSystemTimes(
			ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
		):
			return None
	except (AttributeError, OSError):
		return None

	def value(file_time: _FileTime) -> int:
		return int(file_time.dwLowDateTime) | (int(file_time.dwHighDateTime) << 32)

	return value(idle), value(kernel), value(user)


def _windows_memory_percent() -> float | None:
	"""Zwróć procent użytej pamięci fizycznej systemu Windows."""
	if os.name != "nt":
		return None

	class _MemoryStatusEx(ctypes.Structure):
		_fields_ = [
			("dwLength", ctypes.c_ulong),
			("dwMemoryLoad", ctypes.c_ulong),
			("ullTotalPhys", ctypes.c_ulonglong),
			("ullAvailPhys", ctypes.c_ulonglong),
			("ullTotalPageFile", ctypes.c_ulonglong),
			("ullAvailPageFile", ctypes.c_ulonglong),
			("ullTotalVirtual", ctypes.c_ulonglong),
			("ullAvailVirtual", ctypes.c_ulonglong),
			("ullAvailExtendedVirtual", ctypes.c_ulonglong),
		]

	status = _MemoryStatusEx()
	status.dwLength = ctypes.sizeof(status)
	try:
		if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
			return None
	except (AttributeError, OSError):
		return None
	return max(0.0, min(100.0, float(status.dwMemoryLoad)))


def _portable_cpu_percent() -> float | None:
	"""Użyj średniego obciążenia jako awaryjnego pomiaru poza Windows."""
	try:
		load = float(os.getloadavg()[0])
		logical_cpus = max(1, int(os.cpu_count() or 1))
	except (AttributeError, OSError, TypeError, ValueError):
		return None
	return max(0.0, min(100.0, load * 100.0 / logical_cpus))


def _portable_memory_percent() -> float | None:
	"""Zwróć użycie pamięci z POSIX-owego sysconf, gdy jest dostępne."""
	try:
		total_pages = int(os.sysconf("SC_PHYS_PAGES"))
		available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
	except (AttributeError, OSError, TypeError, ValueError):
		return None
	if total_pages <= 0:
		return None
	used_pages = max(0, total_pages - available_pages)
	return max(0.0, min(100.0, used_pages * 100.0 / total_pages))


class _SystemResourceMonitor:
	"""Lekki monitor zasobów, niewymagający dodatkowych pakietów."""

	def __init__(self) -> None:
		self._previous_times = _windows_system_times()

	def sample(self) -> SystemResourceUsage:
		current_times = _windows_system_times()
		cpu_percent: float | None = None
		if current_times is not None and self._previous_times is not None:
			previous_idle, previous_kernel, previous_user = self._previous_times
			idle, kernel, user = current_times
			delta_idle = max(0, idle - previous_idle)
			delta_total = max(
				0,
				(kernel - previous_kernel) + (user - previous_user),
			)
			if delta_total:
				busy = max(0, delta_total - delta_idle)
				cpu_percent = max(0.0, min(100.0, busy * 100.0 / delta_total))
		self._previous_times = current_times
		if cpu_percent is None and os.name != "nt":
			cpu_percent = _portable_cpu_percent()
		memory_percent = (
			_windows_memory_percent()
			if os.name == "nt"
			else _portable_memory_percent()
		)
		return SystemResourceUsage(cpu_percent, memory_percent)


ADAPTIVE_CPU_HIGH_PERCENT = 88.0
ADAPTIVE_CPU_LOW_PERCENT = 55.0
ADAPTIVE_MEMORY_HIGH_PERCENT = 90.0
ADAPTIVE_MEMORY_LOW_PERCENT = 75.0
ADAPTIVE_HIGH_SAMPLES = 2
ADAPTIVE_LOW_SAMPLES = 3


class AdaptiveWorkerController:
	"""Dobieraj liczbę nowych pracowników na granicach plików.

	Aktywne zadania nigdy nie są przerywane przy zmniejszaniu limitu. Kontroler
	zmienia wyłącznie liczbę kolejnych plików dopuszczanych do wykonania, dzięki
	czemu konwersja pozostaje bezpieczna także przy wysokim obciążeniu.
	"""

	def __init__(self, file_count: int) -> None:
		file_count = max(1, int(file_count))
		# Automatyczny tryb nie przekracza ostrożnego limitu rdzeni fizycznych.
		# Ręczne wartości nadal pozwalają świadomie wybrać także wątki logiczne.
		self.maximum = min(
			MAX_PARALLEL_JOBS,
			file_count,
			recommended_parallel_jobs(file_count),
		)
		self.target = self.maximum
		self._high_samples = 0
		self._low_samples = 0

	@property
	def adaptive(self) -> bool:
		return True

	def update(self, usage: SystemResourceUsage) -> int:
		cpu = usage.cpu_percent
		memory = usage.memory_percent
		high_cpu = cpu is not None and cpu >= ADAPTIVE_CPU_HIGH_PERCENT
		high_memory = memory is not None and memory >= ADAPTIVE_MEMORY_HIGH_PERCENT
		low_cpu = cpu is not None and cpu <= ADAPTIVE_CPU_LOW_PERCENT
		low_memory = memory is None or memory <= ADAPTIVE_MEMORY_LOW_PERCENT
		if high_cpu or high_memory:
			self._high_samples += 1
			self._low_samples = 0
			if self._high_samples >= ADAPTIVE_HIGH_SAMPLES:
				self.target = max(1, self.target - 1)
				self._high_samples = 0
		elif low_cpu and low_memory:
			self._low_samples += 1
			self._high_samples = 0
			if self._low_samples >= ADAPTIVE_LOW_SAMPLES:
				self.target = min(self.maximum, self.target + 1)
				self._low_samples = 0
		else:
			self._high_samples = 0
			self._low_samples = 0
		return self.target


def recommended_parallel_jobs(file_count: int | None = None) -> int:
	"""Zwróć początkową liczbę pracowników dla trybu adaptacyjnego.

	Enkodery audio zwykle wykonują pracę jednym wątkiem na plik. Tryb
	automatyczny zaczyna od ostrożnego szacunku liczby rdzeni fizycznych na
	podstawie logicznej liczby procesorów, a następnie może zwiększać lub
	zmniejszać limit na granicach kolejnych plików.
	"""
	logical_cpus = max(1, int(os.cpu_count() or 1))
	if logical_cpus <= 2:
		workers = logical_cpus
	else:
		workers = max(1, logical_cpus // 2)
	workers = min(MAX_PARALLEL_JOBS, workers)
	if file_count is not None:
		workers = min(workers, max(1, int(file_count)))
	return max(1, workers)


def resolve_parallel_jobs(requested: int, file_count: int) -> int:
	"""Rozwiąż skonfigurowaną liczbę pracowników dla jednego zadania."""
	try:
		requested = int(requested)
		file_count = max(0, int(file_count))
	except (TypeError, ValueError) as error:
		raise ValueError("Invalid parallel conversion worker count") from error
	if requested not in PARALLEL_JOB_COUNTS:
		raise ValueError("Invalid parallel conversion worker count")
	if file_count <= 1:
		return 1
	if requested == 0:
		return recommended_parallel_jobs(file_count)
	return min(requested, file_count)


def _parallel_work_seconds(item: ConversionPlanItem) -> float:
	"""Oszacuj koszt pliku dla równoważenia kolejki.

	Czas z rozpoznania jest najlepszym wskaźnikiem. Dla szybkiej ścieżki,
	gdy czasu nie znamy, rozmiar jest przybliżeniem kosztu odczytu i zapisu.
	"""
	if item.duration is not None and float(item.duration) > 0:
		return float(item.duration)
	if item.input_size > 0:
		# 192 kb/s to neutralny przelicznik tylko do porządkowania kolejki.
		return max(0.001, float(item.input_size) / (192_000.0 / 8.0))
	return 0.001


def parallel_schedule_order(items: Sequence[ConversionPlanItem]) -> tuple[int, ...]:
	"""Zwróć indeksy od najdroższych plików do najtańszych.

	Najdłuższe pliki startują wcześniej (heurystyka LPT), dzięki czemu krótkie
	pliki nie czekają na koniec jednej przypadkowo uruchomionej długiej ścieżki.
	"""
	return tuple(
		sorted(
			range(len(items)),
			key=lambda index: _parallel_work_seconds(items[index]),
			reverse=True,
		)
	)


class Converter:
	"""Uruchom zadanie konwersji z bezpiecznym anulowaniem i równoległością."""

	def __init__(self, ffmpeg_path: str | os.PathLike[str]):
		self.ffmpeg_path = Path(ffmpeg_path)
		self._cancel_event = threading.Event()
		self._stop_after_current_event = threading.Event()
		self._process_lock = threading.Lock()
		self._process: subprocess.Popen[str] | None = None
		self._processes: set[subprocess.Popen[str]] = set()
		self._children_lock = threading.Lock()
		self._parallel_children: set[Converter] = set()
		self._probe_stats_lock = threading.Lock()
		self._probe_cache_hits = 0
		self._probe_cache_misses = 0

	@staticmethod
	def clear_probe_cache() -> None:
		"""Wyczyść współdzielony, ograniczony cache rozpoznania plików."""
		with _PROBE_CACHE_LOCK:
			_PROBE_CACHE.clear()

	def cancel(self) -> None:
		self._cancel_event.set()
		with self._process_lock:
			processes = tuple(self._processes)
			if self._process is not None and self._process not in processes:
				processes += (self._process,)
		with self._children_lock:
			children = tuple(self._parallel_children)
		for child in children:
			child.cancel()
		for process in processes:
			if process.poll() is None:
				try:
					process.terminate()
				except OSError:
					pass

	def _register_parallel_child(self, child: Converter) -> None:
		with self._children_lock:
			self._parallel_children.add(child)

	def _unregister_parallel_child(self, child: Converter) -> None:
		with self._children_lock:
			self._parallel_children.discard(child)

	def stop_after_current(self) -> None:
		"""Finish the active file, then stop this conversion job."""
		self._stop_after_current_event.set()

	@property
	def is_canceled(self) -> bool:
		return self._cancel_event.is_set()

	@staticmethod
	def _can_use_fast_path(settings: ConversionSettings) -> bool:
		"""Czy można pominąć rozpoznanie wejścia przed zwykłym kodowaniem."""
		return bool(
			not settings.show_preflight
			and settings.target_format not in STREAM_COPY_FORMATS
			and settings.loudness_preset == "off"
			and not Converter._requires_source_metadata(settings)
		)

	def _create_fast_plan(
		self,
		paths: Iterable[str | os.PathLike[str]],
		settings: ConversionSettings,
		*,
		source_root: str | os.PathLike[str] | None = None,
	) -> ConversionPlan:
		"""Zbuduj plan bez uruchamiania FFmpeg dla zwykłej konwersji.

		Szybka ścieżka jest używana wyłącznie wtedy, gdy format docelowy, nazwa
		pliku i ustawienia nie wymagają informacji z wejściowego strumienia.
		Postęp czasowy pozostaje nieznany, ale FFmpeg i tak otrzymuje pełny plik.
		"""
		path_list = tuple(paths)
		root = Path(source_root) if source_root else None
		files, ignored, skipped_files = self._collect_job_files(path_list, settings)
		reserved_outputs: set[str] = set()
		items: list[ConversionPlanItem] = []
		input_bytes = 0
		for index, source in enumerate(files, start=1):
			try:
				source_size = source.stat().st_size
			except OSError:
				source_size = 0
			output_directory = _output_directory(source, settings, root)
			base_name = render_output_name(
				settings.output_name_template,
				source,
				output_format_name_for(settings.target_format),
				{},
				index=index,
			)
			output = make_unique_output_path(
				source,
				output_directory,
				FORMAT_EXTENSIONS[settings.target_format],
				reserved_outputs,
				base_name=base_name,
			)
			items.append(
				ConversionPlanItem(
					source_path=str(source),
					output_path=str(output),
					duration=None,
					input_size=source_size,
					estimated_output_size=None,
					metadata={},
					has_artwork=None,
					codec="",
				)
			)
			input_bytes += source_size
		destination, free_space = self._plan_destination(items, settings)
		return ConversionPlan(
			items=tuple(items),
			ignored=ignored,
			skipped_files=tuple(skipped_files),
			input_bytes=input_bytes,
			estimated_output_bytes=None,
			total_duration=None,
			destination=destination,
			free_space_bytes=free_space,
			lossy_to_lossy_count=0,
			replace_source_files=settings.replace_source_files,
		)


	def create_plan(
		self,
		paths: Iterable[str | os.PathLike[str]],
		settings: ConversionSettings,
		*,
		source_root: str | os.PathLike[str] | None = None,
		callbacks: ConversionCallbacks | None = None,
	) -> ConversionPlan:
		"""Probe inputs and return a non-destructive conversion preview."""
		settings.validate()
		self._require_ffmpeg()
		path_list = tuple(paths)
		callbacks = callbacks or ConversionCallbacks()
		root = Path(source_root) if source_root else None
		files, ignored, skipped_files = self._collect_job_files(path_list, settings)
		_safe_callback(callbacks.on_collected, len(files), ignored)
		reserved_outputs: set[str] = set()
		items: list[ConversionPlanItem] = []
		input_bytes = 0
		output_estimates: list[int | None] = []
		durations: list[float | None] = []
		lossy_to_lossy_count = 0
		include_metadata = self._requires_source_metadata(settings)
		plan_started = time.monotonic()
		probe_seconds = 0.0
		cache_hits_before, cache_misses_before = self._probe_stats()

		for index, source in enumerate(files, start=1):
			if self._cancel_event.is_set():
				break
			_safe_callback(callbacks.on_stage, index, len(files), source.name, "planning")
			probe_started = time.monotonic()
			info = self._probe_media_info(source, include_metadata=include_metadata)
			probe_seconds += max(0.0, time.monotonic() - probe_started)
			try:
				target_extension = output_extension_for(
					settings.target_format,
					info.codec,
				)
			except StreamCopySourceError as error:
				ignored += 1
				if len(skipped_files) < MAX_SKIPPED_FILE_DETAILS:
					skipped_files.append(
						SkippedFile(
							source_path=str(source),
							reason=error.reason,
						)
					)
				continue
			try:
				source_size = source.stat().st_size
			except OSError:
				source_size = 0
			output_directory = _output_directory(source, settings, root)
			base_name = render_output_name(
				settings.output_name_template,
				source,
				output_format_name_for(settings.target_format, info.codec),
				info.metadata,
				index=index,
			)
			output = make_unique_output_path(
				source,
				output_directory,
				target_extension,
				reserved_outputs,
				base_name=base_name,
			)
			estimate = _estimated_output_size(
				source_size,
				info.duration,
				settings,
				info.bitrate_kbps,
			)
			items.append(
				ConversionPlanItem(
					source_path=str(source),
					output_path=str(output),
					duration=info.duration,
					input_size=source_size,
					estimated_output_size=estimate,
					metadata=dict(info.metadata),
					has_artwork=info.has_artwork,
					codec=info.codec,
				)
			)
			input_bytes += source_size
			output_estimates.append(estimate)
			durations.append(info.duration)
			source_is_lossy = (
				info.codec.casefold() in LOSSY_CODEC_NAMES
				if info.codec
				else source.suffix.casefold() in LOSSY_SOURCE_EXTENSIONS
			)
			if source_is_lossy and settings.target_format in LOSSY_TARGET_FORMATS:
				lossy_to_lossy_count += 1

		destination, free_space = self._plan_destination(items, settings)
		cache_hits_after, cache_misses_after = self._probe_stats()
		return ConversionPlan(
			items=tuple(items),
			ignored=ignored,
			skipped_files=tuple(skipped_files),
			input_bytes=input_bytes,
			estimated_output_bytes=(
				sum(value for value in output_estimates if value is not None)
				if output_estimates and all(value is not None for value in output_estimates)
				else None
			),
			total_duration=(
				sum(value for value in durations if value is not None)
				if durations and all(value is not None for value in durations)
				else None
			),
			destination=destination,
			free_space_bytes=free_space,
			lossy_to_lossy_count=lossy_to_lossy_count,
			replace_source_files=settings.replace_source_files,
			timing=ConversionTiming(
				wall_seconds=max(0.0, time.monotonic() - plan_started),
				probe_seconds=probe_seconds,
				probe_cache_hits=max(0, cache_hits_after - cache_hits_before),
				probe_cache_misses=max(0, cache_misses_after - cache_misses_before),
			),
		)

	def probe_media_info(self, source: str | os.PathLike[str]) -> MediaInfo:
		"""Return complete technical and metadata information for one file."""
		self._require_ffmpeg()
		path = Path(source)
		if not path.is_file():
			raise FileNotFoundError(str(path))
		return self._probe_media_info(path, include_metadata=True)

	def run(
		self,
		paths: Iterable[str | os.PathLike[str]],
		settings: ConversionSettings,
		*,
		source_root: str | os.PathLike[str] | None = None,
		callbacks: ConversionCallbacks | None = None,
		plan: ConversionPlan | None = None,
	) -> ConversionSummary:
		settings.validate()
		self._require_ffmpeg()
		path_list = tuple(paths)
		callbacks = callbacks or ConversionCallbacks()
		root = Path(source_root) if source_root else None
		run_started = time.monotonic()
		if plan is None and settings.target_format in STREAM_COPY_FORMATS:
			# Copy modes must probe before choosing a container and, for M4A,
			# must reject non-AAC sources even when preflight UI is disabled.
			plan = self.create_plan(
				path_list,
				settings,
				source_root=source_root,
			)
		elif plan is None and self._can_use_fast_path(settings):
			# Przy wyłączonym podglądzie zwykła konwersja nie potrzebuje drugiego
			# procesu FFmpeg do odczytania czasu i kodeka.
			plan = self._create_fast_plan(
				path_list,
				settings,
				source_root=source_root,
			)
		if plan is None:
			files, ignored, skipped_files = self._collect_job_files(path_list, settings)
			plan_items: Sequence[ConversionPlanItem] | None = None
		else:
			files = [Path(item.source_path) for item in plan.items]
			ignored = plan.ignored
			skipped_files = list(plan.skipped_files)
			plan_items = plan.items
		inline_probe_stats_before = self._probe_stats()
		if not files or self._cancel_event.is_set():
			summary = ConversionSummary(
				total=len(files),
				ignored=ignored,
				skipped_files=skipped_files,
				timing=(plan.timing.copy() if plan is not None else ConversionTiming()),
			)
			summary.timing.wall_seconds = (
				(plan.timing.wall_seconds if plan is not None else 0.0)
				+ max(0.0, time.monotonic() - run_started)
			)
			_safe_callback(callbacks.on_collected, summary.total, ignored)
			summary.canceled = self._cancel_event.is_set()
			return summary
		if resolve_parallel_jobs(settings.parallel_jobs, len(files)) > 1:
			return self._run_parallel(
				path_list,
				settings,
				source_root=source_root,
				callbacks=callbacks,
				plan=plan,
			)
		summary = ConversionSummary(
			total=len(files),
			ignored=ignored,
			skipped_files=skipped_files,
			timing=(plan.timing.copy() if plan is not None else ConversionTiming()),
		)
		_safe_callback(callbacks.on_collected, summary.total, ignored)

		reserved_outputs: set[str] = set()
		for index, source in enumerate(files, start=1):
			if self._cancel_event.is_set():
				summary.canceled = True
				break
			if self._stop_after_current_event.is_set() and index > 1:
				summary.stopped_after_current = True
				break
			planned_item = plan_items[index - 1] if plan_items is not None else None
			metadata: dict[str, str] = {}
			duration: float | None = None
			has_artwork = False
			source_codec = ""
			if planned_item is not None:
				metadata = dict(planned_item.metadata)
				duration = planned_item.duration
				has_artwork = planned_item.has_artwork
				source_codec = planned_item.codec
				output_directory = Path(planned_item.output_path).parent
				output = Path(planned_item.output_path)
				reserved_outputs.add(_normal_path(output))
			else:
				_safe_callback(callbacks.on_stage, index, summary.total, source.name, "probing")
				probe_started = time.monotonic()
				info = self._probe_media_info(
					source,
					include_metadata=self._requires_source_metadata(settings),
				)
				summary.timing.probe_seconds += max(0.0, time.monotonic() - probe_started)
				metadata = dict(info.metadata)
				duration = info.duration
				has_artwork = info.has_artwork
				source_codec = info.codec
				output_directory = _output_directory(source, settings, root)
				base_name = render_output_name(
					settings.output_name_template,
					source,
					output_format_name_for(settings.target_format, info.codec),
					metadata,
					index=index,
				)
				output = make_unique_output_path(
					source,
					output_directory,
					output_extension_for(settings.target_format, info.codec),
					reserved_outputs,
					base_name=base_name,
				)
			try:
				output_directory.mkdir(parents=True, exist_ok=True)
			except OSError as error:
				self._record_failure(summary, source, str(error))
				if self._finish_at_boundary(summary):
					break
				continue

			_safe_callback(callbacks.on_file_start, index, summary.total, source.name, output.name)
			if self._cancel_event.is_set():
				summary.canceled = True
				break
			loudnorm_filter = ""
			if (
				settings.target_format not in STREAM_COPY_FORMATS
				and settings.loudness_preset != "off"
			):
				_safe_callback(
					callbacks.on_stage,
					index,
					summary.total,
					source.name,
					"analyzingLoudness",
				)
				analysis_started = time.monotonic()
				try:
					measurement = self._analyze_loudness(source, settings)
					loudnorm_filter = (
						build_loudnorm_filter(settings, measurement)
						if measurement
						else build_loudnorm_filter(settings)
					)
				except (OSError, ValueError) as error:
					if self._cancel_event.is_set():
						summary.canceled = True
						break
					self._record_failure(summary, source, str(error))
					if self._finish_at_boundary(summary):
						break
					continue
				finally:
					summary.timing.analysis_seconds += max(
						0.0,
						time.monotonic() - analysis_started,
					)
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
			_safe_callback(callbacks.on_stage, index, summary.total, source.name, "converting")
			stream_arguments = self._stream_mapping_arguments(
				settings,
				has_artwork=has_artwork,
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
				# Pozwól każdemu kodekowi i filtrowi FFmpeg dobrać liczbę wątków.
				"-threads",
				"0",
				*stream_arguments,
				*self._metadata_arguments(settings, metadata),
				"-map_chapters",
				(
					"0"
					if (
						settings.copy_chapters
						and settings.target_format != ORIGINAL_AUDIO_COPY_FORMAT
					)
					else "-1"
				),
				*(["-af", loudnorm_filter] if loudnorm_filter else []),
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

			encode_started = time.monotonic()
			return_code, error_message = self._run_process(command, report_progress)
			summary.timing.encode_seconds += max(0.0, time.monotonic() - encode_started)
			finalize_started = time.monotonic()

			def record_finalize_time() -> None:
				summary.timing.finalize_seconds += max(
					0.0,
					time.monotonic() - finalize_started,
				)

			if self._cancel_event.is_set():
				summary.canceled = True
				self._remove_partial_output(output)
				record_finalize_time()
				break
			valid_output = False
			if return_code == 0:
				try:
					valid_output = output.is_file() and output.stat().st_size > 0
				except OSError as error:
					error_message = str(error)
			if valid_output:
				if settings.verify_output:
					_safe_callback(
						callbacks.on_stage,
						index,
						summary.total,
						source.name,
						"verifying",
					)
					verified, verification_error = self._verify_output(
						output,
						duration,
						expected_codec=(
							source_codec
							if settings.target_format in STREAM_COPY_FORMATS
							else ""
						),
					)
					if self._cancel_event.is_set():
						summary.canceled = True
						self._remove_partial_output(output)
						record_finalize_time()
						break
					if not verified:
						self._remove_partial_output(output)
						self._record_failure(summary, source, verification_error)
						record_finalize_time()
						if self._finish_at_boundary(summary):
							break
						continue
				if settings.preserve_timestamps:
					try:
						copy_source_file_timestamps(source, output)
					except OSError as error:
						self._remove_partial_output(output)
						self._record_failure(
							summary,
							source,
							f"Could not preserve source file dates: {error}",
						)
						record_finalize_time()
						if self._finish_at_boundary(summary):
							break
						continue
				if settings.replace_source_files:
					if self._cancel_event.is_set():
						summary.canceled = True
						self._remove_partial_output(output)
						record_finalize_time()
						break
					try:
						self._remove_source_file(source)
					except OSError as error:
						self._record_failure(
							summary,
							source,
							f"Could not remove source file after successful conversion: {error}",
							output=output,
						)
						record_finalize_time()
						if self._finish_at_boundary(summary):
							break
						continue
				summary.succeeded += 1
				summary.outputs.append(str(output))
				summary.successes.append(
					ConversionSuccess(
						source_path=str(source),
						output_path=str(output),
					)
				)
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
				record_finalize_time()
				if self._finish_at_boundary(summary):
					break
				continue
			self._remove_partial_output(output)
			self._record_failure(
				summary,
				source,
				_redact_ffmpeg_error(error_message, source, output),
			)
			record_finalize_time()
			if self._finish_at_boundary(summary):
				break
		summary.timing.wall_seconds = (
			(plan.timing.wall_seconds if plan is not None else 0.0)
			+ max(0.0, time.monotonic() - run_started)
		)
		if plan_items is None:
			cache_hits_after, cache_misses_after = self._probe_stats()
			summary.timing.probe_cache_hits += max(
				0,
				cache_hits_after - inline_probe_stats_before[0],
			)
			summary.timing.probe_cache_misses += max(
				0,
				cache_misses_after - inline_probe_stats_before[1],
			)
		return summary

	def _run_parallel(
		self,
		path_list: Sequence[str | os.PathLike[str]],
		settings: ConversionSettings,
		*,
		source_root: str | os.PathLike[str] | None,
		callbacks: ConversionCallbacks,
		plan: ConversionPlan | None,
	) -> ConversionSummary:
		"""Konwertuj niezależne pliki równolegle z limitem pracowników FFmpeg.

		Przed startem pracowników wymagany jest kompletny plan. Dzięki temu
		unikalne nazwy wyników są rezerwowane tylko raz i równoległe pliki nie
		wybierają tego samego celu. Każdy pracownik ma własny obiekt Converter,
		ale współdzieli z rodzicem zdarzenie anulowania, więc anulowanie kończy
		każdy aktywny proces potomny FFmpeg.
		"""
		if plan is None:
			if self._can_use_fast_path(settings):
				plan = self._create_fast_plan(
					path_list,
					settings,
					source_root=source_root,
				)
			else:
				plan = self.create_plan(
					path_list,
					settings,
					source_root=source_root,
					callbacks=ConversionCallbacks(on_stage=callbacks.on_stage),
				)
		plan_timing = plan.timing.copy()
		conversion_started = time.monotonic()
		items = tuple(plan.items)
		summary = ConversionSummary(
			total=len(items),
			ignored=plan.ignored,
			skipped_files=list(plan.skipped_files),
			timing=plan_timing,
		)
		_safe_callback(callbacks.on_collected, summary.total, summary.ignored)
		if not items:
			summary.canceled = self._cancel_event.is_set()
			summary.timing.wall_seconds = plan_timing.wall_seconds + max(
				0.0,
				time.monotonic() - conversion_started,
			)
			return summary
		if self._cancel_event.is_set():
			summary.canceled = True
			summary.timing.wall_seconds = plan_timing.wall_seconds + max(
				0.0,
				time.monotonic() - conversion_started,
			)
			return summary

		adaptive_controller = (
			AdaptiveWorkerController(len(items))
			if settings.parallel_jobs == 0
			else None
		)
		worker_count = (
			adaptive_controller.target
			if adaptive_controller is not None
			else resolve_parallel_jobs(settings.parallel_jobs, len(items))
		)
		worker_limit = (
			adaptive_controller.maximum
			if adaptive_controller is not None
			else worker_count
		)
		resource_monitor = _SystemResourceMonitor() if adaptive_controller else None
		progress_values = [0.0] * len(items)
		progress_weights = [max(0.001, _parallel_work_seconds(item)) for item in items]
		total_progress_weight = sum(progress_weights) or 1.0
		progress_lock = threading.Lock()

		def convert_one(
			index: int,
			item: ConversionPlanItem,
		) -> ConversionSummary | None:
			# Po zatrzymaniu na granicy nie uruchamiaj nowej pracy. Pliki już
			# uruchomione mogą bezpiecznie się zakończyć.
			if self._cancel_event.is_set() or self._stop_after_current_event.is_set():
				return None
			try:
				child = type(self)(self.ffmpeg_path)
			except TypeError:
				# Zachowaj obsługę niestandardowych podklas testowych i integracyjnych,
				# nawet gdy ich konstruktor wymaga dodatkowych argumentów.
				child = Converter(self.ffmpeg_path)
			# Wspólne zdarzenie pozwala rodzicowi natychmiast anulować zadanie.
			child._cancel_event = self._cancel_event
			child._stop_after_current_event = self._stop_after_current_event
			self._register_parallel_child(child)
			child_settings = replace(settings, parallel_jobs=1)
			single_plan = ConversionPlan(
				items=(item,),
				ignored=0,
				skipped_files=(),
				input_bytes=item.input_size,
				estimated_output_bytes=item.estimated_output_size,
				total_duration=item.duration,
				destination=str(Path(item.output_path).parent),
				free_space_bytes=plan.free_space_bytes,
				lossy_to_lossy_count=0,
				replace_source_files=settings.replace_source_files,
			)

			def on_file_start(
				_child_index: int,
				_child_total: int,
				source_name: str,
				output_name: str,
			) -> None:
				_safe_callback(
					callbacks.on_file_start,
					index,
					len(items),
					source_name,
					output_name,
				)

			def on_stage(
				_child_index: int,
				_child_total: int,
				source_name: str,
				stage: str,
			) -> None:
				_safe_callback(
					callbacks.on_stage,
					index,
					len(items),
					source_name,
					stage,
				)

			def on_progress(
				_child_index: int,
				_child_total: int,
				source_name: str,
				file_fraction: float | None,
				_child_overall_fraction: float,
				processed_seconds: float,
				duration: float | None,
			) -> None:
				fraction = file_fraction if file_fraction is not None else 0.0
				with progress_lock:
					progress_values[index - 1] = max(
						progress_values[index - 1],
						max(0.0, min(1.0, fraction)),
					)
					overall_fraction = sum(
						weight * value
						for weight, value in zip(progress_weights, progress_values)
					) / total_progress_weight
				_safe_callback(
					callbacks.on_progress,
					index,
					len(items),
					source_name,
					file_fraction,
					overall_fraction,
					processed_seconds,
					duration,
				)

			def on_file_done(
				_child_index: int,
				_child_total: int,
				source_name: str,
				output_name: str,
			) -> None:
				_safe_callback(
					callbacks.on_file_done,
					index,
					len(items),
					source_name,
					output_name,
				)

			try:
				return child.run(
					[item.source_path],
					child_settings,
					source_root=source_root,
					callbacks=ConversionCallbacks(
						on_file_start=on_file_start,
						on_progress=on_progress,
						on_file_done=on_file_done,
						on_stage=on_stage,
					),
					plan=single_plan,
				)
			except Exception as error:
				return ConversionSummary(
					total=1,
					failed=1,
					failures=[
						ConversionFailure(
							Path(item.source_path).name,
							str(error),
							item.source_path,
							item.output_path,
						)
					],
				)
			finally:
				self._unregister_parallel_child(child)

		results: list[ConversionSummary | None] = [None] * len(items)
		schedule = parallel_schedule_order(items)
		with ThreadPoolExecutor(
			max_workers=worker_limit,
			thread_name_prefix="EasyAudioConverterFile",
		) as executor:
			next_position = 0
			active: dict[Any, int] = {}

			def submit_next() -> None:
				nonlocal next_position
				while (
					next_position < len(schedule)
					and len(active) < worker_count
					and not self._cancel_event.is_set()
					and not self._stop_after_current_event.is_set()
				):
					index = schedule[next_position]
					next_position += 1
					active[executor.submit(convert_one, index + 1, items[index])] = index

			submit_next()
			_safe_callback(
				callbacks.on_parallelism,
				len(active),
				worker_count,
				adaptive_controller is not None,
			)
			while active:
				done, _pending = wait(
					tuple(active),
					return_when=FIRST_COMPLETED,
				)
				for future in done:
					index = active.pop(future)
					results[index] = future.result()
				if adaptive_controller is not None and resource_monitor is not None:
					worker_count = adaptive_controller.update(resource_monitor.sample())
				submit_next()
				_safe_callback(
					callbacks.on_parallelism,
					len(active),
					worker_count,
					adaptive_controller is not None,
				)

		for result in results:
			if result is None:
				continue
			summary.succeeded += result.succeeded
			summary.failed += result.failed
			summary.outputs.extend(result.outputs)
			summary.failures.extend(result.failures)
			summary.successes.extend(result.successes)
			summary.canceled = summary.canceled or result.canceled
			summary.stopped_after_current = (
				summary.stopped_after_current or result.stopped_after_current
			)
			summary.timing.add(result.timing)
		if self._cancel_event.is_set():
			summary.canceled = True
		elif self._stop_after_current_event.is_set():
			summary.stopped_after_current = True
		summary.timing.wall_seconds = plan_timing.wall_seconds + max(
			0.0,
			time.monotonic() - conversion_started,
		)
		return summary

	def _require_ffmpeg(self) -> None:
		if not self.ffmpeg_path.is_file():
			raise FileNotFoundError("The bundled FFmpeg executable is missing")

	def _collect_job_files(
		self,
		path_list: Sequence[str | os.PathLike[str]],
		settings: ConversionSettings,
	) -> tuple[list[Path], int, list[SkippedFile]]:
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
		return collect_audio_files_detailed(
			path_list,
			recursive=settings.include_subfolders,
			excluded_roots=excluded_roots,
			folder_excluded_extensions=(
				()
				if settings.target_format == ORIGINAL_AUDIO_COPY_FORMAT
				else (FORMAT_EXTENSIONS[settings.target_format],)
			),
		)

	@staticmethod
	def _requires_source_metadata(settings: ConversionSettings) -> bool:
		if (
			settings.target_format != ORIGINAL_AUDIO_COPY_FORMAT
			and settings.metadata_mode == "selected"
			and settings.metadata_fields
		):
			return True
		return any(
			f"{{{field_name}}}" in settings.output_name_template
			for field_name in ("title", "artist", "album", "track", "disc")
		)

	@staticmethod
	def _metadata_arguments(
		settings: ConversionSettings,
		metadata: Mapping[str, str],
	) -> list[str]:
		if (
			settings.target_format == ORIGINAL_AUDIO_COPY_FORMAT
			and not settings.metadata_overrides
		):
			return ["-map_metadata", "-1"]
		return build_metadata_arguments(
			(
				"none"
				if settings.target_format == ORIGINAL_AUDIO_COPY_FORMAT
				else settings.metadata_mode
			),
			settings.metadata_fields,
			metadata,
			settings.metadata_overrides,
		)

	@staticmethod
	def _record_failure(
		summary: ConversionSummary,
		source: Path,
		message: str,
		*,
		output: Path | None = None,
	) -> None:
		summary.failed += 1
		summary.failures.append(
			ConversionFailure(
				source.name,
				message,
				str(source),
				str(output) if output is not None else "",
			)
		)

	def _finish_at_boundary(self, summary: ConversionSummary) -> bool:
		if not self._stop_after_current_event.is_set():
			return False
		summary.stopped_after_current = True
		return True

	@staticmethod
	def _stream_mapping_arguments(
		settings: ConversionSettings,
		*,
		has_artwork: bool | None,
	) -> list[str]:
		audio_stream = "0:a:0" if settings.target_format in STREAM_COPY_FORMATS else "0:a:0?"
		arguments = ["-map", audio_stream, "-sn", "-dn"]
		# None oznacza brak rozpoznania. Opcjonalne mapowanie jest bezpieczne,
		# więc szybka ścieżka nie musi uruchamiać dodatkowego FFmpeg tylko po to,
		# aby sprawdzić, czy okładka istnieje.
		if (
			settings.copy_artwork
			and has_artwork is not False
			and settings.target_format in ARTWORK_TARGET_FORMATS
		):
			arguments.extend(
				(
					"-map",
					"0:v:disp:attached_pic?",
					"-c:v",
					"copy",
					"-disposition:v:0",
					"attached_pic",
				)
			)
		else:
			arguments.append("-vn")
		return arguments

	@staticmethod
	def _plan_destination(
		items: Sequence[ConversionPlanItem],
		settings: ConversionSettings,
	) -> tuple[str, int | None]:
		if not items:
			return (settings.output_folder if not settings.same_folder else ""), None
		if settings.same_folder:
			directories = tuple(dict.fromkeys(str(Path(item.output_path).parent) for item in items))
			if len(directories) == 1:
				destination = directories[0]
			else:
				try:
					destination = os.path.commonpath(directories)
				except ValueError:
					destination = directories[0]
		else:
			destination = settings.output_folder
		probe = Path(destination)
		while not probe.exists() and probe.parent != probe:
			probe = probe.parent
		try:
			return destination, shutil.disk_usage(probe).free
		except OSError:
			return destination, None

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
			self._processes.add(process)
			self._process = process
		if self._cancel_event.is_set() and process.poll() is None:
			try:
				process.terminate()
			except OSError:
				pass
		return process

	def _clear_process(self, process: subprocess.Popen[str]) -> None:
		with self._process_lock:
			self._processes.discard(process)
			if self._process is process:
				self._process = next(iter(self._processes), None)

	def _capture_process(
		self,
		command: list[str],
		*,
		timeout: float | None = 15,
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

	def _record_probe_hit(self) -> None:
		with self._probe_stats_lock:
			self._probe_cache_hits += 1

	def _record_probe_miss(self) -> None:
		with self._probe_stats_lock:
			self._probe_cache_misses += 1

	def _probe_stats(self) -> tuple[int, int]:
		with self._probe_stats_lock:
			return self._probe_cache_hits, self._probe_cache_misses

	def _probe_media_info(self, source: Path, *, include_metadata: bool) -> MediaInfo:
		if self._cancel_event.is_set():
			return MediaInfo(source_path=str(source))
		signature = _probe_file_signature(source)
		cache_key = _normal_path(source)
		cached: _ProbeCacheEntry | None = None
		if signature is not None:
			with _PROBE_CACHE_LOCK:
				candidate = _PROBE_CACHE.get(cache_key)
				if candidate is not None and candidate.signature == signature:
					cached = candidate
					_PROBE_CACHE.move_to_end(cache_key)
			if cached is not None:
				if not include_metadata or cached.metadata_loaded:
					self._record_probe_hit()
					return cached.info
				# Informacje techniczne są nadal aktualne; dociągamy tylko tagi.
				metadata = self._probe_metadata(source)
				info = replace(cached.info, metadata=metadata)
				with _PROBE_CACHE_LOCK:
					_PROBE_CACHE[cache_key] = _ProbeCacheEntry(
						signature=signature,
						info=info,
						metadata_loaded=True,
					)
					_PROBE_CACHE.move_to_end(cache_key)
				self._record_probe_hit()
				return info
		self._record_probe_miss()
		command = [
			str(self.ffmpeg_path),
			"-nostdin",
			"-hide_banner",
			"-i",
			str(source),
		]
		_return_code, _stdout, stderr = self._capture_process(command)
		metadata = self._probe_metadata(source) if include_metadata else {}
		try:
			size_bytes = source.stat().st_size
		except OSError:
			size_bytes = 0
		info = parse_media_info(
			stderr,
			source_path=str(source),
			size_bytes=size_bytes,
			metadata=metadata,
		)
		if signature is not None and not self._cancel_event.is_set():
			with _PROBE_CACHE_LOCK:
				_PROBE_CACHE[cache_key] = _ProbeCacheEntry(
					signature=signature,
					info=info,
					metadata_loaded=include_metadata,
				)
				_PROBE_CACHE.move_to_end(cache_key)
				while len(_PROBE_CACHE) > MAX_PROBE_CACHE_ENTRIES:
					_PROBE_CACHE.popitem(last=False)
		return info

	def _probe_duration(self, source: Path) -> float | None:
		return self._probe_media_info(source, include_metadata=False).duration

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

	def _analyze_loudness(
		self,
		source: Path,
		settings: ConversionSettings,
	) -> dict[str, float]:
		first_pass_filter = build_loudnorm_filter(settings)
		if not first_pass_filter:
			return {}
		command = [
			str(self.ffmpeg_path),
			"-nostdin",
			"-hide_banner",
			"-loglevel",
			"info",
			"-i",
			str(source),
			"-map",
			"0:a:0?",
			"-vn",
			"-sn",
			"-dn",
			"-af",
			first_pass_filter,
			"-f",
			"null",
			os.devnull,
		]
		return_code, _stdout, stderr = self._capture_process(command, timeout=None)
		if self._cancel_event.is_set():
			raise OSError("Loudness analysis was canceled")
		if return_code != 0:
			raise OSError(_redact_ffmpeg_error(stderr, source, Path(os.devnull)))
		try:
			return parse_loudnorm_measurement(stderr)
		except ValueError:
			if re.search(r'"input_i"\s*:\s*"-inf"', stderr, re.IGNORECASE):
				# Silence cannot produce finite first-pass measurements.
				# FFmpeg's dynamic loudnorm mode remains safe and preserves silence.
				return {}
			raise

	def _verify_output(
		self,
		output: Path,
		source_duration: float | None,
		*,
		expected_codec: str = "",
	) -> tuple[bool, str]:
		command = [
			str(self.ffmpeg_path),
			"-nostdin",
			"-hide_banner",
			"-loglevel",
			"error",
			"-xerror",
			"-i",
			str(output),
			"-map",
			"0:a:0?",
			"-f",
			"null",
			os.devnull,
		]
		return_code, _stdout, stderr = self._capture_process(command, timeout=None)
		if return_code != 0:
			return False, _redact_ffmpeg_error(stderr, output, Path(os.devnull))
		output_info = self._probe_media_info(output, include_metadata=False)
		if (
			expected_codec
			and _normalized_codec_name(output_info.codec)
			!= _normalized_codec_name(expected_codec)
		):
			return (
				False,
				(
					"Output audio codec differs from the copied source stream "
					f"({output_info.codec or 'unknown'} versus {expected_codec})"
				),
			)
		output_duration = output_info.duration
		if source_duration and output_duration is not None:
			tolerance = max(2.0, source_duration * 0.02)
			if abs(output_duration - source_duration) > tolerance:
				return (
					False,
					(
						"Output duration differs from the source "
						f"({output_duration:.2f} versus {source_duration:.2f} seconds)"
					),
				)
		return True, ""

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

	@staticmethod
	def _remove_source_file(source: Path) -> None:
		source.unlink()


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
