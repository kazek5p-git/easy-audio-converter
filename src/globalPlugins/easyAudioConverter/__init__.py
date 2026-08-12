"""Easy Audio Converter global plug-in for NVDA."""

from __future__ import annotations

import ctypes
import json
import os
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping

import addonHandler
import api
import config
import globalPluginHandler
import gui
import nvwave
import ui
import wx
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel
from logHandler import log
from scriptHandler import script
from wx.lib import scrolledpanel

try:
	import globalVars
except Exception:
	globalVars = None

from .converter import (
	AAC_M4A_COPY_FORMAT,
	ADVANCED_BIT_DEPTHS,
	ADVANCED_CHANNEL_COUNTS,
	ADVANCED_SAMPLE_RATES,
	DEFAULT_METADATA_FIELDS,
	FLAC_COMPRESSION_LEVELS,
	FORMAT_EXTENSIONS,
	FORMAT_KEYS,
	LOUDNESS_PRESET_KEYS,
	METADATA_FIELD_KEYS,
	METADATA_MODE_KEYS,
	MP3_ENCODER_KEYS,
	normalize_metadata_overrides,
	PARALLEL_JOB_COUNTS,
	ORIGINAL_AUDIO_COPY_FORMAT,
	QUALITY_KEYS,
	STREAM_COPY_FORMATS,
	WAVPACK_COMPRESSION_PROFILES,
	ConversionCallbacks,
	ConversionPlan,
	ConversionSettings,
	ConversionSummary,
	Converter,
	MediaInfo,
	render_output_name,
	resolve_parallel_jobs,
	validate_output_name_template,
)
from .profiles import (
	MAX_PROFILE_DOCUMENT_BYTES,
	NamedConversionProfile,
	dump_user_profiles,
	load_user_profiles,
	merge_user_profiles,
	normalize_profile_name,
	remove_user_profile,
	upsert_user_profile,
)
from .updater import (
	GITHUB_REPOSITORY_URL,
	ReleaseInfo,
	UpdateCanceled,
	download_release,
	fetch_latest_release,
	is_newer_version,
)

try:
	addonHandler.initTranslation()
except Exception:
	pass

try:
	_
except NameError:
	_ = lambda message: message


ADDON_NAME = "Easy Audio Converter"
ADDON_VERSION = "1.8.0"
CONFIG_SECTION = "easyAudioConverter"
SUPPORT_URL = "https://buycoffee.to/kazimierz-parzych"
COMPLETION_SOUND_PATH = Path(__file__).resolve().parent / "sounds" / "notification_complete.wav"
ERROR_SOUND_PATH = Path(__file__).resolve().parent / "sounds" / "notification_error.wav"
CANCEL_SOUND_PATH = Path(__file__).resolve().parent / "sounds" / "notification_cancel.wav"
CONVERSION_LIFECYCLE_WARNING = _(
	"Do not close or restart NVDA while conversion is running. "
	"To stop safely, use the Cancel button."
)
COMPLETION_NOTIFICATION_KEYS = ("speechAndSound", "speechOnly", "soundOnly", "none")
PROGRESS_ANNOUNCEMENT_KEYS = ("milestones", "everyFile", "onDemand")
BUSY_CONVERSION_MODE_KEYS = ("queue", "parallel")
CONFIG_SPEC = {
	"targetFormat": "string(default='mp3')",
	"quality": "string(default='high')",
	"mp3Encoder": "string(default='lame')",
	"sameFolder": "boolean(default=True)",
	"outputFolder": "string(default='')",
	"includeSubfolders": "boolean(default=True)",
	"preserveFolderStructure": "boolean(default=True)",
	"preserveTimestamps": "boolean(default=False)",
	"replaceSourceFiles": "boolean(default=False)",
	"metadataMode": "string(default='all')",
	"metadataFields": (
		"string_list(default=list('title', 'artist', 'album', 'album_artist', "
		"'composer', 'genre', 'date', 'track', 'disc'))"
	),
	"metadataOverrides": "string(default='{}')",
	"outputNameTemplate": "string(default='{source}')",
	"loudnessPreset": "string(default='off')",
	"loudnessTargetI": "float(default=-16.0, min=-70.0, max=-5.0)",
	"loudnessTargetTP": "float(default=-1.5, min=-9.0, max=0.0)",
	"loudnessTargetLRA": "float(default=11.0, min=1.0, max=50.0)",
	"copyArtwork": "boolean(default=False)",
	"copyChapters": "boolean(default=True)",
	"verifyOutput": "boolean(default=False)",
	"showPreflight": "boolean(default=True)",
	"parallelJobs": "integer(default=0, min=0, max=32)",
	"busyConversionMode": "string(default='queue')",
	"advancedProfiles": "string(default='{}')",
	"conversionProfiles": "string(default='{}')",
	"autoCheckUpdates": "boolean(default=True)",
	"completionNotification": "string(default='speechAndSound')",
	"errorSound": "boolean(default=True)",
	"cancelSound": "boolean(default=True)",
	"progressAnnouncements": "string(default='milestones')",
}


def _default_output_folder() -> str:
	return str(Path.home() / "Music" / ADDON_NAME)


def _ensure_config() -> None:
	config.conf.spec[CONFIG_SECTION] = CONFIG_SPEC


def _validated_key(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
	value = str(value or "")
	return value if value in allowed else fallback


def _load_advanced_profiles(value: Any = None) -> dict[str, dict[str, Any]]:
	if value is None:
		_ensure_config()
		value = config.conf[CONFIG_SECTION].get("advancedProfiles", "{}")
	try:
		raw_profiles = json.loads(str(value or "{}"))
	except (TypeError, ValueError):
		return {}
	if not isinstance(raw_profiles, dict):
		return {}
	profiles: dict[str, dict[str, Any]] = {}
	for format_key, raw_profile in raw_profiles.items():
		if format_key not in FORMAT_KEYS or not isinstance(raw_profile, dict):
			continue
		profiles[format_key] = {
			"enabled": bool(raw_profile.get("enabled", False)),
			"bitrate": _safe_int(raw_profile.get("bitrate"), 0),
			"sampleRate": _safe_int(raw_profile.get("sampleRate"), 0),
			"channels": _safe_int(raw_profile.get("channels"), 0),
			"codecLevel": _safe_int(raw_profile.get("codecLevel"), -1),
			"bitDepth": _safe_int(raw_profile.get("bitDepth"), 0),
		}
	return profiles


def _safe_int(value: Any, default: int) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return default


def _safe_float(value: Any, default: float) -> float:
	try:
		return float(value)
	except (TypeError, ValueError):
		return default


def _load_metadata_overrides(value: Any = None) -> dict[str, str]:
	"""Wczytaj ograniczone nadpisania tagów z tekstowej konfiguracji NVDA."""
	if value is None:
		_ensure_config()
		value = config.conf[CONFIG_SECTION].get("metadataOverrides", "{}")
	try:
		raw = json.loads(str(value or "{}"))
	except (TypeError, ValueError):
		return {}
	return normalize_metadata_overrides(raw)


def _dump_metadata_overrides(value: Any) -> str:
	return json.dumps(
		normalize_metadata_overrides(value),
		ensure_ascii=True,
		sort_keys=True,
		separators=(",", ":"),
	)


def _read_settings() -> ConversionSettings:
	_ensure_config()
	conf = config.conf[CONFIG_SECTION]
	target_format = _validated_key(conf.get("targetFormat"), FORMAT_KEYS, "mp3")
	metadata_fields = conf.get("metadataFields", DEFAULT_METADATA_FIELDS)
	if isinstance(metadata_fields, str):
		metadata_fields = [field.strip() for field in metadata_fields.split(",")]
	metadata_fields = tuple(
		field_name
		for field_name in metadata_fields
		if field_name in METADATA_FIELD_KEYS
	)
	parallel_jobs = _safe_int(conf.get("parallelJobs"), 0)
	if parallel_jobs not in PARALLEL_JOB_COUNTS:
		parallel_jobs = 0
	profiles = _load_advanced_profiles(conf.get("advancedProfiles", "{}"))
	return ConversionSettings(
		target_format=target_format,
		quality=_validated_key(conf.get("quality"), QUALITY_KEYS, "high"),
		mp3_encoder=_validated_key(conf.get("mp3Encoder"), MP3_ENCODER_KEYS, "lame"),
		same_folder=bool(conf.get("sameFolder", True)),
		output_folder=str(conf.get("outputFolder") or _default_output_folder()),
		include_subfolders=bool(conf.get("includeSubfolders", True)),
		preserve_folder_structure=bool(conf.get("preserveFolderStructure", True)),
		preserve_timestamps=bool(conf.get("preserveTimestamps", False)),
		replace_source_files=bool(conf.get("replaceSourceFiles", False)),
		metadata_mode=_validated_key(conf.get("metadataMode"), METADATA_MODE_KEYS, "all"),
		metadata_fields=metadata_fields,
		metadata_overrides=_load_metadata_overrides(conf.get("metadataOverrides", "{}")),
		advanced_options=profiles.get(target_format, {}),
		output_name_template=str(conf.get("outputNameTemplate") or "{source}")[:240],
		loudness_preset=_validated_key(
			conf.get("loudnessPreset"),
			LOUDNESS_PRESET_KEYS,
			"off",
		),
		loudness_target_i=_safe_float(conf.get("loudnessTargetI"), -16.0),
		loudness_target_tp=_safe_float(conf.get("loudnessTargetTP"), -1.5),
		loudness_target_lra=_safe_float(conf.get("loudnessTargetLRA"), 11.0),
		copy_artwork=bool(conf.get("copyArtwork", False)),
		copy_chapters=bool(conf.get("copyChapters", True)),
		verify_output=bool(conf.get("verifyOutput", False)),
		show_preflight=bool(conf.get("showPreflight", True)),
		parallel_jobs=parallel_jobs,
	)


def _write_conversion_settings(settings: ConversionSettings) -> None:
	"""Persist a complete job snapshot as the quick-conversion defaults."""
	settings.validate()
	_ensure_config()
	conf = config.conf[CONFIG_SECTION]
	conf["targetFormat"] = settings.target_format
	conf["quality"] = settings.quality
	conf["mp3Encoder"] = settings.mp3_encoder
	conf["sameFolder"] = settings.same_folder
	conf["outputFolder"] = settings.output_folder or _default_output_folder()
	conf["includeSubfolders"] = settings.include_subfolders
	conf["preserveFolderStructure"] = settings.preserve_folder_structure
	conf["preserveTimestamps"] = settings.preserve_timestamps
	conf["replaceSourceFiles"] = settings.replace_source_files
	conf["metadataMode"] = settings.metadata_mode
	conf["metadataFields"] = list(settings.metadata_fields)
	conf["metadataOverrides"] = _dump_metadata_overrides(settings.metadata_overrides)
	conf["outputNameTemplate"] = settings.output_name_template
	conf["loudnessPreset"] = settings.loudness_preset
	conf["loudnessTargetI"] = settings.loudness_target_i
	conf["loudnessTargetTP"] = settings.loudness_target_tp
	conf["loudnessTargetLRA"] = settings.loudness_target_lra
	conf["copyArtwork"] = settings.copy_artwork
	conf["copyChapters"] = settings.copy_chapters
	conf["verifyOutput"] = settings.verify_output
	conf["showPreflight"] = settings.show_preflight
	conf["parallelJobs"] = int(settings.parallel_jobs)
	profiles = _load_advanced_profiles(conf.get("advancedProfiles", "{}"))
	profiles[settings.target_format] = {
		"enabled": bool(settings.advanced_options.get("enabled", False)),
		"bitrate": _safe_int(settings.advanced_options.get("bitrate"), 0),
		"sampleRate": _safe_int(settings.advanced_options.get("sampleRate"), 0),
		"channels": _safe_int(settings.advanced_options.get("channels"), 0),
		"codecLevel": _safe_int(settings.advanced_options.get("codecLevel"), -1),
		"bitDepth": _safe_int(settings.advanced_options.get("bitDepth"), 0),
	}
	conf["advancedProfiles"] = json.dumps(
		profiles,
		ensure_ascii=True,
		sort_keys=True,
		separators=(",", ":"),
	)


def _read_notification_preferences() -> tuple[str, str]:
	_ensure_config()
	conf = config.conf[CONFIG_SECTION]
	return (
		_validated_key(
			conf.get("completionNotification"),
			COMPLETION_NOTIFICATION_KEYS,
			"speechAndSound",
		),
		_validated_key(
			conf.get("progressAnnouncements"),
			PROGRESS_ANNOUNCEMENT_KEYS,
			"milestones",
		),
	)


def _read_busy_conversion_mode() -> str:
	"""Odczytaj sposób obsługi nowego zadania podczas trwającej konwersji."""
	try:
		_ensure_config()
		conf = config.conf[CONFIG_SECTION]
		return _validated_key(
			conf.get("busyConversionMode"),
			BUSY_CONVERSION_MODE_KEYS,
			"queue",
		)
	except Exception:
		# Keep conversion requests safe in test doubles or damaged configurations.
		return "queue"


def _completion_notification_labels() -> dict[str, str]:
	return {
		"speechAndSound": _("Speech and sound"),
		"speechOnly": _("Speech only"),
		"soundOnly": _("Sound only"),
		"none": _("No completion notification"),
	}


def _progress_announcement_labels() -> dict[str, str]:
	return {
		"milestones": _("At progress milestones"),
		"everyFile": _("At every file"),
		"onDemand": _("Only on demand"),
	}


def _busy_conversion_mode_labels() -> dict[str, str]:
	return {
		"queue": _("Add new jobs to the queue"),
		"parallel": _("Run new jobs in separate progress windows"),
	}


def _parallel_job_labels() -> dict[int, str]:
	return {
		0: _("Automatic (dynamic load balancing)"),
		1: _("One file at a time"),
		2: _("2 files at a time"),
		4: _("4 files at a time"),
		8: _("8 files at a time"),
		16: _("16 files at a time"),
		32: _("32 files at a time"),
	}


def _load_user_conversion_profiles(
	fallback: ConversionSettings | None = None,
) -> list[NamedConversionProfile]:
	_ensure_config()
	return load_user_profiles(
		config.conf[CONFIG_SECTION].get("conversionProfiles", "{}"),
		fallback=fallback or _read_settings(),
	)


def _save_user_conversion_profiles(profiles: list[NamedConversionProfile]) -> None:
	_ensure_config()
	config.conf[CONFIG_SECTION]["conversionProfiles"] = dump_user_profiles(profiles)
	config.conf.save()


def _builtin_conversion_profiles(
	base: ConversionSettings | None = None,
) -> list[NamedConversionProfile]:
	"""Return safe content presets while retaining the user's output policy."""
	base = base or _read_settings()
	return [
		NamedConversionProfile(
			_("Audiobook MP3"),
			replace(
				base,
				target_format="mp3",
				quality="economical",
				mp3_encoder="lame",
				metadata_mode="all",
				loudness_preset="off",
				copy_artwork=True,
				copy_chapters=True,
				verify_output=False,
				advanced_options={
					"enabled": True,
					"bitrate": 64,
					"sampleRate": 44100,
					"channels": 1,
					"codecLevel": 2,
					"bitDepth": 0,
				},
			),
		),
		NamedConversionProfile(
			_("Podcast Opus"),
			replace(
				base,
				target_format="opus",
				quality="standard",
				metadata_mode="all",
				loudness_preset="podcast",
				copy_artwork=False,
				copy_chapters=True,
				verify_output=False,
				advanced_options={
					"enabled": True,
					"bitrate": 96,
					"sampleRate": 0,
					"channels": 2,
					"codecLevel": 10,
					"bitDepth": 0,
				},
			),
		),
		NamedConversionProfile(
			_("Archive FLAC"),
			replace(
				base,
				target_format="flac",
				quality="high",
				metadata_mode="all",
				loudness_preset="off",
				copy_artwork=True,
				copy_chapters=True,
				verify_output=True,
				advanced_options={
					"enabled": True,
					"bitrate": 0,
					"sampleRate": 0,
					"channels": 0,
					"codecLevel": 8,
					"bitDepth": 0,
				},
			),
		),
	]


def _format_labels() -> dict[str, str]:
	return {
		"mp3": _("MP3"),
		"wav": _("WAV"),
		"flac": _("FLAC"),
		"ogg": _("Ogg Vorbis"),
		"opus": _("Opus"),
		"m4a": _("M4A (AAC)"),
		"aac": _("AAC"),
		"wma": _("WMA"),
		"alac": _("ALAC (Apple Lossless)"),
		"aiff": _("AIFF"),
		"ac3": _("AC-3"),
		"eac3": _("E-AC-3"),
		"wavpack": _("WavPack"),
		"mp2": _("MP2"),
		"amr": _("AMR narrowband"),
		"amrwb": _("AMR wideband"),
		ORIGINAL_AUDIO_COPY_FORMAT: _(
			"Extract original audio stream (no re-encoding)"
		),
		AAC_M4A_COPY_FORMAT: _("Remux AAC to M4A (no re-encoding)"),
	}


def _stream_copy_description(format_key: str) -> str:
	if format_key == ORIGINAL_AUDIO_COPY_FORMAT:
		return _(
			"The first audio stream will be extracted without re-encoding. "
			"Its codec and quality remain unchanged, and the output extension "
			"is selected automatically.",
		)
	if format_key == AAC_M4A_COPY_FORMAT:
		return _(
			"The first AAC audio stream will be remuxed into M4A without "
			"re-encoding. Sources whose first audio stream is not AAC are skipped.",
		)
	return ""


def _output_name_preview(format_key: str, base_name: str) -> str:
	if format_key == ORIGINAL_AUDIO_COPY_FORMAT:
		return _(
			"{name} (extension selected from the source audio codec)"
		).format(name=base_name)
	return f"{base_name}{FORMAT_EXTENSIONS[format_key]}"


def _quality_labels() -> dict[str, str]:
	return {
		"economical": _("Economical"),
		"standard": _("Standard"),
		"high": _("High"),
		"veryHigh": _("Very high"),
	}


def _mp3_encoder_labels() -> dict[str, str]:
	return {
		"lame": _("LAME MP3"),
		"fraunhofer": _("Fraunhofer / Windows Media Foundation MP3"),
	}


def _metadata_mode_labels() -> dict[str, str]:
	return {
		"none": _("Do not copy metadata"),
		"all": _("Copy all text metadata"),
		"selected": _("Copy selected metadata fields"),
	}


def _loudness_preset_labels() -> dict[str, str]:
	return {
		"off": _("Disabled"),
		"podcast": _("Podcast: -16 LUFS, -1.5 dBTP"),
		"music": _("Music and streaming: -14 LUFS, -1 dBTP"),
		"broadcast": _("Broadcast: -23 LUFS, -2 dBTP"),
		"custom": _("Custom EBU R128 target"),
	}


def _metadata_field_labels() -> dict[str, str]:
	return {
		"title": _("Title"),
		"artist": _("Artist"),
		"album": _("Album"),
		"album_artist": _("Album artist"),
		"composer": _("Composer"),
		"genre": _("Genre"),
		"date": _("Date or year"),
		"track": _("Track number"),
		"disc": _("Disc number"),
		"comment": _("Comment"),
		"copyright": _("Copyright"),
		"lyrics": _("Lyrics"),
		"language": _("Language"),
		"publisher": _("Publisher"),
		"track_total": _("Total tracks"),
		"disc_total": _("Total discs"),
		"compilation": _("Compilation"),
		"bpm": _("BPM"),
		"description": _("Description"),
		"grouping": _("Grouping"),
		"encoder": _("Encoder"),
		"isrc": _("ISRC"),
		"sort_artist": _("Sort artist"),
		"sort_album": _("Sort album"),
		"sort_title": _("Sort title"),
	}


def _add_labeled_spin_double(
	helper: guiHelper.BoxSizerHelper,
	parent: wx.Window,
	label: str,
	*,
	minimum: float,
	maximum: float,
	initial: float,
	increment: float,
) -> wx.SpinCtrlDouble:
	"""Create a decimal spin control with an explicit accessible name."""
	row = wx.BoxSizer(wx.HORIZONTAL)
	label_control = wx.StaticText(parent, label=label)
	control = wx.SpinCtrlDouble(
		parent,
		min=minimum,
		max=maximum,
		initial=initial,
		inc=increment,
	)
	control.SetDigits(1)
	control.SetName(label.replace("&", "").rstrip(":"))
	row.Add(label_control, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
	row.Add(control, 0)
	helper.addItem(row)
	return control


def _open_support_page() -> None:
	try:
		opened = webbrowser.open_new_tab(SUPPORT_URL)
	except Exception:
		opened = False
		log.debugWarning("Easy Audio Converter: failed to open the support page", exc_info=True)
	if opened:
		ui.message(_("Opening the support page"))
	else:
		ui.message(_("Cannot open the support page. Open this address manually: {url}").format(url=SUPPORT_URL))


def _top_level_window_handle(window_handle: int) -> int:
	"""Zwróć okno główne dla uchwytu, zachowując użyteczną wartość awaryjną."""
	if not window_handle:
		return 0
	try:
		user32 = ctypes.windll.user32
		user32.GetAncestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
		user32.GetAncestor.restype = ctypes.c_void_p
		root = int(user32.GetAncestor(int(window_handle), 2) or 0)
	except Exception:
		root = 0
	return root or int(window_handle)


def _top_level_foreground_window() -> int:
	user32 = ctypes.windll.user32
	user32.GetForegroundWindow.restype = ctypes.c_void_p
	foreground = int(user32.GetForegroundWindow() or 0)
	return _top_level_window_handle(foreground)


def _remembered_focus_objects() -> tuple[Any, ...]:
	"""Zwróć bieżący fokus oraz fokus zapamiętany przed otwarciem menu NVDA."""
	objects: list[Any] = []
	seen: set[int] = set()

	def add(obj: Any) -> None:
		if obj is None or id(obj) in seen:
			return
		seen.add(id(obj))
		objects.append(obj)

	try:
		add(api.getFocusObject())
	except Exception:
		pass
	main_frame = getattr(gui, "mainFrame", None)
	try:
		add(getattr(main_frame, "prevFocus", None))
	except Exception:
		pass
	try:
		ancestors = tuple(getattr(main_frame, "prevFocusAncestors", ()) or ())
	except Exception:
		ancestors = ()
	for ancestor in reversed(ancestors):
		add(ancestor)
	return tuple(objects)


def _explorer_candidate_window_handles() -> tuple[int, ...]:
	"""Zwróć okna, do których może należeć zaznaczenie ukryte za menu NVDA."""
	handles: list[int] = []

	def add(handle: int) -> None:
		handle = int(handle or 0)
		if handle and handle not in handles:
			handles.append(handle)

	try:
		add(_top_level_foreground_window())
	except Exception:
		pass
	for obj in _remembered_focus_objects():
		try:
			add(_top_level_window_handle(int(getattr(obj, "windowHandle", 0) or 0)))
		except Exception:
			continue
	return tuple(handles)


def _explorer_context() -> tuple[list[str], str]:
	"""Return selected Explorer paths and the current Explorer folder."""
	try:
		from comtypes.client import CreateObject

		candidate_handles = _explorer_candidate_window_handles()
		if not candidate_handles:
			return [], ""
		shell = CreateObject("Shell.Application", dynamic=True)
		windows = shell.Windows()
		matches: dict[int, tuple[list[str], str]] = {}
		for index in range(int(windows.Count)):
			window = windows.Item(index)
			try:
				window_handle = _top_level_window_handle(int(window.HWND))
				if window_handle not in candidate_handles:
					continue
				document = window.Document
				folder = str(document.Folder.Self.Path or "")
				selected_items = document.SelectedItems()
				selection = []
				for item_index in range(int(selected_items.Count)):
					path = str(selected_items.Item(item_index).Path or "")
					if path and os.path.exists(path):
						selection.append(path)
				if selection:
					# Windows 11 Explorer tabs can share a top-level window.
					# Prefer a matching tab with a real selection and keep the
					# last such tab, which ShellWindows exposes as the active one.
					matches[window_handle] = (selection, folder)
				elif window_handle not in matches:
					matches[window_handle] = ([], folder)
			except Exception:
				continue
		for window_handle in candidate_handles:
			selection, folder = matches.get(window_handle, ([], ""))
			if folder:
				return selection, folder
	except Exception:
		pass
	return [], ""


def _focused_path(current_folder: str = "") -> str:
	"""Spróbuj odtworzyć ścieżkę z bieżącego lub zapamiętanego fokusu."""
	for obj in _remembered_focus_objects():
		values = []
		for attribute in ("value", "name"):
			try:
				values.append(getattr(obj, attribute, ""))
			except Exception:
				continue
		for value in values:
			if not value:
				continue
			try:
				candidate = os.path.expandvars(os.path.expanduser(str(value).strip('"')))
				if os.path.exists(candidate):
					return candidate
				if current_folder:
					candidate = os.path.join(current_folder, str(value))
					if os.path.exists(candidate):
						return candidate
			except OSError:
				continue
	return ""


class _EasyAudioConverterStandardSettingsPage(SettingsPanel):
	# Translators: Name of the standard settings tab.
	title = _("Standard settings")

	def makeSettings(self, settingsSizer):
		settings = _read_settings()
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		format_labels = _format_labels()
		self.target_format = helper.addLabeledControl(
			# Translators: Label for the target audio format list.
			_("Target format:"),
			wx.Choice,
			choices=[format_labels[key] for key in FORMAT_KEYS],
		)
		self.target_format.SetSelection(FORMAT_KEYS.index(settings.target_format))

		quality_labels = _quality_labels()
		self.quality = helper.addLabeledControl(
			# Translators: Label for the conversion quality list.
			_("Quality:"),
			wx.Choice,
			choices=[quality_labels[key] for key in QUALITY_KEYS],
		)
		self.quality.SetSelection(QUALITY_KEYS.index(settings.quality))

		encoder_labels = _mp3_encoder_labels()
		self.mp3_encoder = helper.addLabeledControl(
			# Translators: Label for the MP3 encoder list.
			_("MP3 encoder:"),
			wx.Choice,
			choices=[encoder_labels[key] for key in MP3_ENCODER_KEYS],
		)
		self.mp3_encoder.SetSelection(MP3_ENCODER_KEYS.index(settings.mp3_encoder))
		self.stream_copy_note = helper.addItem(wx.StaticText(self, label=""))

		self.same_folder = helper.addItem(
			# Translators: Convert next to each source instead of using one destination folder.
			wx.CheckBox(self, label=_("Save converted files next to the source files")),
		)
		self.same_folder.SetValue(settings.same_folder)

		self.output_folder = helper.addLabeledControl(
			# Translators: Label for the destination folder edit field.
			_("Destination folder:"),
			wx.TextCtrl,
		)
		self.output_folder.SetValue(settings.output_folder)
		self.browse_button = helper.addItem(
			# Translators: Opens a folder chooser.
			wx.Button(self, label=_("Browse...")),
		)
		self.output_name_template = helper.addLabeledControl(
			_("Output filename template:"),
			wx.TextCtrl,
		)
		self.output_name_template.SetValue(settings.output_name_template)
		self.template_help = helper.addItem(
			wx.StaticText(
				self,
				label=_(
					"Available fields: {source}, {title}, {artist}, {album}, "
					"{track}, {disc}, {index}, {format}.",
				),
			)
		)
		self.template_preview = helper.addItem(wx.StaticText(self, label=""))

		self.include_subfolders = helper.addItem(
			# Translators: Include audio files from child folders during folder conversion.
			wx.CheckBox(self, label=_("Include subfolders when converting a folder")),
		)
		self.include_subfolders.SetValue(settings.include_subfolders)

		self.preserve_structure = helper.addItem(
			# Translators: Recreate source subfolders below the destination folder.
			wx.CheckBox(self, label=_("Preserve the source folder structure in the destination")),
		)
		self.preserve_structure.SetValue(settings.preserve_folder_structure)
		self.preserve_timestamps = helper.addItem(
			# Translators: Kopiowanie dat utworzenia i modyfikacji do przekonwertowanych plików.
			wx.CheckBox(
				self,
				label=_("Preserve source file creation and modification dates"),
			),
		)
		self.preserve_timestamps.SetValue(settings.preserve_timestamps)
		self.replace_source_files = helper.addItem(
			# Translators: Trwałe usuwanie oryginałów dopiero po udanej konwersji.
			wx.CheckBox(
				self,
				label=_(
					"Replace source files after successful conversion "
					"(permanently deletes originals)",
				),
			),
		)
		self.replace_source_files.SetValue(settings.replace_source_files)

		metadata_mode_labels = _metadata_mode_labels()
		self.metadata_mode = helper.addLabeledControl(
			# Translators: Label for choosing how source metadata is copied.
			_("Metadata export:"),
			wx.Choice,
			choices=[metadata_mode_labels[key] for key in METADATA_MODE_KEYS],
		)
		self.metadata_mode.SetSelection(METADATA_MODE_KEYS.index(settings.metadata_mode))

		metadata_field_labels = _metadata_field_labels()
		self.metadata_fields_sizer = wx.StaticBoxSizer(
			wx.VERTICAL,
			self,
			# Translators: Label for the group of metadata field check boxes.
			_("Metadata fields to copy:"),
		)
		self.metadata_fields = []
		for field_name in METADATA_FIELD_KEYS:
			checkbox = wx.CheckBox(self, label=metadata_field_labels[field_name])
			checkbox.SetValue(field_name in settings.metadata_fields)
			self.metadata_fields_sizer.Add(checkbox, 0, wx.BOTTOM, 3)
			self.metadata_fields.append(checkbox)
		helper.addItem(self.metadata_fields_sizer)
		self.metadata_overrides = dict(settings.metadata_overrides)
		self.metadata_overrides_button = helper.addItem(
			wx.Button(self, label=_("Edit metadata overrides..."))
		)
		self.metadata_overrides_summary = helper.addItem(wx.StaticText(self, label=""))

		self.target_format.Bind(wx.EVT_CHOICE, self._update_control_state)
		self.same_folder.Bind(wx.EVT_CHECKBOX, self._update_control_state)
		self.metadata_mode.Bind(wx.EVT_CHOICE, self._update_control_state)
		self.metadata_overrides_button.Bind(wx.EVT_BUTTON, self._on_metadata_overrides)
		self.output_name_template.Bind(wx.EVT_TEXT, self._update_name_preview)
		self.browse_button.Bind(wx.EVT_BUTTON, self._on_browse)
		self._update_control_state()
		self._update_name_preview()
		self._update_metadata_overrides_summary()

	def _update_metadata_overrides_summary(self) -> None:
		count = len(self.metadata_overrides)
		self.metadata_overrides_summary.SetLabel(
			_("Metadata overrides: {count} fields").format(count=count)
		)

	def _update_control_state(self, event=None):
		target_format = FORMAT_KEYS[self.target_format.GetSelection()]
		stream_copy = target_format in STREAM_COPY_FORMATS
		is_mp3 = target_format == "mp3"
		self.quality.Enable(not stream_copy)
		self.mp3_encoder.Enable(is_mp3)
		self.stream_copy_note.SetLabel(_stream_copy_description(target_format))
		self.stream_copy_note.Show(stream_copy)
		if stream_copy:
			self.stream_copy_note.Wrap(max(360, self.GetClientSize().GetWidth() - 20))
		use_destination = not self.same_folder.IsChecked()
		self.output_folder.Enable(use_destination)
		self.browse_button.Enable(use_destination)
		self.preserve_structure.Enable(use_destination)
		metadata_supported = target_format != ORIGINAL_AUDIO_COPY_FORMAT
		self.metadata_mode.Enable(metadata_supported)
		copy_selected_metadata = (
			metadata_supported
			and METADATA_MODE_KEYS[self.metadata_mode.GetSelection()] == "selected"
		)
		self.metadata_fields_sizer.GetStaticBox().Enable(copy_selected_metadata)
		for checkbox in self.metadata_fields:
			checkbox.Enable(copy_selected_metadata)
		self.metadata_overrides_button.Enable(True)
		self._update_name_preview()
		self.Layout()

	def _update_name_preview(self, event=None):
		try:
			target_format = FORMAT_KEYS[self.target_format.GetSelection()]
			preview = render_output_name(
				self.output_name_template.GetValue(),
				Path("Example source.wav"),
				target_format,
				{
					"title": _("Example title"),
					"artist": _("Example artist"),
					"album": _("Example album"),
					"track": "01",
					"disc": "1",
					**self.metadata_overrides,
				},
			)
			self.template_preview.SetLabel(
				_("Example filename: {name}").format(
					name=_output_name_preview(target_format, preview)
				)
			)
		except ValueError as error:
			self.template_preview.SetLabel(
				_("Invalid filename template: {error}").format(error=error)
			)
		if event is not None:
			event.Skip()

	def _on_metadata_overrides(self, event) -> None:
		dialog = MetadataOverridesDialog(self, self.metadata_overrides)
		try:
			if dialog.ShowModal() == wx.ID_OK:
				self.metadata_overrides = dialog.values()
				self._update_metadata_overrides_summary()
		finally:
			dialog.Destroy()

	def _on_browse(self, event):
		initial_path = self.output_folder.GetValue().strip() or _default_output_folder()
		dialog = wx.DirDialog(
			self,
			# Translators: Title of the destination folder chooser.
			_("Choose the destination folder"),
			defaultPath=initial_path,
			style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
		)
		try:
			if dialog.ShowModal() == wx.ID_OK:
				self.output_folder.SetValue(dialog.GetPath())
		finally:
			dialog.Destroy()

	def isValid(self) -> bool:
		try:
			validate_output_name_template(self.output_name_template.GetValue())
		except ValueError as error:
			gui.messageBox(
				str(error),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			self.output_name_template.SetFocus()
			return False
		return True

	def onSave(self):
		_ensure_config()
		conf = config.conf[CONFIG_SECTION]
		conf["targetFormat"] = FORMAT_KEYS[self.target_format.GetSelection()]
		conf["quality"] = QUALITY_KEYS[self.quality.GetSelection()]
		conf["mp3Encoder"] = MP3_ENCODER_KEYS[self.mp3_encoder.GetSelection()]
		conf["sameFolder"] = self.same_folder.IsChecked()
		conf["outputFolder"] = self.output_folder.GetValue().strip() or _default_output_folder()
		conf["includeSubfolders"] = self.include_subfolders.IsChecked()
		conf["preserveFolderStructure"] = self.preserve_structure.IsChecked()
		conf["preserveTimestamps"] = self.preserve_timestamps.IsChecked()
		conf["replaceSourceFiles"] = self.replace_source_files.IsChecked()
		conf["metadataMode"] = METADATA_MODE_KEYS[self.metadata_mode.GetSelection()]
		conf["metadataFields"] = [
			field_name
			for field_name, checkbox in zip(METADATA_FIELD_KEYS, self.metadata_fields)
			if checkbox.IsChecked()
		]
		conf["metadataOverrides"] = _dump_metadata_overrides(self.metadata_overrides)
		conf["outputNameTemplate"] = self.output_name_template.GetValue().strip()


class _EasyAudioConverterProcessingSettingsPage(SettingsPanel):
	"""Loudness, verification and notification preferences."""

	title = _("Processing and notifications")

	def makeSettings(self, settingsSizer):
		settings = _read_settings()
		_ensure_config()
		conf = config.conf[CONFIG_SECTION]
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		self._target_format = settings.target_format
		self.stream_copy_note = helper.addItem(wx.StaticText(self, label=""))

		loudness_labels = _loudness_preset_labels()
		self.loudness_preset = helper.addLabeledControl(
			_("Loudness normalization:"),
			wx.Choice,
			choices=[loudness_labels[key] for key in LOUDNESS_PRESET_KEYS],
		)
		self.loudness_preset.SetSelection(
			LOUDNESS_PRESET_KEYS.index(settings.loudness_preset)
		)
		self.loudness_target_i = _add_labeled_spin_double(
			helper,
			self,
			_("Custom integrated loudness in LUFS:"),
			minimum=-70.0,
			maximum=-5.0,
			initial=settings.loudness_target_i,
			increment=0.5,
		)
		self.loudness_target_tp = _add_labeled_spin_double(
			helper,
			self,
			_("Custom true peak in dBTP:"),
			minimum=-9.0,
			maximum=0.0,
			initial=settings.loudness_target_tp,
			increment=0.1,
		)
		self.loudness_target_lra = _add_labeled_spin_double(
			helper,
			self,
			_("Custom loudness range in LU:"),
			minimum=1.0,
			maximum=50.0,
			initial=settings.loudness_target_lra,
			increment=0.5,
		)

		self.copy_artwork = helper.addItem(
			wx.CheckBox(self, label=_("Copy embedded cover artwork when the target supports it"))
		)
		self.copy_artwork.SetValue(settings.copy_artwork)
		self.copy_chapters = helper.addItem(
			wx.CheckBox(self, label=_("Copy chapter markers"))
		)
		self.copy_chapters.SetValue(settings.copy_chapters)
		self.verify_output = helper.addItem(
			wx.CheckBox(
				self,
				label=_("Deeply verify output by decoding it and comparing duration"),
			)
		)
		self.verify_output.SetValue(settings.verify_output)
		parallel_labels = _parallel_job_labels()
		self.parallel_jobs = helper.addLabeledControl(
			_("Parallel conversion jobs:"),
			wx.Choice,
			choices=[parallel_labels[key] for key in PARALLEL_JOB_COUNTS],
		)
		self.parallel_jobs.SetSelection(
			PARALLEL_JOB_COUNTS.index(settings.parallel_jobs)
			if settings.parallel_jobs in PARALLEL_JOB_COUNTS
			else 0
		)
		busy_labels = _busy_conversion_mode_labels()
		self.busy_conversion_mode = helper.addLabeledControl(
			_("When another conversion is active:"),
			wx.Choice,
			choices=[busy_labels[key] for key in BUSY_CONVERSION_MODE_KEYS],
		)
		busy_mode = _read_busy_conversion_mode()
		self.busy_conversion_mode.SetSelection(
			BUSY_CONVERSION_MODE_KEYS.index(busy_mode)
		)
		helper.addItem(
			wx.StaticText(
				self,
				label=_(
					"Separate progress windows run independently and may use more CPU and memory."
				),
			)
		)
		helper.addItem(
			wx.StaticText(
				self,
				label=_(
					"Automatic mode dynamically adjusts independent files using CPU and memory load. "
					"GPU acceleration is not used for audio encoding.",
				),
			)
		)
		self.show_preflight = helper.addItem(
			wx.CheckBox(self, label=_("Show a conversion plan before starting"))
		)
		self.show_preflight.SetValue(settings.show_preflight)
		helper.addItem(
			wx.StaticText(
				self,
				label=_(
					"When the plan is disabled, ordinary conversions use a fast path "
					"and skip the preliminary input scan when it is not needed.",
				),
			)
		)

		completion_mode, progress_mode = _read_notification_preferences()
		completion_labels = _completion_notification_labels()
		self.completion_notification = helper.addLabeledControl(
			_("Successful completion notification:"),
			wx.Choice,
			choices=[completion_labels[key] for key in COMPLETION_NOTIFICATION_KEYS],
		)
		self.completion_notification.SetSelection(
			COMPLETION_NOTIFICATION_KEYS.index(completion_mode)
		)
		self.test_success_button = helper.addItem(
			wx.Button(self, label=_("Test success sound"))
		)

		self.error_sound = helper.addItem(
			wx.CheckBox(self, label=_("Play a sound when a conversion fails"))
		)
		self.error_sound.SetValue(bool(conf.get("errorSound", True)))
		self.test_error_button = helper.addItem(
			wx.Button(self, label=_("Test error sound"))
		)
		self.cancel_sound = helper.addItem(
			wx.CheckBox(self, label=_("Play a sound when a conversion is canceled or stopped"))
		)
		self.cancel_sound.SetValue(bool(conf.get("cancelSound", True)))
		self.test_cancel_button = helper.addItem(
			wx.Button(self, label=_("Test cancel sound"))
		)

		progress_labels = _progress_announcement_labels()
		self.progress_announcements = helper.addLabeledControl(
			_("Automatic progress announcements:"),
			wx.Choice,
			choices=[progress_labels[key] for key in PROGRESS_ANNOUNCEMENT_KEYS],
		)
		self.progress_announcements.SetSelection(
			PROGRESS_ANNOUNCEMENT_KEYS.index(progress_mode)
		)
		self.auto_check_updates = helper.addItem(
			wx.CheckBox(self, label=_("Automatically check for add-on updates"))
		)
		self.auto_check_updates.SetValue(bool(conf.get("autoCheckUpdates", True)))
		self.support_button = helper.addItem(
			wx.Button(self, label=_("Support the author"))
		)

		self.loudness_preset.Bind(wx.EVT_CHOICE, self._update_control_state)
		self.error_sound.Bind(wx.EVT_CHECKBOX, self._update_control_state)
		self.cancel_sound.Bind(wx.EVT_CHECKBOX, self._update_control_state)
		self.completion_notification.Bind(wx.EVT_CHOICE, self._update_control_state)
		self.test_success_button.Bind(
			wx.EVT_BUTTON,
			lambda event: _play_completion_sound(),
		)
		self.test_error_button.Bind(
			wx.EVT_BUTTON,
			lambda event: _play_event_sound(ERROR_SOUND_PATH, "error"),
		)
		self.test_cancel_button.Bind(
			wx.EVT_BUTTON,
			lambda event: _play_event_sound(CANCEL_SOUND_PATH, "cancel"),
		)
		self.support_button.Bind(wx.EVT_BUTTON, lambda event: _open_support_page())
		self._update_control_state()

	def _update_control_state(self, event=None):
		stream_copy = self._target_format in STREAM_COPY_FORMATS
		self.stream_copy_note.SetLabel(
			_stream_copy_description(self._target_format)
		)
		self.stream_copy_note.Show(stream_copy)
		if stream_copy:
			self.stream_copy_note.Wrap(max(360, self.GetClientSize().GetWidth() - 20))
		self.loudness_preset.Enable(not stream_copy)
		custom = (
			not stream_copy
			and
			LOUDNESS_PRESET_KEYS[max(0, self.loudness_preset.GetSelection())] == "custom"
		)
		self.loudness_target_i.Enable(custom)
		self.loudness_target_tp.Enable(custom)
		self.loudness_target_lra.Enable(custom)
		preserve_extra_streams = self._target_format != ORIGINAL_AUDIO_COPY_FORMAT
		self.copy_artwork.Enable(preserve_extra_streams)
		self.copy_chapters.Enable(preserve_extra_streams)
		completion_mode = COMPLETION_NOTIFICATION_KEYS[
			max(0, self.completion_notification.GetSelection())
		]
		self.test_success_button.Enable(
			completion_mode in {"speechAndSound", "soundOnly"}
		)
		self.test_error_button.Enable(self.error_sound.IsChecked())
		self.test_cancel_button.Enable(self.cancel_sound.IsChecked())
		self.Layout()
		if event is not None:
			event.Skip()

	def onSave(self):
		conf = config.conf[CONFIG_SECTION]
		target_format = _validated_key(conf.get("targetFormat"), FORMAT_KEYS, "mp3")
		conf["loudnessPreset"] = (
			"off"
			if target_format in STREAM_COPY_FORMATS
			else LOUDNESS_PRESET_KEYS[max(0, self.loudness_preset.GetSelection())]
		)
		conf["loudnessTargetI"] = self.loudness_target_i.GetValue()
		conf["loudnessTargetTP"] = self.loudness_target_tp.GetValue()
		conf["loudnessTargetLRA"] = self.loudness_target_lra.GetValue()
		conf["copyArtwork"] = (
			self.copy_artwork.IsChecked()
			and target_format != ORIGINAL_AUDIO_COPY_FORMAT
		)
		conf["copyChapters"] = (
			self.copy_chapters.IsChecked()
			and target_format != ORIGINAL_AUDIO_COPY_FORMAT
		)
		conf["verifyOutput"] = self.verify_output.IsChecked()
		conf["parallelJobs"] = PARALLEL_JOB_COUNTS[
			max(0, self.parallel_jobs.GetSelection())
		]
		conf["busyConversionMode"] = BUSY_CONVERSION_MODE_KEYS[
			max(0, self.busy_conversion_mode.GetSelection())
		]
		conf["showPreflight"] = self.show_preflight.IsChecked()
		conf["completionNotification"] = COMPLETION_NOTIFICATION_KEYS[
			max(0, self.completion_notification.GetSelection())
		]
		conf["errorSound"] = self.error_sound.IsChecked()
		conf["cancelSound"] = self.cancel_sound.IsChecked()
		conf["progressAnnouncements"] = PROGRESS_ANNOUNCEMENT_KEYS[
			max(0, self.progress_announcements.GetSelection())
		]
		conf["autoCheckUpdates"] = self.auto_check_updates.IsChecked()


def _default_advanced_profile() -> dict[str, Any]:
	return {
		"enabled": False,
		"bitrate": 0,
		"sampleRate": 0,
		"channels": 0,
		"codecLevel": -1,
		"bitDepth": 0,
	}


def _lossless_compression_choices(format_key: str) -> list[tuple[int, str]]:
	"""Zwraca nazwane, bezpieczne poziomy kompresji dla kodeka bezstratnego."""
	if format_key == "flac":
		choices = [(-1, _("Use the quality preset"))]
		for level in FLAC_COMPRESSION_LEVELS:
			if level == 0:
				label = _("FLAC 0 — fastest encoding")
			elif level == FLAC_COMPRESSION_LEVELS[-1]:
				label = _("FLAC 12 — maximum compression, very slow")
			else:
				label = _("FLAC {level}").format(level=level)
			choices.append((level, label))
		return choices
	if format_key == "wavpack":
		labels = (
			_("Fast, -f (FFmpeg level 0)"),
			_("Normal (FFmpeg level 1)"),
			_("High, -h (FFmpeg level 2)"),
			_("Very high, -hh (FFmpeg level 3)"),
			_("Very high + extra 1, -hhx1 (FFmpeg level 4)"),
			_("Very high + extra 2, -hhx2 (FFmpeg level 5)"),
			_("Very high + extra 3, -hhx3 (FFmpeg level 6)"),
			_("Very high + extra 4, -hhx4 (FFmpeg level 7)"),
			_("Maximum, -hhx6 (FFmpeg level 8)"),
		)
		return [(-1, _("Use the quality preset"))] + [
			(profile[0], label)
			for profile, label in zip(WAVPACK_COMPRESSION_PROFILES, labels)
		]
	return [(-1, _("Not used by this codec"))]


class _EasyAudioConverterAdvancedSettingsPage(SettingsPanel):
	# Translators: Name of the advanced settings tab.
	title = _("Advanced settings")

	_BITRATE_FORMATS = {"mp3", "opus", "m4a", "aac", "wma", "ac3", "eac3", "mp2", "amr", "amrwb"}
	_NUMERIC_LEVEL_FORMATS = {"mp3", "ogg", "opus"}
	_LOSSLESS_COMPRESSION_FORMATS = {"flac", "wavpack"}
	_BIT_DEPTH_FORMATS = {"wav", "aiff"}

	def makeSettings(self, settingsSizer):
		_ensure_config()
		conf = config.conf[CONFIG_SECTION]
		self._profiles = _load_advanced_profiles(conf.get("advancedProfiles", "{}"))
		self._current_format = _validated_key(conf.get("targetFormat"), FORMAT_KEYS, "mp3")
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		format_labels = _format_labels()
		self.codec = helper.addLabeledControl(
			# Translators: Advanced settings apply separately to each target codec.
			_("Codec profile to edit:"),
			wx.Choice,
			choices=[format_labels[key] for key in FORMAT_KEYS],
		)
		self.codec.SetSelection(FORMAT_KEYS.index(self._current_format))

		self.enabled = helper.addItem(
			# Translators: Enables advanced overrides for the selected target codec.
			wx.CheckBox(self, label=_("Enable advanced overrides for this codec")),
		)
		self.bitrate = helper.addLabeledControl(
			# Translators: Zero keeps the bitrate selected by the quality preset.
			_("Bitrate in kbps (0 uses the quality preset):"),
			wx.SpinCtrl,
			min=0,
			max=1536,
			initial=0,
		)
		self.sample_rate = helper.addLabeledControl(
			_("Sample rate:"),
			wx.Choice,
			choices=[_("Keep the source sample rate")]
			+ [f"{rate} Hz" for rate in ADVANCED_SAMPLE_RATES if rate],
		)
		self.channels = helper.addLabeledControl(
			_("Channels:"),
			wx.Choice,
			choices=[_("Keep the source channel count"), _("Mono"), _("Stereo")],
		)
		self.codec_level = helper.addLabeledControl(
			# Translators: The meaning is explained in the following help text.
			_("Codec-specific level (-1 uses the preset):"),
			wx.SpinCtrl,
			min=-1,
			max=12,
			initial=-1,
		)
		self.lossless_compression = helper.addLabeledControl(
			_("Lossless compression profile:"),
			wx.Choice,
			choices=[],
		)
		self._lossless_compression_values: tuple[int, ...] = (-1,)
		self.bit_depth = helper.addLabeledControl(
			_("PCM bit depth:"),
			wx.Choice,
			choices=[_("Use the quality preset"), _("16 bit"), _("24 bit"), _("32 bit")],
		)
		self.level_help = helper.addItem(wx.StaticText(self, label=""))

		self.codec.Bind(wx.EVT_CHOICE, self._on_codec_changed)
		self.enabled.Bind(wx.EVT_CHECKBOX, self._update_control_state)
		self._load_profile(self._current_format)

	def _profile(self, format_key: str) -> dict[str, Any]:
		return dict(_default_advanced_profile(), **self._profiles.get(format_key, {}))

	def _store_current_profile(self) -> None:
		codec_level = self.codec_level.GetValue()
		if self._current_format in self._LOSSLESS_COMPRESSION_FORMATS:
			selection = self.lossless_compression.GetSelection()
			codec_level = (
				self._lossless_compression_values[selection]
				if 0 <= selection < len(self._lossless_compression_values)
				else -1
			)
		self._profiles[self._current_format] = {
			"enabled": (
				self.enabled.IsChecked()
				and self._current_format not in STREAM_COPY_FORMATS
			),
			"bitrate": self.bitrate.GetValue(),
			"sampleRate": ADVANCED_SAMPLE_RATES[self.sample_rate.GetSelection()],
			"channels": ADVANCED_CHANNEL_COUNTS[self.channels.GetSelection()],
			"codecLevel": codec_level,
			"bitDepth": ADVANCED_BIT_DEPTHS[self.bit_depth.GetSelection()],
		}

	def _load_profile(self, format_key: str) -> None:
		profile = self._profile(format_key)
		self.enabled.SetValue(
			bool(profile["enabled"]) and format_key not in STREAM_COPY_FORMATS
		)
		self.bitrate.SetValue(max(0, min(1536, _safe_int(profile["bitrate"], 0))))
		sample_rate = _safe_int(profile["sampleRate"], 0)
		self.sample_rate.SetSelection(
			ADVANCED_SAMPLE_RATES.index(sample_rate)
			if sample_rate in ADVANCED_SAMPLE_RATES
			else 0
		)
		channels = _safe_int(profile["channels"], 0)
		self.channels.SetSelection(
			ADVANCED_CHANNEL_COUNTS.index(channels)
			if channels in ADVANCED_CHANNEL_COUNTS
			else 0
		)
		codec_level = max(-1, min(12, _safe_int(profile["codecLevel"], -1)))
		self.codec_level.SetValue(codec_level)
		self._load_lossless_compression(format_key, codec_level)
		bit_depth = _safe_int(profile["bitDepth"], 0)
		self.bit_depth.SetSelection(
			ADVANCED_BIT_DEPTHS.index(bit_depth)
			if bit_depth in ADVANCED_BIT_DEPTHS
			else 0
		)
		self._update_control_state()

	def _load_lossless_compression(self, format_key: str, codec_level: int) -> None:
		choices = _lossless_compression_choices(format_key)
		self._lossless_compression_values = tuple(value for value, _label in choices)
		self.lossless_compression.Clear()
		self.lossless_compression.AppendItems([label for _value, label in choices])
		if codec_level not in self._lossless_compression_values:
			codec_level = (
				self._lossless_compression_values[-1]
				if codec_level >= 0 and len(self._lossless_compression_values) > 1
				else -1
			)
		self.lossless_compression.SetSelection(
			self._lossless_compression_values.index(codec_level)
		)

	def _on_codec_changed(self, event):
		self._store_current_profile()
		self._current_format = FORMAT_KEYS[self.codec.GetSelection()]
		self._load_profile(self._current_format)

	def _update_control_state(self, event=None):
		stream_copy = self._current_format in STREAM_COPY_FORMATS
		self.enabled.Enable(not stream_copy)
		enabled = self.enabled.IsChecked() and not stream_copy
		self.bitrate.Enable(enabled and self._current_format in self._BITRATE_FORMATS)
		self.sample_rate.Enable(enabled and self._current_format not in {"amr", "amrwb", "opus"})
		self.channels.Enable(enabled and self._current_format not in {"amr", "amrwb"})
		self.codec_level.Enable(
			enabled and self._current_format in self._NUMERIC_LEVEL_FORMATS
		)
		self.lossless_compression.Enable(
			enabled and self._current_format in self._LOSSLESS_COMPRESSION_FORMATS
		)
		self.bit_depth.Enable(enabled and self._current_format in self._BIT_DEPTH_FORMATS)
		level_descriptions = {
			"mp3": _("For LAME MP3, level 0 is the slowest and highest algorithm quality; 9 is fastest."),
			"flac": _(
				"All FLAC levels are lossless. Level 0 is fastest; level 12 gives "
				"the strongest compression but is very slow."
			),
			"ogg": _("For Ogg Vorbis, levels 0 to 10 select increasing variable-bitrate quality."),
			"opus": _("For Opus, levels 0 to 10 select increasing encoder complexity."),
			"wavpack": _(
				"WavPack profiles use FFmpeg levels 0 to 8. Level 8 corresponds "
				"to -hhx6 and is extremely slow."
			),
		}
		self.level_help.SetLabel(
			_(
				"No advanced codec settings are used because the audio stream "
				"is copied without re-encoding.",
			)
			if stream_copy
			else level_descriptions.get(
				self._current_format,
				_("The codec-specific level is not used by this format."),
			)
		)
		self.level_help.Wrap(max(300, self.GetClientSize().GetWidth() - 20))

	def onSave(self):
		self._store_current_profile()
		config.conf[CONFIG_SECTION]["advancedProfiles"] = json.dumps(
			self._profiles,
			ensure_ascii=True,
			sort_keys=True,
			separators=(",", ":"),
		)


class _SettingsNotebookAccessible(wx.Accessible):
	"""Correct wx.Notebook's inflated MSAA child count on Windows."""

	def GetChildCount(self):
		return (wx.ACC_OK, self.Window.GetPageCount())


class EasyAudioConverterSettingsDialog(wx.Dialog):
	"""Standalone tabbed settings dialog opened from NVDA's Tools menu."""

	# Translators: Title of the standalone add-on settings dialog.
	title = _("Easy Audio Converter settings")
	STANDARD_TAB = 0
	ADVANCED_TAB = 1
	PROCESSING_TAB = 2
	shouldSuspendConfigProfileTriggers = True

	def __init__(self, parent, initial_tab: int = STANDARD_TAB):
		super().__init__(
			parent,
			title=self.title,
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		valid_tabs = (self.STANDARD_TAB, self.ADVANCED_TAB, self.PROCESSING_TAB)
		initial_tab = initial_tab if initial_tab in valid_tabs else self.STANDARD_TAB

		outer = wx.BoxSizer(wx.VERTICAL)
		self.notebook = wx.Notebook(self)
		self.standard_page = self._add_scrolled_page(
			_EasyAudioConverterStandardSettingsPage
		)
		self.advanced_page = self._add_scrolled_page(
			_EasyAudioConverterAdvancedSettingsPage
		)
		self.processing_page = self._add_scrolled_page(
			_EasyAudioConverterProcessingSettingsPage
		)
		self.notebook.SetAccessible(_SettingsNotebookAccessible(self.notebook))
		self.notebook.SetSelection(initial_tab)
		self.notebook.SetMinSize((620, 400))
		outer.Add(self.notebook, 1, wx.ALL | wx.EXPAND, 8)

		buttons = wx.StdDialogButtonSizer()
		self.ok_button = wx.Button(self, wx.ID_OK)
		self.cancel_button = wx.Button(self, wx.ID_CANCEL)
		buttons.AddButton(self.ok_button)
		buttons.AddButton(self.cancel_button)
		buttons.Realize()
		outer.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_RIGHT, 8)
		self.SetSizer(outer)
		self.SetMinSize((660, 500))
		self.SetSize((820, 680))
		self.CentreOnParent()
		self.ok_button.SetDefault()
		self.ok_button.Bind(wx.EVT_BUTTON, self._on_ok)
		wx.CallAfter(self.notebook.SetFocus)

	def _add_scrolled_page(self, page_class: type[SettingsPanel]) -> SettingsPanel:
		container = scrolledpanel.ScrolledPanel(
			self.notebook,
			style=wx.TAB_TRAVERSAL | wx.BORDER_NONE,
		)
		container.SetMinSize((1, 1))
		page = page_class(container)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(page, 1, wx.ALL | wx.EXPAND, 8)
		container.SetSizer(sizer)
		container.SetupScrolling(scroll_x=False)
		self.notebook.AddPage(container, page.title)
		return page

	def _on_ok(self, event) -> None:
		if not self.standard_page.isValid():
			self.notebook.SetSelection(self.STANDARD_TAB)
			wx.CallAfter(self.standard_page.output_name_template.SetFocus)
			return
		try:
			self.standard_page.onSave()
			self.advanced_page.onSave()
			self.processing_page.onSave()
			config.conf.save()
		except Exception:
			log.error(
				"Easy Audio Converter: could not save settings",
				exc_info=True,
			)
			gui.messageBox(
				_("Could not save Easy Audio Converter settings. See the NVDA log for details."),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		self.EndModal(wx.ID_OK)


class MetadataFieldsDialog(wx.Dialog):
	"""Accessible individual check boxes for one job's metadata selection."""

	def __init__(self, parent, selected_fields: tuple[str, ...]):
		super().__init__(
			parent,
			title=_("Choose metadata fields"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(
			wx.StaticText(
				panel,
				label=_("Select the text metadata fields to copy for this conversion."),
			),
			0,
			wx.ALL | wx.EXPAND,
			8,
		)
		self._checkboxes: list[wx.CheckBox] = []
		field_labels = _metadata_field_labels()
		for field_name in METADATA_FIELD_KEYS:
			checkbox = wx.CheckBox(panel, label=field_labels[field_name])
			checkbox.SetValue(field_name in selected_fields)
			sizer.Add(checkbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
			self._checkboxes.append(checkbox)
		buttons = wx.StdDialogButtonSizer()
		buttons.AddButton(wx.Button(panel, wx.ID_OK))
		buttons.AddButton(wx.Button(panel, wx.ID_CANCEL))
		buttons.Realize()
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizerAndFit(outer)
		self.SetMinSize((460, self.GetSize().height))
		self.CentreOnParent()

	def selected_fields(self) -> tuple[str, ...]:
		return tuple(
			field_name
			for field_name, checkbox in zip(METADATA_FIELD_KEYS, self._checkboxes)
			if checkbox.IsChecked()
		)


class MetadataOverridesDialog(wx.Dialog):
	"""Dostępny edytor tagów stosowanych do każdego wyniku zadania."""

	def __init__(self, parent, overrides: Mapping[str, str] | None):
		super().__init__(
			parent,
			title=_("Edit metadata overrides"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(
			wx.StaticText(
				panel,
				label=(
					_(
						"Enter values to replace source tags for every converted file. "
						"Leave a field empty to keep its source value."
					)
				),
			),
			0,
			wx.ALL | wx.EXPAND,
			8,
		)
		content = scrolledpanel.ScrolledPanel(panel, style=wx.TAB_TRAVERSAL)
		content_sizer = wx.FlexGridSizer(0, 2, 8, 10)
		content_sizer.AddGrowableCol(1, 1)
		self._controls: dict[str, wx.TextCtrl] = {}
		field_labels = _metadata_field_labels()
		overrides = normalize_metadata_overrides(overrides)
		multiline_fields = {"comment", "lyrics", "description"}
		for field_name in METADATA_FIELD_KEYS:
			label = wx.StaticText(content, label=field_labels[field_name])
			style = wx.TE_MULTILINE if field_name in multiline_fields else 0
			control = wx.TextCtrl(
				content,
				value=overrides.get(field_name, ""),
				style=style,
			)
			control.SetName(field_labels[field_name])
			if style:
				control.SetMinSize((360, 58))
			content_sizer.Add(label, 0, wx.ALIGN_TOP | wx.ALIGN_LEFT)
			content_sizer.Add(control, 1, wx.EXPAND)
			self._controls[field_name] = control
		content.SetSizer(content_sizer)
		content.SetupScrolling(scroll_x=False)
		sizer.Add(content, 1, wx.ALL | wx.EXPAND, 8)
		buttons = wx.StdDialogButtonSizer()
		buttons.AddButton(wx.Button(panel, wx.ID_OK))
		buttons.AddButton(wx.Button(panel, wx.ID_CANCEL))
		buttons.Realize()
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizerAndFit(outer)
		self.SetSize((700, 650))
		self.SetMinSize((560, 420))
		self.CentreOnParent()

	def values(self) -> dict[str, str]:
		return normalize_metadata_overrides(
			{
				field_name: control.GetValue()
				for field_name, control in self._controls.items()
			}
		)


class JobProcessingOptionsDialog(wx.Dialog):
	"""One-job loudness, stream-copy and verification options."""

	def __init__(self, parent, settings: ConversionSettings):
		super().__init__(
			parent,
			title=_("Processing options"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		helper = guiHelper.BoxSizerHelper(panel, sizer=sizer)
		self._target_format = settings.target_format
		self.stream_copy_note = helper.addItem(
			wx.StaticText(panel, label=_stream_copy_description(settings.target_format))
		)
		self.stream_copy_note.Show(settings.target_format in STREAM_COPY_FORMATS)
		labels = _loudness_preset_labels()
		self.loudness_preset = helper.addLabeledControl(
			_("Loudness normalization:"),
			wx.Choice,
			choices=[labels[key] for key in LOUDNESS_PRESET_KEYS],
		)
		self.loudness_preset.SetSelection(
			LOUDNESS_PRESET_KEYS.index(settings.loudness_preset)
		)
		self.target_i = _add_labeled_spin_double(
			helper,
			panel,
			_("Custom integrated loudness in LUFS:"),
			minimum=-70.0,
			maximum=-5.0,
			initial=settings.loudness_target_i,
			increment=0.5,
		)
		self.target_tp = _add_labeled_spin_double(
			helper,
			panel,
			_("Custom true peak in dBTP:"),
			minimum=-9.0,
			maximum=0.0,
			initial=settings.loudness_target_tp,
			increment=0.1,
		)
		self.target_lra = _add_labeled_spin_double(
			helper,
			panel,
			_("Custom loudness range in LU:"),
			minimum=1.0,
			maximum=50.0,
			initial=settings.loudness_target_lra,
			increment=0.5,
		)
		self.copy_artwork = helper.addItem(
			wx.CheckBox(panel, label=_("Copy embedded cover artwork when supported"))
		)
		self.copy_artwork.SetValue(settings.copy_artwork)
		self.copy_chapters = helper.addItem(
			wx.CheckBox(panel, label=_("Copy chapter markers"))
		)
		self.copy_chapters.SetValue(settings.copy_chapters)
		self.verify_output = helper.addItem(
			wx.CheckBox(panel, label=_("Deeply verify every output file"))
		)
		self.verify_output.SetValue(settings.verify_output)
		parallel_labels = _parallel_job_labels()
		self.parallel_jobs = helper.addLabeledControl(
			_("Parallel conversion jobs:"),
			wx.Choice,
			choices=[parallel_labels[key] for key in PARALLEL_JOB_COUNTS],
		)
		self.parallel_jobs.SetSelection(
			PARALLEL_JOB_COUNTS.index(settings.parallel_jobs)
			if settings.parallel_jobs in PARALLEL_JOB_COUNTS
			else 0
		)
		helper.addItem(
			wx.StaticText(
				panel,
				label=_(
					"Automatic mode dynamically adjusts independent files using CPU and memory load."
				),
			)
		)
		self.show_preflight = helper.addItem(
			wx.CheckBox(panel, label=_("Show the conversion plan before starting"))
		)
		self.show_preflight.SetValue(settings.show_preflight)

		buttons = wx.StdDialogButtonSizer()
		buttons.AddButton(wx.Button(panel, wx.ID_OK))
		buttons.AddButton(wx.Button(panel, wx.ID_CANCEL))
		buttons.Realize()
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizerAndFit(outer)
		self.SetMinSize((560, self.GetSize().height))
		self.CentreOnParent()
		self.loudness_preset.Bind(wx.EVT_CHOICE, self._update_control_state)
		self._update_control_state()

	def _update_control_state(self, event=None):
		stream_copy = self._target_format in STREAM_COPY_FORMATS
		self.loudness_preset.Enable(not stream_copy)
		custom = (
			not stream_copy
			and
			LOUDNESS_PRESET_KEYS[max(0, self.loudness_preset.GetSelection())] == "custom"
		)
		for control in (self.target_i, self.target_tp, self.target_lra):
			control.Enable(custom)
		preserve_extra_streams = self._target_format != ORIGINAL_AUDIO_COPY_FORMAT
		self.copy_artwork.Enable(preserve_extra_streams)
		self.copy_chapters.Enable(preserve_extra_streams)
		if event is not None:
			event.Skip()

	def apply_to(self, settings: ConversionSettings) -> ConversionSettings:
		stream_copy = self._target_format in STREAM_COPY_FORMATS
		preserve_extra_streams = self._target_format != ORIGINAL_AUDIO_COPY_FORMAT
		return replace(
			settings,
			loudness_preset=(
				"off"
				if stream_copy
				else LOUDNESS_PRESET_KEYS[
					max(0, self.loudness_preset.GetSelection())
				]
			),
			loudness_target_i=float(self.target_i.GetValue()),
			loudness_target_tp=float(self.target_tp.GetValue()),
			loudness_target_lra=float(self.target_lra.GetValue()),
			copy_artwork=self.copy_artwork.IsChecked() and preserve_extra_streams,
			copy_chapters=self.copy_chapters.IsChecked() and preserve_extra_streams,
			verify_output=self.verify_output.IsChecked(),
			show_preflight=self.show_preflight.IsChecked(),
			parallel_jobs=PARALLEL_JOB_COUNTS[max(0, self.parallel_jobs.GetSelection())],
		)


class ConversionOptionsDialog(wx.Dialog):
	"""Choose one-time job settings and manage complete named profiles."""

	def __init__(
		self,
		parent,
		*,
		item_count: int,
		initial_settings: ConversionSettings,
		preview_source: str | None = None,
	):
		super().__init__(
			parent,
			title=_("Convert with options"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._updating = True
		self._one_time_settings = initial_settings
		self._advanced_options = dict(initial_settings.advanced_options)
		self._metadata_fields = tuple(initial_settings.metadata_fields)
		self._metadata_overrides = dict(initial_settings.metadata_overrides)
		self._processing_settings = initial_settings
		self._preview_source = Path(preview_source) if preview_source else Path("Example source.wav")
		self._builtin_profiles = _builtin_conversion_profiles(initial_settings)
		self._user_profiles = _load_user_conversion_profiles(initial_settings)
		self._profile_entries: list[tuple[str, NamedConversionProfile | None]] = []

		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		helper = guiHelper.BoxSizerHelper(panel, sizer=sizer)
		helper.addItem(
			wx.StaticText(
				panel,
				label=_("Selected items: {count}").format(count=item_count),
			)
		)

		self.profile = helper.addLabeledControl(
			_("Conversion profile:"),
			wx.Choice,
			choices=[],
		)
		profile_buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.save_profile_button = wx.Button(panel, label=_("Save profile..."))
		self.delete_profile_button = wx.Button(panel, label=_("Delete profile"))
		self.import_profiles_button = wx.Button(panel, label=_("Import profiles..."))
		self.export_profiles_button = wx.Button(panel, label=_("Export profiles..."))
		profile_buttons.Add(self.save_profile_button, 0, wx.RIGHT, 8)
		profile_buttons.Add(self.delete_profile_button, 0, wx.RIGHT, 8)
		profile_buttons.Add(self.import_profiles_button, 0, wx.RIGHT, 8)
		profile_buttons.Add(self.export_profiles_button, 0)
		helper.addItem(profile_buttons)

		format_labels = _format_labels()
		self.target_format = helper.addLabeledControl(
			_("Target format:"),
			wx.Choice,
			choices=[format_labels[key] for key in FORMAT_KEYS],
		)
		quality_labels = _quality_labels()
		self.quality = helper.addLabeledControl(
			_("Quality:"),
			wx.Choice,
			choices=[quality_labels[key] for key in QUALITY_KEYS],
		)
		encoder_labels = _mp3_encoder_labels()
		self.mp3_encoder = helper.addLabeledControl(
			_("MP3 encoder:"),
			wx.Choice,
			choices=[encoder_labels[key] for key in MP3_ENCODER_KEYS],
		)

		self.same_folder = helper.addItem(
			wx.CheckBox(panel, label=_("Save converted files next to the source files"))
		)
		self.output_folder = helper.addLabeledControl(
			_("Destination folder:"),
			wx.TextCtrl,
		)
		self.browse_button = helper.addItem(
			wx.Button(panel, label=_("Browse...")),
		)
		self.output_name_template = helper.addLabeledControl(
			_("Output filename template:"),
			wx.TextCtrl,
		)
		self.name_preview = helper.addItem(wx.StaticText(panel, label=""))
		self.include_subfolders = helper.addItem(
			wx.CheckBox(panel, label=_("Include subfolders when converting a folder"))
		)
		self.preserve_structure = helper.addItem(
			wx.CheckBox(
				panel,
				label=_("Preserve the source folder structure in the destination"),
			)
		)
		self.preserve_timestamps = helper.addItem(
			wx.CheckBox(
				panel,
				label=_("Preserve source file creation and modification dates"),
			)
		)
		self.replace_source_files = helper.addItem(
			wx.CheckBox(
				panel,
				label=_(
					"Replace source files after successful conversion "
					"(permanently deletes originals)",
				),
			)
		)

		metadata_labels = _metadata_mode_labels()
		self.metadata_mode = helper.addLabeledControl(
			_("Metadata export:"),
			wx.Choice,
			choices=[metadata_labels[key] for key in METADATA_MODE_KEYS],
		)
		self.metadata_fields_button = helper.addItem(
			wx.Button(panel, label=_("Choose metadata fields...")),
		)
		self.metadata_overrides_button = helper.addItem(
			wx.Button(panel, label=_("Edit metadata overrides...")),
		)
		self.metadata_overrides_summary = helper.addItem(wx.StaticText(panel, label=""))
		self.advanced_status = helper.addItem(wx.StaticText(panel, label=""))
		self.processing_status = helper.addItem(wx.StaticText(panel, label=""))
		self.processing_options_button = helper.addItem(
			wx.Button(panel, label=_("Processing options..."))
		)
		self.save_as_defaults = helper.addItem(
			wx.CheckBox(
				panel,
				label=_("Use these settings for future quick conversions"),
			)
		)

		buttons = wx.StdDialogButtonSizer()
		buttons.AddButton(wx.Button(panel, wx.ID_OK))
		buttons.AddButton(wx.Button(panel, wx.ID_CANCEL))
		buttons.Realize()
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizerAndFit(outer)
		self.SetMinSize((780, self.GetSize().height))
		self.CentreOnParent()
		ok_button = self.FindWindowById(wx.ID_OK)
		if ok_button is not None:
			ok_button.SetLabel(_("Convert"))
			ok_button.SetDefault()

		self._rebuild_profile_choice()
		self._apply_settings(initial_settings)
		self._updating = False
		self.profile.Bind(wx.EVT_CHOICE, self._on_profile_changed)
		self.save_profile_button.Bind(wx.EVT_BUTTON, self._on_save_profile)
		self.delete_profile_button.Bind(wx.EVT_BUTTON, self._on_delete_profile)
		self.import_profiles_button.Bind(wx.EVT_BUTTON, self._on_import_profiles)
		self.export_profiles_button.Bind(wx.EVT_BUTTON, self._on_export_profiles)
		self.target_format.Bind(wx.EVT_CHOICE, self._on_target_changed)
		self.quality.Bind(wx.EVT_CHOICE, self._on_setting_changed)
		self.mp3_encoder.Bind(wx.EVT_CHOICE, self._on_setting_changed)
		self.same_folder.Bind(wx.EVT_CHECKBOX, self._on_setting_changed)
		self.output_folder.Bind(wx.EVT_TEXT, self._on_setting_changed)
		self.output_name_template.Bind(wx.EVT_TEXT, self._on_setting_changed)
		self.include_subfolders.Bind(wx.EVT_CHECKBOX, self._on_setting_changed)
		self.preserve_structure.Bind(wx.EVT_CHECKBOX, self._on_setting_changed)
		self.preserve_timestamps.Bind(wx.EVT_CHECKBOX, self._on_setting_changed)
		self.replace_source_files.Bind(wx.EVT_CHECKBOX, self._on_setting_changed)
		self.metadata_mode.Bind(wx.EVT_CHOICE, self._on_setting_changed)
		self.browse_button.Bind(wx.EVT_BUTTON, self._on_browse)
		self.metadata_fields_button.Bind(wx.EVT_BUTTON, self._on_metadata_fields)
		self.metadata_overrides_button.Bind(wx.EVT_BUTTON, self._on_metadata_overrides)
		self.processing_options_button.Bind(wx.EVT_BUTTON, self._on_processing_options)
		self.Bind(wx.EVT_BUTTON, self._on_convert, id=wx.ID_OK)
		self._update_control_state()

	def _rebuild_profile_choice(self, selected_name: str | None = None) -> None:
		self._profile_entries = [("oneTime", None)]
		self._profile_entries.extend(("builtin", profile) for profile in self._builtin_profiles)
		self._profile_entries.extend(("user", profile) for profile in self._user_profiles)
		self.profile.Clear()
		self.profile.AppendItems(
			[_("One-time settings")]
			+ [profile.name for profile in self._builtin_profiles]
			+ [profile.name for profile in self._user_profiles]
		)
		selection = 0
		if selected_name:
			for index, (profile_type, profile) in enumerate(self._profile_entries):
				if (
					profile_type == "user"
					and profile is not None
					and profile.name.casefold() == selected_name.casefold()
				):
					selection = index
					break
		self.profile.SetSelection(selection)
		self._update_delete_profile_state()

	def _update_delete_profile_state(self) -> None:
		selection = self.profile.GetSelection()
		can_delete = (
			0 <= selection < len(self._profile_entries)
			and self._profile_entries[selection][0] == "user"
		)
		self.delete_profile_button.Enable(can_delete)

	def _apply_settings(self, settings: ConversionSettings) -> None:
		self._updating = True
		try:
			self.target_format.SetSelection(FORMAT_KEYS.index(settings.target_format))
			self.quality.SetSelection(QUALITY_KEYS.index(settings.quality))
			self.mp3_encoder.SetSelection(MP3_ENCODER_KEYS.index(settings.mp3_encoder))
			self.same_folder.SetValue(settings.same_folder)
			self.output_folder.SetValue(settings.output_folder or _default_output_folder())
			self.output_name_template.SetValue(settings.output_name_template)
			self.include_subfolders.SetValue(settings.include_subfolders)
			self.preserve_structure.SetValue(settings.preserve_folder_structure)
			self.preserve_timestamps.SetValue(settings.preserve_timestamps)
			self.replace_source_files.SetValue(settings.replace_source_files)
			self.metadata_mode.SetSelection(METADATA_MODE_KEYS.index(settings.metadata_mode))
			self._metadata_fields = tuple(settings.metadata_fields)
			self._metadata_overrides = dict(settings.metadata_overrides)
			self._advanced_options = dict(settings.advanced_options)
			self._processing_settings = settings
			self._update_control_state()
		finally:
			self._updating = False

	def _capture_settings(self) -> ConversionSettings:
		target_format = FORMAT_KEYS[max(0, self.target_format.GetSelection())]
		stream_copy = target_format in STREAM_COPY_FORMATS
		preserve_extra_streams = target_format != ORIGINAL_AUDIO_COPY_FORMAT
		advanced_options = dict(self._advanced_options)
		if stream_copy:
			advanced_options["enabled"] = False
		settings = replace(
			self._processing_settings,
			target_format=target_format,
			quality=QUALITY_KEYS[max(0, self.quality.GetSelection())],
			mp3_encoder=MP3_ENCODER_KEYS[max(0, self.mp3_encoder.GetSelection())],
			same_folder=self.same_folder.IsChecked(),
			output_folder=self.output_folder.GetValue().strip() or _default_output_folder(),
			include_subfolders=self.include_subfolders.IsChecked(),
			preserve_folder_structure=self.preserve_structure.IsChecked(),
			preserve_timestamps=self.preserve_timestamps.IsChecked(),
			replace_source_files=self.replace_source_files.IsChecked(),
			metadata_mode=METADATA_MODE_KEYS[max(0, self.metadata_mode.GetSelection())],
			metadata_fields=self._metadata_fields,
			metadata_overrides=self._metadata_overrides,
			advanced_options=advanced_options,
			output_name_template=self.output_name_template.GetValue().strip(),
			loudness_preset=(
				"off" if stream_copy else self._processing_settings.loudness_preset
			),
			copy_artwork=(
				self._processing_settings.copy_artwork and preserve_extra_streams
			),
			copy_chapters=(
				self._processing_settings.copy_chapters and preserve_extra_streams
			),
		)
		settings.validate()
		return settings

	def get_settings(self) -> ConversionSettings:
		return self._capture_settings()

	def _mark_as_one_time(self) -> None:
		if self._updating:
			return
		try:
			self._one_time_settings = self._capture_settings()
		except ValueError:
			return
		self.profile.SetSelection(0)
		self._update_delete_profile_state()

	def _update_control_state(self) -> None:
		target_format = FORMAT_KEYS[max(0, self.target_format.GetSelection())]
		stream_copy = target_format in STREAM_COPY_FORMATS
		original_stream = target_format == ORIGINAL_AUDIO_COPY_FORMAT
		self.quality.Enable(not stream_copy)
		self.mp3_encoder.Enable(target_format == "mp3")
		use_destination = not self.same_folder.IsChecked()
		self.output_folder.Enable(use_destination)
		self.browse_button.Enable(use_destination)
		self.preserve_structure.Enable(use_destination)
		self.metadata_mode.Enable(not original_stream)
		selected_metadata = (
			not original_stream
			and METADATA_MODE_KEYS[max(0, self.metadata_mode.GetSelection())] == "selected"
		)
		self.metadata_fields_button.Enable(selected_metadata)
		self.metadata_overrides_button.Enable(True)
		self.metadata_overrides_summary.SetLabel(
			_("Metadata overrides: {count} fields").format(
				count=len(self._metadata_overrides)
			)
		)
		advanced_enabled = bool(self._advanced_options.get("enabled", False))
		self.advanced_status.SetLabel(
			_("Advanced codec overrides are not used for stream copy")
			if stream_copy
			else (
				_("Advanced codec overrides: enabled")
				if advanced_enabled
				else _("Advanced codec overrides: disabled")
			)
		)
		try:
			preview = render_output_name(
				self.output_name_template.GetValue(),
				self._preview_source,
				target_format,
				self._metadata_overrides,
				index=1,
			)
			self.name_preview.SetLabel(
				_("Filename preview: {name}").format(
					name=_output_name_preview(target_format, preview),
				)
			)
		except ValueError as error:
			self.name_preview.SetLabel(
				_("Invalid filename template: {error}").format(error=error)
			)
		if stream_copy:
			self.processing_status.SetLabel(
				_(
					"No re-encoding: quality, loudness, source metadata, artwork, "
					"chapters, and advanced codec settings are not used. Explicit "
					"metadata overrides are still applied.",
				)
				if original_stream
				else _(
					"No re-encoding: quality, loudness, and advanced codec "
					"settings are not used.",
				)
			)
		else:
			loudness_label = _loudness_preset_labels()[
				self._processing_settings.loudness_preset
			]
			self.processing_status.SetLabel(
				_(
					"Processing: loudness {loudness}; artwork {artwork}; "
					"chapters {chapters}; verification {verification}.",
				).format(
					loudness=loudness_label,
					artwork=_("on") if self._processing_settings.copy_artwork else _("off"),
					chapters=_("on") if self._processing_settings.copy_chapters else _("off"),
					verification=_("on") if self._processing_settings.verify_output else _("off"),
				)
			)
		self.Layout()

	def _on_setting_changed(self, event) -> None:
		self._update_control_state()
		self._mark_as_one_time()
		event.Skip()

	def _on_target_changed(self, event) -> None:
		target_format = FORMAT_KEYS[max(0, self.target_format.GetSelection())]
		self._advanced_options = _load_advanced_profiles().get(
			target_format,
			_default_advanced_profile(),
		)
		self._update_control_state()
		self._mark_as_one_time()
		event.Skip()

	def _on_profile_changed(self, event) -> None:
		selection = self.profile.GetSelection()
		if not 0 <= selection < len(self._profile_entries):
			return
		_profile_type, profile = self._profile_entries[selection]
		settings = self._one_time_settings if profile is None else profile.settings
		self._apply_settings(settings)
		self._update_delete_profile_state()
		event.Skip()

	def _on_browse(self, event) -> None:
		dialog = wx.DirDialog(
			self,
			_("Choose the destination folder"),
			defaultPath=self.output_folder.GetValue().strip() or _default_output_folder(),
			style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
		)
		try:
			if dialog.ShowModal() == wx.ID_OK:
				self.output_folder.SetValue(dialog.GetPath())
		finally:
			dialog.Destroy()

	def _on_metadata_fields(self, event) -> None:
		dialog = MetadataFieldsDialog(self, self._metadata_fields)
		try:
			if dialog.ShowModal() == wx.ID_OK:
				self._metadata_fields = dialog.selected_fields()
				self._mark_as_one_time()
		finally:
			dialog.Destroy()

	def _on_metadata_overrides(self, event) -> None:
		dialog = MetadataOverridesDialog(self, self._metadata_overrides)
		try:
			if dialog.ShowModal() == wx.ID_OK:
				self._metadata_overrides = dialog.values()
				self._update_control_state()
				self._mark_as_one_time()
		finally:
			dialog.Destroy()

	def _on_processing_options(self, event) -> None:
		try:
			current = self._capture_settings()
		except ValueError as error:
			gui.messageBox(
				str(error),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		dialog = JobProcessingOptionsDialog(self, current)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			self._processing_settings = dialog.apply_to(current)
		finally:
			dialog.Destroy()
		self._update_control_state()
		self._mark_as_one_time()

	def _on_import_profiles(self, event) -> None:
		dialog = wx.FileDialog(
			self,
			_("Import conversion profiles"),
			wildcard=_("JSON profile files (*.json)|*.json|All files (*.*)|*.*"),
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
		)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			path = Path(dialog.GetPath())
		finally:
			dialog.Destroy()
		try:
			if path.stat().st_size > MAX_PROFILE_DOCUMENT_BYTES:
				raise ValueError(_("The profile file is too large."))
			document = path.read_text(encoding="utf-8")
			imported = load_user_profiles(
				document,
				fallback=self._capture_settings(),
			)
			builtin_names = {
				profile.name.casefold()
				for profile in self._builtin_profiles
			}
			imported = [
				profile
				for profile in imported
				if profile.name.casefold() not in builtin_names
			]
			if not imported:
				raise ValueError(_("The file does not contain valid conversion profiles."))
			self._user_profiles = merge_user_profiles(self._user_profiles, imported)
		except (OSError, UnicodeError, ValueError) as error:
			gui.messageBox(
				_("Could not import profiles:\n{error}").format(error=error),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		_save_user_conversion_profiles(self._user_profiles)
		self._rebuild_profile_choice()
		self._apply_settings(self._one_time_settings)
		ui.message(
			_("Imported {count} conversion profiles").format(count=len(imported))
		)

	def _on_export_profiles(self, event) -> None:
		if not self._user_profiles:
			ui.message(_("There are no user profiles to export"))
			return
		dialog = wx.FileDialog(
			self,
			_("Export conversion profiles"),
			defaultFile="easy-audio-converter-profiles.json",
			wildcard=_("JSON profile files (*.json)|*.json|All files (*.*)|*.*"),
			style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
		)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			path = Path(dialog.GetPath())
		finally:
			dialog.Destroy()
		try:
			path.write_text(
				dump_user_profiles(self._user_profiles),
				encoding="utf-8",
				newline="\n",
			)
		except OSError as error:
			gui.messageBox(
				_("Could not export profiles:\n{error}").format(error=error),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		ui.message(_("Conversion profiles exported"))

	def _on_save_profile(self, event) -> None:
		try:
			settings = self._capture_settings()
		except ValueError as error:
			gui.messageBox(
				str(error),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		default_name = ""
		selection = self.profile.GetSelection()
		if 0 <= selection < len(self._profile_entries):
			profile_type, selected_profile = self._profile_entries[selection]
			if profile_type == "user" and selected_profile is not None:
				default_name = selected_profile.name
		dialog = wx.TextEntryDialog(
			self,
			_("Enter a name for this conversion profile:"),
			_("Save conversion profile"),
			value=default_name,
		)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			name = normalize_profile_name(dialog.GetValue())
		finally:
			dialog.Destroy()
		if not name:
			gui.messageBox(
				_("The profile name cannot be empty."),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		if any(profile.name.casefold() == name.casefold() for profile in self._builtin_profiles):
			gui.messageBox(
				_("A built-in profile already uses this name."),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		existing = next(
			(
				profile
				for profile in self._user_profiles
				if profile.name.casefold() == name.casefold()
			),
			None,
		)
		if existing is not None:
			result = gui.messageBox(
				_("Replace the existing profile “{name}”?").format(name=existing.name),
				_("Save conversion profile"),
				wx.YES_NO | getattr(wx, "NO_DEFAULT", 0) | wx.ICON_QUESTION,
				self,
			)
			if result != wx.YES:
				return
		try:
			self._user_profiles = upsert_user_profile(
				self._user_profiles,
				NamedConversionProfile(name, settings),
			)
		except ValueError as error:
			gui.messageBox(
				str(error),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		_save_user_conversion_profiles(self._user_profiles)
		self._rebuild_profile_choice(name)
		ui.message(_("Profile saved: {name}").format(name=name))

	def _on_delete_profile(self, event) -> None:
		selection = self.profile.GetSelection()
		if not 0 <= selection < len(self._profile_entries):
			return
		profile_type, profile = self._profile_entries[selection]
		if profile_type != "user" or profile is None:
			return
		result = gui.messageBox(
			_("Delete the profile “{name}”?").format(name=profile.name),
			_("Delete conversion profile"),
			wx.YES_NO | getattr(wx, "NO_DEFAULT", 0) | wx.ICON_WARNING,
			self,
		)
		if result != wx.YES:
			return
		self._user_profiles = remove_user_profile(self._user_profiles, profile.name)
		_save_user_conversion_profiles(self._user_profiles)
		self._rebuild_profile_choice()
		self._apply_settings(self._one_time_settings)
		ui.message(_("Profile deleted"))

	def _on_convert(self, event) -> None:
		try:
			settings = self._capture_settings()
		except ValueError as error:
			gui.messageBox(
				str(error),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		if self.save_as_defaults.IsChecked():
			_write_conversion_settings(settings)
			config.conf.save()
		self.EndModal(wx.ID_OK)


def _run_conversion_options_dialog(
	dialog: ConversionOptionsDialog,
) -> ConversionSettings | None:
	"""Run an NVDA-owned modal dialog and always restore popup state."""
	try:
		gui.mainFrame.prePopup()
		try:
			result = dialog.ShowModal()
		finally:
			gui.mainFrame.postPopup()
		if result != wx.ID_OK:
			return None
		return dialog.get_settings()
	finally:
		dialog.Destroy()


def _format_bytes(value: int | None) -> str:
	if value is None:
		return _("unknown")
	size = max(0.0, float(value))
	for unit in (_("bytes"), _("KB"), _("MB"), _("GB"), _("TB")):
		if size < 1024.0 or unit == _("TB"):
			return f"{size:.0f} {unit}" if unit == _("bytes") else f"{size:.1f} {unit}"
		size /= 1024.0
	return f"{size:.1f} TB"


def _build_plan_report(plan: ConversionPlan) -> str:
	lines = [
		_("Conversion plan"),
		_("Files to convert: {count}").format(count=plan.total),
		_("Skipped inputs: {count}").format(count=plan.ignored),
		_("Destination: {destination}").format(
			destination=plan.destination or _("source folders")
		),
		_("Input size: {size}").format(size=_format_bytes(plan.input_bytes)),
		_("Estimated output size: {size}").format(
			size=_format_bytes(plan.estimated_output_bytes)
		),
		_("Free disk space: {size}").format(size=_format_bytes(plan.free_space_bytes)),
		_("Total audio duration: {duration}").format(
			duration=(
				_format_elapsed(plan.total_duration)
				if plan.total_duration is not None
				else _("unknown")
			)
		),
	]
	if plan.replace_source_files:
		lines.append(
			_(
				"Warning: source files will be permanently deleted after "
				"successful conversion.",
			)
		)
	if plan.lossy_to_lossy_count:
		lines.append(
			_(
				"Warning: {count} files will be converted from a lossy format "
				"to another lossy format, which can reduce quality.",
			).format(count=plan.lossy_to_lossy_count)
		)
	if (
		plan.estimated_output_bytes is not None
		and plan.free_space_bytes is not None
		and plan.estimated_output_bytes > plan.free_space_bytes
	):
		lines.append(
			_("Warning: the estimated output is larger than the available disk space.")
		)
	if plan.items:
		lines.extend(("", _("Planned output files:")))
		for item in plan.items[:500]:
			lines.append(f"{item.source_path} -> {item.output_path}")
		if len(plan.items) > 500:
			lines.append(
				_("...and {count} more files").format(count=len(plan.items) - 500)
			)
	return "\n".join(lines)


class ConversionPlanDialog(wx.Dialog):
	"""Accessible confirmation of the exact files and output names."""

	def __init__(self, parent, plan: ConversionPlan):
		super().__init__(
			parent,
			title=_("Review conversion plan"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		if plan.replace_source_files:
			description = _(
				"Review the plan below. Size estimates are approximate. "
				"Source files will be permanently deleted after their outputs "
				"are completed successfully.",
			)
		else:
			description = _(
				"Review the plan below. Size estimates are approximate. "
				"No source file will be overwritten.",
			)
		description = f"{description}\n\n{CONVERSION_LIFECYCLE_WARNING}"
		sizer.Add(
			wx.StaticText(
				panel,
				label=description,
			),
			0,
			wx.ALL | wx.EXPAND,
			8,
		)
		self.report = wx.TextCtrl(
			panel,
			value=_build_plan_report(plan),
			style=wx.TE_MULTILINE | wx.TE_READONLY,
		)
		sizer.Add(self.report, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		buttons = wx.StdDialogButtonSizer()
		start_button = wx.Button(panel, wx.ID_OK, _("Start conversion"))
		cancel_button = wx.Button(panel, wx.ID_CANCEL)
		buttons.AddButton(start_button)
		buttons.AddButton(cancel_button)
		buttons.Realize()
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizer(outer)
		self.SetSize((820, 580))
		self.SetMinSize((620, 400))
		self.CentreOnParent()
		start_button.SetDefault()
		self.report.SetInsertionPoint(0)


def _build_media_info_report(info: MediaInfo) -> str:
	lines = [
		_("Audio file information"),
		_("Path: {path}").format(path=info.source_path),
		_("Container: {value}").format(value=info.container or _("unknown")),
		_("Audio codec: {value}").format(value=info.codec or _("unknown")),
		_("Duration: {value}").format(
			value=_format_elapsed(info.duration) if info.duration is not None else _("unknown")
		),
		_("Bitrate: {value}").format(
			value=(
				_("{value} kbps").format(value=info.bitrate_kbps)
				if info.bitrate_kbps is not None
				else _("unknown")
			)
		),
		_("Channels: {value}").format(value=info.channels or _("unknown")),
		_("Sample rate: {value}").format(
			value=(
				_("{value} Hz").format(value=info.sample_rate)
				if info.sample_rate is not None
				else _("unknown")
			)
		),
		_("File size: {value}").format(value=_format_bytes(info.size_bytes)),
		_("Embedded artwork: {value}").format(
			value=_("yes") if info.has_artwork else _("no")
		),
		_("Chapters: {value}").format(value=info.chapter_count),
	]
	if info.metadata:
		lines.extend(("", _("Metadata:")))
		labels = _metadata_field_labels()
		for key, value in sorted(info.metadata.items()):
			lines.append(f"{labels.get(key, key)}: {value}")
	return "\n".join(lines)


class AudioInfoDialog(wx.Dialog):
	"""Modeless, copyable technical information for a selected audio file."""

	def __init__(self, parent, info: MediaInfo):
		super().__init__(
			parent,
			title=_("Audio file information"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._report = _build_media_info_report(info)
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.details = wx.TextCtrl(
			panel,
			value=self._report,
			style=wx.TE_MULTILINE | wx.TE_READONLY,
		)
		sizer.Add(self.details, 1, wx.ALL | wx.EXPAND, 8)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		copy_button = wx.Button(panel, label=_("Copy information"))
		close_button = wx.Button(panel, wx.ID_CLOSE, _("Close"))
		buttons.Add(copy_button, 0, wx.RIGHT, 8)
		buttons.Add(close_button, 0)
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizer(outer)
		self.SetSize((700, 500))
		self.SetMinSize((520, 360))
		self.CentreOnParent()
		copy_button.Bind(wx.EVT_BUTTON, self._on_copy)
		close_button.Bind(wx.EVT_BUTTON, lambda event: self.Hide())
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self.details.SetInsertionPoint(0)

	def _on_copy(self, event):
		try:
			if api.copyToClip(self._report) is False:
				raise RuntimeError
		except Exception:
			ui.message(_("Could not copy the audio information"))
		else:
			ui.message(_("Audio information copied"))

	def _on_close(self, event):
		self.Hide()
		if event.CanVeto():
			event.Veto()


def _format_elapsed(seconds: float | None) -> str:
	seconds = max(0, int(seconds or 0))
	hours, remainder = divmod(seconds, 3600)
	minutes, seconds = divmod(remainder, 60)
	if hours:
		return f"{hours:d}:{minutes:02d}:{seconds:02d}"
	return f"{minutes:d}:{seconds:02d}"


def _estimate_remaining(elapsed_seconds: float, overall_fraction: float) -> float | None:
	"""Estimate remaining time from stable, bounded overall progress."""
	elapsed_seconds = max(0.0, float(elapsed_seconds))
	overall_fraction = max(0.0, min(1.0, float(overall_fraction)))
	if overall_fraction >= 1.0:
		return 0.0
	if elapsed_seconds < 2.0 or overall_fraction < 0.01:
		return None
	remaining = elapsed_seconds * (1.0 - overall_fraction) / overall_fraction
	if remaining > 30 * 24 * 60 * 60:
		return None
	return max(0.0, remaining)


def _conversion_completed_successfully(summary: ConversionSummary) -> bool:
	"""Return whether every planned conversion completed without errors."""
	return bool(
		summary.total > 0
		and summary.succeeded == summary.total
		and summary.failed == 0
		and not summary.canceled
		and not summary.stopped_after_current
	)


def _play_event_sound(path: Path, event_name: str) -> None:
	"""Play one bundled event sound without blocking NVDA."""
	try:
		nvwave.playWaveFile(str(path), asynchronous=True)
	except Exception:
		log.debugWarning(
			f"Easy Audio Converter: failed to play the {event_name} sound",
			exc_info=True,
		)


def _play_completion_sound() -> None:
	"""Play the bundled success notification without blocking NVDA."""
	_play_event_sound(COMPLETION_SOUND_PATH, "completion")


def _event_sound_enabled(config_key: str, default: bool = True) -> bool:
	try:
		_ensure_config()
		return bool(config.conf[CONFIG_SECTION].get(config_key, default))
	except Exception:
		return default


def _stage_status_label(stage: str) -> str:
	return {
		"planning": _("Building the conversion plan"),
		"probing": _("Reading audio information"),
		"analyzingLoudness": _("Analyzing loudness, first pass"),
		"converting": _("Converting audio, second pass"),
		"verifying": _("Verifying the output by decoding it"),
	}.get(stage, _("Preparing the conversion"))


class _VisualProgressBar(getattr(wx, "Panel", object)):
	"""Draw a progress bar without exposing noisy native progress events."""

	def __init__(self, parent, value_range: int = 1000):
		super().__init__(parent, style=getattr(wx, "BORDER_SIMPLE", 0))
		self._range = max(1, int(value_range))
		self._value = 0
		self.SetMinSize((-1, 14))
		if hasattr(self, "DisableFocusFromKeyboard"):
			self.DisableFocusFromKeyboard()
		self.Bind(wx.EVT_PAINT, self._on_paint)
		self.Bind(wx.EVT_SIZE, self._on_size)

	def AcceptsFocus(self) -> bool:
		return False

	def AcceptsFocusFromKeyboard(self) -> bool:
		return False

	def SetValue(self, value: int) -> None:
		value = max(0, min(self._range, int(value)))
		if value != self._value:
			self._value = value
			self.Refresh(False)

	def GetValue(self) -> int:
		return self._value

	def Pulse(self) -> None:
		self.SetValue((self._value + max(1, self._range // 20)) % self._range)

	def _on_size(self, event) -> None:
		self.Refresh(False)
		event.Skip()

	def _on_paint(self, event) -> None:
		dc = wx.PaintDC(self)
		width, height = self.GetClientSize()
		background = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
		foreground = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
		dc.SetBackground(wx.Brush(background))
		dc.Clear()
		completed_width = int(width * self._value / self._range)
		if completed_width > 0:
			dc.SetPen(wx.Pen(foreground))
			dc.SetBrush(wx.Brush(foreground))
			dc.DrawRectangle(0, 0, completed_width, height)


class ConversionProgressDialog(wx.Dialog):
	"""Accessible modeless progress window for the active conversion job."""

	def __init__(
		self,
		parent,
		on_cancel: Callable[[], None],
		on_stop_after_current: Callable[[], None],
		on_clear_queue: Callable[[], None],
		on_report: Callable[[], None],
		on_results: Callable[[], None],
	):
		super().__init__(
			parent,
			title=_("Easy Audio Converter progress"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._on_cancel_callback = on_cancel
		self._on_stop_after_current_callback = on_stop_after_current
		self._on_clear_queue_callback = on_clear_queue
		self._on_report_callback = on_report
		self._on_results_callback = on_results
		self._running = True
		self._cancel_requested = False
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.current_file = wx.StaticText(panel, label=_("Preparing the conversion"))
		sizer.Add(self.current_file, 0, wx.ALL | wx.EXPAND, 8)
		self.lifecycle_warning = wx.StaticText(panel, label=CONVERSION_LIFECYCLE_WARNING)
		self.lifecycle_warning.Wrap(520)
		sizer.Add(self.lifecycle_warning, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		self.file_status = wx.StaticText(panel, label=_("Current file progress: waiting"))
		sizer.Add(self.file_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		self.file_gauge = _VisualProgressBar(panel, value_range=1000)
		sizer.Add(self.file_gauge, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		self.overall_status = wx.StaticText(panel, label=_("Overall progress: waiting"))
		sizer.Add(self.overall_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		self.overall_gauge = _VisualProgressBar(panel, value_range=1000)
		sizer.Add(self.overall_gauge, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		self.elapsed_status = wx.StaticText(panel, label=_("Elapsed time: 0:00"))
		sizer.Add(self.elapsed_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		self.remaining_status = wx.StaticText(
			panel,
			label=_("Estimated time remaining: calculating"),
		)
		sizer.Add(self.remaining_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		self.queue_status = wx.StaticText(panel, label=_("Queued jobs: 0"))
		sizer.Add(self.queue_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		self.parallel_status = wx.StaticText(
			panel,
			label=_("Parallel workers: waiting"),
		)
		sizer.Add(self.parallel_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

		button_sizer = wx.FlexGridSizer(rows=2, cols=3, vgap=8, hgap=8)
		self.cancel_button = wx.Button(panel, label=_("Cancel conversion"))
		self.stop_button = wx.Button(panel, label=_("Stop after current file"))
		self.clear_queue_button = wx.Button(panel, label=_("Clear queued jobs"))
		self.report_button = wx.Button(panel, label=_("Report conversion status"))
		self.results_button = wx.Button(panel, label=_("Show results"))
		self.hide_button = wx.Button(panel, label=_("Hide"))
		button_sizer.Add(self.cancel_button, 0)
		button_sizer.Add(self.stop_button, 0)
		button_sizer.Add(self.clear_queue_button, 0)
		button_sizer.Add(self.report_button, 0)
		button_sizer.Add(self.results_button, 0)
		button_sizer.Add(self.hide_button, 0)
		sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer_sizer = wx.BoxSizer(wx.VERTICAL)
		outer_sizer.Add(panel, 1, wx.EXPAND)
		self.SetSizerAndFit(outer_sizer)
		self.SetMinSize((560, self.GetSize().height))
		self.CentreOnParent()
		self.cancel_button.Bind(wx.EVT_BUTTON, self._on_cancel)
		self.stop_button.Bind(wx.EVT_BUTTON, self._on_stop)
		self.clear_queue_button.Bind(wx.EVT_BUTTON, self._on_clear_queue)
		self.report_button.Bind(wx.EVT_BUTTON, self._on_report)
		self.results_button.Bind(wx.EVT_BUTTON, self._on_results)
		self.hide_button.Bind(wx.EVT_BUTTON, self._on_hide)
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self.results_button.Disable()
		self.clear_queue_button.Disable()

	def show_window(self) -> None:
		if not self.IsShown():
			self.Show()
		self.Raise()
		if self._running:
			self.cancel_button.SetFocus()
		else:
			self.hide_button.SetFocus()

	def update_progress(
		self,
		index: int,
		total: int,
		source_name: str,
		file_fraction: float | None,
		overall_fraction: float,
		processed_seconds: float,
		duration: float | None,
		elapsed_seconds: float,
	) -> None:
		if not self._running:
			return
		self.current_file.SetLabel(
			_("File {index} of {total}: {name}").format(
				index=index,
				total=total,
				name=source_name,
			)
		)
		if file_fraction is None:
			self.file_gauge.Pulse()
			self.file_status.SetLabel(
				_("Current file time: {processed}").format(
					processed=_format_elapsed(processed_seconds),
				)
			)
		else:
			file_percent = int(max(0.0, min(1.0, file_fraction)) * 100)
			self.file_gauge.SetValue(file_percent * 10)
			self.file_status.SetLabel(
				_("Current file progress: {percent}% ({processed} of {duration})").format(
					percent=file_percent,
					processed=_format_elapsed(processed_seconds),
					duration=_format_elapsed(duration),
				)
			)
		overall_percent = int(max(0.0, min(1.0, overall_fraction)) * 100)
		self.overall_gauge.SetValue(overall_percent * 10)
		self.overall_status.SetLabel(
			_("Overall progress: {percent}%").format(percent=overall_percent)
		)
		self.elapsed_status.SetLabel(
			_("Elapsed time: {elapsed}").format(elapsed=_format_elapsed(elapsed_seconds))
		)
		remaining = _estimate_remaining(elapsed_seconds, overall_fraction)
		self.remaining_status.SetLabel(
			_("Estimated time remaining: {remaining}").format(
				remaining=(
					_format_elapsed(remaining)
					if remaining is not None
					else _("calculating")
				)
			)
		)

	def update_stage(self, index: int, total: int, source_name: str, stage: str) -> None:
		if not self._running:
			return
		label = _stage_status_label(stage)
		if source_name and total:
			label = _("{stage}. File {index} of {total}: {name}").format(
				stage=label,
				index=index,
				total=total,
				name=source_name,
			)
		self.current_file.SetLabel(label)

	def set_queue_count(self, count: int) -> None:
		count = max(0, int(count))
		self.queue_status.SetLabel(_("Queued jobs: {count}").format(count=count))
		self.clear_queue_button.Enable(self._running and count > 0)

	def set_parallelism(self, active: int, target: int, adaptive: bool) -> None:
		if not self._running:
			return
		active = max(0, int(active))
		target = max(1, int(target))
		if adaptive:
			self.parallel_status.SetLabel(
				_("Adaptive workers: {active} active, target {target}").format(
					active=active,
					target=target,
				)
			)
		else:
			self.parallel_status.SetLabel(
				_("Parallel workers: {active} active of {target}").format(
					active=active,
					target=target,
				)
			)

	def finish(self, message: str, completed: bool, has_results: bool = False) -> None:
		self._running = False
		self.current_file.SetLabel(message)
		self.remaining_status.SetLabel(_("Estimated time remaining: 0:00"))
		self.parallel_status.SetLabel(_("Parallel workers: finished"))
		if completed:
			self.file_gauge.SetValue(1000)
			self.overall_gauge.SetValue(1000)
			self.file_status.SetLabel(_("Current file progress: 100%"))
			self.overall_status.SetLabel(_("Overall progress: 100%"))
		self.hide_button.SetLabel(_("Close"))
		if self.IsShown():
			self.hide_button.SetFocus()
		self.cancel_button.SetLabel(_("Cancel conversion"))
		self.cancel_button.Disable()
		self.stop_button.Disable()
		self.clear_queue_button.Disable()
		self.report_button.Disable()
		self.results_button.Enable(has_results)

	def _on_cancel(self, event):
		if self._running and not self._cancel_requested:
			self._cancel_requested = True
			self.cancel_button.SetLabel(_("Canceling..."))
			self._on_cancel_callback()

	def _on_stop(self, event):
		if self._running:
			self.stop_button.SetLabel(_("Stopping after this file..."))
			self.stop_button.Disable()
			self._on_stop_after_current_callback()

	def _on_clear_queue(self, event):
		if self._running:
			self._on_clear_queue_callback()

	def _on_report(self, event):
		if self._running:
			self._on_report_callback()

	def _on_results(self, event):
		if not self._running:
			self._on_results_callback()

	def _on_hide(self, event):
		self.Hide()

	def _on_close(self, event):
		self.Hide()
		if event.CanVeto():
			event.Veto()


def _friendly_failure_message(message: str) -> str:
	"""Translate common FFmpeg and filesystem failures into actionable text."""
	last_line = message.splitlines()[-1].strip() if message else ""
	lowered = last_line.casefold()
	if "could not remove source file after successful conversion" in message.casefold():
		return _(
			"The converted output was kept, but the source file could not be removed."
		)
	if "permission denied" in lowered or "access is denied" in lowered:
		return _("Access to the source or destination was denied.")
	if "no space left on device" in lowered or "not enough space" in lowered:
		return _("There is not enough free disk space.")
	if "invalid data found" in lowered:
		return _("The input file is damaged or uses an unsupported encoding.")
	if "does not contain any stream" in lowered or "matches no streams" in lowered:
		return _("The input does not contain a readable audio stream.")
	if "output duration differs" in lowered:
		return _("Output verification failed because its duration differs from the source.")
	if "could not preserve source file dates" in lowered:
		return _("The source file dates could not be preserved.")
	return last_line[:1000] if last_line else _("Unknown error")


def _skipped_reason_label(reason: str) -> str:
	return {
		"targetFormat": _("Already uses the target format"),
		"unsupported": _("Unsupported file type"),
		"unavailable": _("File or folder is unavailable"),
		"noAudioStream": _("No readable audio stream was found"),
		"requiresAac": _(
			"The first audio stream is not AAC, so it cannot be remuxed to M4A"
		),
	}.get(reason, _("Skipped"))


def _format_timing_seconds(seconds: float | None) -> str:
	"""Formatuj krótki pomiar, zachowując ułamki dla szybkich etapów."""
	value = max(0.0, float(seconds or 0.0))
	if value < 60.0:
		return f"{value:.2f} s"
	return _format_elapsed(value)


def _build_timing_report(summary: ConversionSummary) -> list[str]:
	timing = summary.timing
	return [
		_("Timing:"),
		_("Total wall time: {value}").format(
			value=_format_timing_seconds(timing.wall_seconds),
		),
		_("Input recognition: {value}").format(
			value=_format_timing_seconds(timing.probe_seconds),
		),
		_("Loudness analysis: {value}").format(
			value=_format_timing_seconds(timing.analysis_seconds),
		),
		_("Encoding and output writing: {value}").format(
			value=_format_timing_seconds(timing.encode_seconds),
		),
		_("Verification and finalization: {value}").format(
			value=_format_timing_seconds(timing.finalize_seconds),
		),
		_("Probe cache hits: {count}; misses: {misses}").format(
			count=timing.probe_cache_hits,
			misses=timing.probe_cache_misses,
		),
	]


def _build_results_report(summary: ConversionSummary) -> str:
	"""Build a complete localized plain-text report for the clipboard."""
	lines = [
		_("Conversion results"),
		_("Succeeded: {done}. Failed: {failed}. Skipped: {skipped}.").format(
			done=summary.succeeded,
			failed=summary.failed,
			skipped=summary.ignored,
		),
	]
	lines.extend(("", *_build_timing_report(summary)))
	if summary.canceled:
		lines.append(_("The conversion was canceled."))
	if summary.stopped_after_current:
		lines.append(_("The job was stopped after the current file."))
	if summary.successes:
		lines.extend(("", _("Successful files:")))
		for success in summary.successes:
			lines.append(f"{success.source_path} -> {success.output_path}")
	elif summary.outputs:
		lines.extend(("", _("Output files:"), *summary.outputs))
	if summary.failures:
		lines.extend(("", _("Failed files:")))
		for failure in summary.failures:
			source = failure.source_path or failure.source_name
			lines.append(f"{source}: {_friendly_failure_message(failure.message)}")
			if failure.output_path:
				lines.append(
					_("Converted output kept at: {output}").format(
						output=failure.output_path,
					)
				)
	if summary.skipped_files:
		lines.extend(("", _("Skipped files:")))
		for skipped in summary.skipped_files:
			lines.append(f"{skipped.source_path}: {_skipped_reason_label(skipped.reason)}")
		hidden_count = max(0, summary.ignored - len(summary.skipped_files))
		if hidden_count:
			lines.append(
				_("...and {count} more skipped files").format(count=hidden_count)
			)
	return "\n".join(lines)


class ConversionResultsDialog(wx.Dialog):
	"""Accessible modeless view of the most recent conversion results."""

	def __init__(
		self,
		parent,
		summary: ConversionSummary,
		on_retry_failed: Callable[[], None],
	):
		super().__init__(
			parent,
			title=_("Easy Audio Converter results"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._summary = summary
		self._on_retry_failed_callback = on_retry_failed
		self._entries: list[tuple[str, str, str | None]] = []
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(
			wx.StaticText(
				panel,
				label=_("Succeeded: {done}. Failed: {failed}. Skipped: {skipped}.").format(
					done=summary.succeeded,
					failed=summary.failed,
					skipped=summary.ignored,
				),
			),
			0,
			wx.ALL | wx.EXPAND,
			8,
		)
		for success in summary.successes:
			self._entries.append(
				(
					_("Success: {name}").format(name=Path(success.output_path).name),
					_(
						"Source:\n{source}\n\nOutput:\n{output}",
					).format(
						source=success.source_path,
						output=success.output_path,
					),
					success.output_path,
				)
			)
		if not summary.successes:
			for output in summary.outputs:
				self._entries.append(
					(
						_("Success: {name}").format(name=Path(output).name),
						_("Output:\n{output}").format(output=output),
						output,
					)
				)
		for failure in summary.failures:
			source = failure.source_path or failure.source_name
			details = _("Source:\n{source}\n\nError:\n{error}").format(
				source=source,
				error=_friendly_failure_message(failure.message),
			)
			if failure.output_path:
				details += "\n\n" + _(
					"Converted output kept at:\n{output}",
				).format(output=failure.output_path)
			self._entries.append(
				(
					_("Failed: {name}").format(name=failure.source_name),
					details,
					failure.output_path or None,
				)
			)
		for skipped in summary.skipped_files:
			self._entries.append(
				(
					_("Skipped: {name}").format(name=Path(skipped.source_path).name),
					_("Source:\n{source}\n\nReason:\n{reason}").format(
						source=skipped.source_path,
						reason=_skipped_reason_label(skipped.reason),
					),
					None,
				)
			)
		hidden_count = max(0, summary.ignored - len(summary.skipped_files))
		if hidden_count:
			self._entries.append(
				(
					_("Additional skipped files: {count}").format(count=hidden_count),
					_(
						"Details are limited to the first {limit} skipped files.",
					).format(limit=len(summary.skipped_files)),
					None,
				)
			)
		self.result_list = wx.ListBox(
			panel,
			choices=[entry[0] for entry in self._entries],
			style=wx.LB_SINGLE,
		)
		sizer.Add(self.result_list, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		sizer.Add(
			wx.StaticText(panel, label=_("Details:")),
			0,
			wx.LEFT | wx.RIGHT | wx.BOTTOM,
			8,
		)
		self.details = wx.TextCtrl(
			panel,
			style=wx.TE_MULTILINE | wx.TE_READONLY,
		)
		sizer.Add(self.details, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.retry_button = wx.Button(panel, label=_("Retry failed files"))
		self.open_button = wx.Button(panel, label=_("Open output folder"))
		self.copy_button = wx.Button(panel, label=_("Copy report"))
		self.close_button = wx.Button(panel, wx.ID_CLOSE, _("Close"))
		buttons.Add(self.retry_button, 0, wx.RIGHT, 8)
		buttons.Add(self.open_button, 0, wx.RIGHT, 8)
		buttons.Add(self.copy_button, 0, wx.RIGHT, 8)
		buttons.Add(self.close_button, 0)
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizer(outer)
		self.SetSize((760, 520))
		self.SetMinSize((600, 400))
		self.CentreOnParent()

		self.result_list.Bind(wx.EVT_LISTBOX, self._on_selected)
		self.retry_button.Bind(wx.EVT_BUTTON, self._on_retry)
		self.open_button.Bind(wx.EVT_BUTTON, self._on_open_output)
		self.copy_button.Bind(wx.EVT_BUTTON, self._on_copy_report)
		self.close_button.Bind(wx.EVT_BUTTON, self._on_close_button)
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self.retry_button.Enable(
			any(
				failure.source_path and not failure.output_path
				for failure in summary.failures
			)
		)
		self.open_button.Enable(any(entry[2] for entry in self._entries))
		if self._entries:
			self.result_list.SetSelection(0)
			self._show_entry(0)
		else:
			self.result_list.Disable()
			self.details.SetValue(_("No file details are available."))

	def show_window(self) -> None:
		if not self.IsShown():
			self.Show()
		self.Raise()
		if self._entries:
			self.result_list.SetFocus()
		else:
			self.close_button.SetFocus()

	def _show_entry(self, index: int) -> None:
		if 0 <= index < len(self._entries):
			self.details.SetValue(self._entries[index][1])
			self.details.SetInsertionPoint(0)

	def _on_selected(self, event) -> None:
		self._show_entry(self.result_list.GetSelection())
		event.Skip()

	def _selected_output(self) -> str | None:
		selection = self.result_list.GetSelection()
		if 0 <= selection < len(self._entries):
			output = self._entries[selection][2]
			if output:
				return output
		return self._summary.outputs[0] if self._summary.outputs else None

	def _on_retry(self, event) -> None:
		self.Hide()
		self._on_retry_failed_callback()

	def _on_open_output(self, event) -> None:
		output = self._selected_output()
		if not output:
			return
		try:
			os.startfile(str(Path(output).parent))
		except OSError:
			gui.messageBox(
				_("Could not open the output folder."),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)

	def _on_copy_report(self, event) -> None:
		try:
			copied = api.copyToClip(_build_results_report(self._summary))
			if copied is False:
				raise RuntimeError("NVDA could not access the clipboard")
		except Exception:
			gui.messageBox(
				_("Could not copy the conversion report."),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		ui.message(_("Conversion report copied"))

	def _on_close_button(self, event) -> None:
		self.Hide()

	def _on_close(self, event) -> None:
		self.Hide()
		if event.CanVeto():
			event.Veto()


@dataclass(frozen=True)
class _ConversionJob:
	paths: tuple[str, ...]
	settings: ConversionSettings
	source_root: str | None = None


SCRIPT_CATEGORY = _("Easy Audio Converter")


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = SCRIPT_CATEGORY

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		_ensure_config()
		self._converter: Converter | None = None
		self._job_queue: deque[_ConversionJob] = deque()
		self._parallel_plugins: dict[int, GlobalPlugin] = {}
		self._next_parallel_plugin_id = 1
		self._last_results_controller: GlobalPlugin | None = None
		self._current_job: _ConversionJob | None = None
		self._worker: threading.Thread | None = None
		self._progress: tuple[int, int, str, float | None, float, float, float | None, float] | None = None
		self._progress_dialog: ConversionProgressDialog | None = None
		self._results_dialog: ConversionResultsDialog | None = None
		self._audio_info_dialog: AudioInfoDialog | None = None
		self._media_info_worker: threading.Thread | None = None
		self._last_summary: ConversionSummary | None = None
		self._last_job_settings: ConversionSettings | None = None
		self._last_source_root: str | None = None
		self._pending_failure_result: (
			tuple[ConversionSummary, ConversionSettings | None, str | None] | None
		) = None
		self._job_settings: ConversionSettings | None = None
		self._job_source_root: str | None = None
		self._job_completion_mode = "speechAndSound"
		self._job_progress_mode = "milestones"
		self._job_started_at = 0.0
		self._job_stage = "preparing"
		self._update_check_thread: threading.Thread | None = None
		self._update_download_thread: threading.Thread | None = None
		self._update_cancel_event: threading.Event | None = None
		self._update_progress_dialog = None
		self._update_timer = None
		self._settings_dialog: EasyAudioConverterSettingsDialog | None = None
		self._terminated = False
		self._menu: wx.Menu | None = None
		self._menu_root_item = None
		self._menu_bindings: list[tuple[Any, Callable]] = []
		self._install_menu()
		if self._updates_allowed() and bool(
			config.conf[CONFIG_SECTION].get("autoCheckUpdates", True)
		):
			self._update_timer = wx.CallLater(8000, self._start_update_check, True)

	def terminate(self):
		self._terminated = True
		self._job_queue.clear()
		converter = self._converter
		if converter is not None:
			converter.cancel()
		worker = self._worker
		if worker is not None and worker.is_alive():
			worker.join(timeout=3)
		parallel_plugins = tuple(getattr(self, "_parallel_plugins", {}).values())
		for parallel_plugin in parallel_plugins:
			parallel_plugin._terminated = True
			parallel_converter = getattr(parallel_plugin, "_converter", None)
			if parallel_converter is not None:
				parallel_converter.cancel()
		for parallel_plugin in parallel_plugins:
			parallel_worker = getattr(parallel_plugin, "_worker", None)
			if parallel_worker is not None and parallel_worker.is_alive():
				parallel_worker.join(timeout=3)
		if self._update_timer is not None:
			try:
				self._update_timer.Stop()
			except Exception:
				pass
		if self._update_cancel_event is not None:
			self._update_cancel_event.set()
		try:
			self._remove_menu()
			if self._settings_dialog is not None:
				try:
					if self._settings_dialog.IsModal():
						self._settings_dialog.EndModal(wx.ID_CANCEL)
					else:
						self._settings_dialog.Destroy()
				except Exception:
					log.debugWarning(
						"Easy Audio Converter: could not close the settings dialog",
						exc_info=True,
					)
				self._settings_dialog = None
			if self._progress_dialog is not None:
				self._progress_dialog.Destroy()
				self._progress_dialog = None
			if self._results_dialog is not None:
				self._results_dialog.Destroy()
				self._results_dialog = None
			if self._audio_info_dialog is not None:
				self._audio_info_dialog.Destroy()
				self._audio_info_dialog = None
			if self._update_progress_dialog is not None:
				self._update_progress_dialog.Destroy()
				self._update_progress_dialog = None
			for parallel_plugin in parallel_plugins:
				for attribute in (
					"_settings_dialog",
					"_progress_dialog",
					"_results_dialog",
					"_audio_info_dialog",
					"_update_progress_dialog",
				):
					dialog = getattr(parallel_plugin, attribute, None)
					if dialog is not None:
						try:
							dialog.Destroy()
						except Exception:
							log.debugWarning(
								"Easy Audio Converter: could not close a parallel job window",
								exc_info=True,
							)
					setattr(parallel_plugin, attribute, None)
			getattr(parallel_plugin, "_job_queue", deque()).clear()
			if hasattr(self, "_parallel_plugins"):
				self._parallel_plugins.clear()
		finally:
			super().terminate()

	def _install_menu(self) -> None:
		try:
			tray = gui.mainFrame.sysTrayIcon
			tools_menu = tray.toolsMenu
			self._menu = wx.Menu()
			entries: tuple[tuple[str | None, Callable | None], ...] = (
				(_("Convert selected files or folders with options..."), self.script_convertSelectionWithOptions),
				(_("Convert selected files or folders"), self.script_convertSelection),
				(_("Choose files to convert") + "...", self.script_chooseFilesForConversion),
				(_("Choose a folder to convert") + "...", self.script_chooseFolderForConversion),
				(_("Convert the current folder"), self.script_convertCurrentFolder),
				(_("Information about the selected audio file..."), self.script_showSelectedAudioInfo),
				(_("Show conversion progress"), self.script_showProgress),
				(_("Report conversion status"), self.script_reportStatus),
				(_("Show last conversion results"), self.script_showResults),
				(_("Stop after the current file"), self.script_stopAfterCurrent),
				(_("Cancel conversion"), self.script_cancelConversion),
				(_("Report queued conversion jobs"), self.script_reportQueue),
				(_("Clear queued conversion jobs"), self.script_clearQueue),
				(None, None),
				(_("Settings..."), self.script_openSettings),
				(_("Advanced codec settings..."), self.script_openAdvancedSettings),
				(_("Check for updates..."), self.script_checkForUpdates),
				(_("Support the author"), self.script_openSupportPage),
			)
			for label, callback in entries:
				if label is None:
					self._menu.AppendSeparator()
					continue
				item = self._menu.Append(wx.ID_ANY, label)

				def handler(event, action=callback):
					# Poczekaj, aż wx zamknie menu Narzędzia i przywróci fokus.
					# Modalny dialog otwarty wewnątrz EVT_MENU bywa zgłaszany
					# przez NVDA jako „nieznane”.
					wx.CallAfter(action, None)

				tray.Bind(wx.EVT_MENU, handler, item)
				self._menu_bindings.append((item, handler))
			self._menu_root_item = tools_menu.AppendSubMenu(self._menu, _("Easy Audio Converter"))
		except Exception:
			log.debugWarning("Easy Audio Converter: could not add the Tools menu", exc_info=True)

	def _remove_menu(self) -> None:
		if self._menu is None:
			return
		try:
			tray = gui.mainFrame.sysTrayIcon
			for item, handler in self._menu_bindings:
				tray.Unbind(wx.EVT_MENU, handler=handler, source=item)
			if self._menu_root_item is not None:
				# DestroyItem niszczy również podmenu. Późniejsze wywołanie
				# Menu.Destroy uszkadza stertę wx podczas zamykania NVDA.
				tray.toolsMenu.DestroyItem(self._menu_root_item)
			else:
				self._menu.Destroy()
		except Exception:
			log.debugWarning("Easy Audio Converter: could not remove the Tools menu", exc_info=True)
		finally:
			self._menu = None
			self._menu_root_item = None
			self._menu_bindings.clear()

	@staticmethod
	def _ffmpeg_path() -> Path:
		return Path(__file__).resolve().parent / "bin" / "ffmpeg.exe"

	def _active_parallel_plugins(self) -> tuple["GlobalPlugin", ...]:
		return tuple(
			plugin
			for plugin in getattr(self, "_parallel_plugins", {}).values()
			if getattr(plugin, "_converter", None) is not None
		)

	def _is_busy(self) -> bool:
		return getattr(self, "_converter", None) is not None or bool(
			self._active_parallel_plugins()
		)

	def _create_parallel_plugin(self) -> "GlobalPlugin":
		"""Utwórz lekki kontroler zadania bez instalowania drugiego menu NVDA."""
		parallel_plugin = type(self).__new__(type(self))
		parallel_plugin._parallel_parent = self
		parallel_plugin._parallel_task_id = 0
		parallel_plugin._terminated = False
		parallel_plugin._converter = None
		parallel_plugin._job_queue = deque()
		parallel_plugin._parallel_plugins = {}
		parallel_plugin._last_results_controller = None
		parallel_plugin._current_job = None
		parallel_plugin._worker = None
		parallel_plugin._progress = None
		parallel_plugin._progress_dialog = None
		parallel_plugin._results_dialog = None
		parallel_plugin._audio_info_dialog = None
		parallel_plugin._media_info_worker = None
		parallel_plugin._last_summary = None
		parallel_plugin._last_job_settings = None
		parallel_plugin._last_source_root = None
		parallel_plugin._pending_failure_result = None
		parallel_plugin._job_settings = None
		parallel_plugin._job_source_root = None
		parallel_plugin._job_completion_mode = "speechAndSound"
		parallel_plugin._job_progress_mode = "milestones"
		parallel_plugin._job_started_at = 0.0
		parallel_plugin._job_stage = "preparing"
		parallel_plugin._update_check_thread = None
		parallel_plugin._update_download_thread = None
		parallel_plugin._update_cancel_event = None
		parallel_plugin._update_progress_dialog = None
		parallel_plugin._update_timer = None
		parallel_plugin._settings_dialog = None
		parallel_plugin._menu = None
		parallel_plugin._menu_root_item = None
		parallel_plugin._menu_bindings = []
		return parallel_plugin

	def _launch_parallel_conversion_job(self, job: _ConversionJob) -> None:
		"""Uruchom drugie zadanie z własnym konwerterem i oknem postępu."""
		parallel_plugin = self._create_parallel_plugin()
		parallel_plugin._parallel_task_id = getattr(self, "_next_parallel_plugin_id", 1)
		self._next_parallel_plugin_id = parallel_plugin._parallel_task_id + 1
		self._parallel_plugins[parallel_plugin._parallel_task_id] = parallel_plugin
		try:
			parallel_plugin._launch_conversion_job(job)
		except Exception:
			parallel_plugin._terminated = True
			parallel_converter = getattr(parallel_plugin, "_converter", None)
			if parallel_converter is not None:
				parallel_converter.cancel()
			parallel_worker = getattr(parallel_plugin, "_worker", None)
			if parallel_worker is not None and parallel_worker.is_alive():
				parallel_worker.join(timeout=3)
			self._parallel_plugins.pop(parallel_plugin._parallel_task_id, None)
			raise
		if parallel_plugin._converter is None and parallel_plugin._worker is None:
			self._parallel_plugins.pop(parallel_plugin._parallel_task_id, None)
			return
		progress_dialog = getattr(parallel_plugin, "_progress_dialog", None)
		if progress_dialog is not None and hasattr(progress_dialog, "SetTitle"):
			try:
				progress_dialog.SetTitle(
					_("Easy Audio Converter progress — separate job {id}").format(
						id=parallel_plugin._parallel_task_id,
					)
				)
			except Exception:
				log.debugWarning(
					"Easy Audio Converter: could not label a parallel progress window",
					exc_info=True,
				)
		ui.message(
			_("Started a separate conversion window for the new job.")
		)

	def _parallel_job_finished(self, parallel_plugin: "GlobalPlugin") -> None:
		"""Zachowaj zakończone okno, aby można było ponownie otworzyć wyniki."""
		if getattr(parallel_plugin, "_parallel_parent", None) is not self:
			return
		if getattr(parallel_plugin, "_last_summary", None) is not None:
			self._last_results_controller = parallel_plugin
		self._launch_next_queued_job()

	def _conversion_controllers(self, *, active_only: bool = True) -> tuple["GlobalPlugin", ...]:
		"""Zwróć zadanie główne i zadania w osobnych oknach w stałej kolejności."""
		controllers: list[GlobalPlugin] = []
		if not active_only or getattr(self, "_converter", None) is not None:
			controllers.append(self)
		parallel_plugins = getattr(self, "_parallel_plugins", {})
		for plugin in parallel_plugins.values():
			if not active_only or getattr(plugin, "_converter", None) is not None:
				controllers.append(plugin)
		return tuple(controllers)

	def _controller_status(self, controller: "GlobalPlugin") -> str:
		"""Przygotuj odczytywany stan bez informacji o kolejce."""
		progress = getattr(controller, "_progress", None)
		if progress is None:
			return _stage_status_label(getattr(controller, "_job_stage", "preparing"))
		(
			index,
			total,
			source_name,
			file_fraction,
			overall_fraction,
			processed_seconds,
			duration,
			elapsed_seconds,
		) = progress
		if file_fraction is None:
			message = _(
				"Converting {index} of {total}: {name}. "
				"Current file time {processed}; elapsed {elapsed}.",
			).format(
				index=index,
				total=total,
				name=source_name,
				processed=_format_elapsed(processed_seconds),
				elapsed=_format_elapsed(elapsed_seconds),
			)
		else:
			message = _(
				"Converting {index} of {total}: {name}. "
				"Current file {filePercent}%, overall {overallPercent}%, elapsed {elapsed}.",
			).format(
				index=index,
				total=total,
				name=source_name,
				filePercent=int(file_fraction * 100),
				overallPercent=int(overall_fraction * 100),
				elapsed=_format_elapsed(elapsed_seconds),
			)
		remaining = _estimate_remaining(elapsed_seconds, overall_fraction)
		return _(
			"{stage}. {status} Estimated time remaining {remaining}."
		).format(
			stage=_stage_status_label(getattr(controller, "_job_stage", "converting")),
			status=message,
			remaining=(
				_format_elapsed(remaining)
				if remaining is not None
				else _("calculating")
			),
		)

	def _open_settings_dialog(
		self,
		initial_tab: int = EasyAudioConverterSettingsDialog.STANDARD_TAB,
	) -> None:
		if self._terminated:
			return
		if self._settings_dialog is not None:
			try:
				self._settings_dialog.Raise()
				self._settings_dialog.SetFocus()
			except Exception:
				log.debugWarning(
					"Easy Audio Converter: could not focus the existing settings dialog",
					exc_info=True,
				)
			return

		dialog = None
		gui.mainFrame.prePopup()
		try:
			dialog = EasyAudioConverterSettingsDialog(
				gui.mainFrame,
				initial_tab=initial_tab,
			)
			self._settings_dialog = dialog
			dialog.ShowModal()
		except Exception:
			log.error(
				"Easy Audio Converter: could not open settings",
				exc_info=True,
			)
			gui.messageBox(
				_("Could not open Easy Audio Converter settings. See the NVDA log for details."),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				gui.mainFrame,
			)
		finally:
			self._settings_dialog = None
			if dialog is not None:
				try:
					dialog.Destroy()
				except Exception:
					log.debugWarning(
						"Easy Audio Converter: could not destroy the settings dialog",
						exc_info=True,
					)
			gui.mainFrame.postPopup()

	@staticmethod
	def _updates_allowed() -> bool:
		if globalVars is None:
			return True
		try:
			return not bool(getattr(globalVars.appArgs, "secure", False))
		except Exception:
			return False

	def _start_update_check(self, silent: bool = False) -> None:
		if self._terminated or not self._updates_allowed():
			return
		if self._update_check_thread is not None and self._update_check_thread.is_alive():
			if not silent:
				ui.message(_("An update check is already in progress"))
			return
		if not silent:
			ui.message(_("Checking for Easy Audio Converter updates"))

		def check() -> None:
			try:
				release = fetch_latest_release()
			except Exception as error:
				wx.CallAfter(self._on_update_check_result, None, str(error), silent)
			else:
				wx.CallAfter(self._on_update_check_result, release, None, silent)

		self._update_check_thread = threading.Thread(
			target=check,
			name="EasyAudioConverterUpdateCheck",
			daemon=True,
		)
		self._update_check_thread.start()

	def _on_update_check_result(
		self,
		release: ReleaseInfo | None,
		error_message: str | None,
		silent: bool,
	) -> None:
		self._update_check_thread = None
		if self._terminated:
			return
		if release is None:
			if not silent:
				gui.messageBox(
					_("Could not check for updates.\n\n{error}").format(
						error=error_message or _("Unknown error"),
					),
					_("Easy Audio Converter update"),
					wx.OK | wx.ICON_WARNING,
					gui.mainFrame,
				)
			return
		if not is_newer_version(release.version, ADDON_VERSION):
			if not silent:
				gui.messageBox(
					_("Easy Audio Converter is up to date. Installed version: {version}.").format(
						version=ADDON_VERSION,
					),
					_("Easy Audio Converter update"),
					wx.OK | wx.ICON_INFORMATION,
					gui.mainFrame,
				)
			return
		notes = release.notes.strip()
		if len(notes) > 1600:
			notes = f"{notes[:1600]}\n..."
		if release.download_url:
			message = _(
				"Easy Audio Converter {newVersion} is available. "
				"You have version {currentVersion}.\n\n"
				"Do you want to download and install the update now?",
			).format(
				newVersion=release.version,
				currentVersion=ADDON_VERSION,
			)
			if notes:
				message = f"{message}\n\n{_('Release notes:')}\n{notes}"
			dialog = wx.MessageDialog(
				gui.mainFrame,
				message,
				_("Easy Audio Converter update available"),
				wx.YES_NO | wx.YES_DEFAULT | wx.ICON_INFORMATION,
			)
			try:
				dialog.SetYesNoLabels(_("Download and install"), _("Later"))
				if dialog.ShowModal() == wx.ID_YES:
					self._start_update_download(release)
			finally:
				dialog.Destroy()
			return
		result = gui.messageBox(
			_(
				"Easy Audio Converter {version} is available, but the release "
				"does not contain a direct add-on package. Open the release page?",
			).format(version=release.version),
			_("Easy Audio Converter update available"),
			wx.YES_NO | wx.ICON_INFORMATION,
			gui.mainFrame,
		)
		if result == wx.YES:
			webbrowser.open(release.page_url or GITHUB_REPOSITORY_URL)

	def _start_update_download(self, release: ReleaseInfo) -> None:
		if self._update_download_thread is not None and self._update_download_thread.is_alive():
			ui.message(_("An update download is already in progress"))
			return
		if globalVars is not None:
			base_path = Path(globalVars.appArgs.configPath)
		else:
			base_path = Path(os.environ.get("APPDATA", str(Path.home()))) / "nvda"
		file_name = Path(release.asset_name).name or f"easyAudioConverter-{release.version}.nvda-addon"
		destination = base_path / "easyAudioConverterUpdates" / file_name
		self._update_cancel_event = threading.Event()
		self._update_progress_dialog = wx.ProgressDialog(
			_("Downloading Easy Audio Converter update"),
			_("Starting the download..."),
			maximum=1000,
			parent=gui.mainFrame,
			style=wx.PD_CAN_ABORT | wx.PD_ELAPSED_TIME | wx.PD_REMAINING_TIME | wx.PD_SMOOTH,
		)

		def progress(bytes_read: int, total_size: int | None) -> None:
			wx.CallAfter(self._update_download_progress, bytes_read, total_size)

		def download() -> None:
			try:
				path = download_release(
					release,
					destination,
					progress_callback=progress,
					cancel_event=self._update_cancel_event,
				)
			except UpdateCanceled:
				wx.CallAfter(self._on_update_download_complete, None, None, True)
			except Exception as error:
				wx.CallAfter(self._on_update_download_complete, None, str(error), False)
			else:
				wx.CallAfter(self._on_update_download_complete, path, None, False)

		self._update_download_thread = threading.Thread(
			target=download,
			name="EasyAudioConverterUpdateDownload",
			daemon=True,
		)
		self._update_download_thread.start()

	def _update_download_progress(self, bytes_read: int, total_size: int | None) -> None:
		if self._terminated or self._update_progress_dialog is None:
			return
		megabytes = bytes_read / (1024 * 1024)
		if total_size:
			value = int(max(0.0, min(1.0, bytes_read / total_size)) * 1000)
			total_megabytes = total_size / (1024 * 1024)
			result = self._update_progress_dialog.Update(
				value,
				_("Downloaded {done:.1f} of {total:.1f} MB").format(
					done=megabytes,
					total=total_megabytes,
				),
			)
		else:
			result = self._update_progress_dialog.Pulse(
				_("Downloaded {done:.1f} MB").format(done=megabytes)
			)
		keep_going = result[0] if isinstance(result, tuple) else bool(result)
		if not keep_going and self._update_cancel_event is not None:
			self._update_cancel_event.set()

	def _on_update_download_complete(
		self,
		path: Path | None,
		error_message: str | None,
		canceled: bool,
	) -> None:
		self._update_download_thread = None
		if self._update_progress_dialog is not None:
			self._update_progress_dialog.Destroy()
			self._update_progress_dialog = None
		if self._terminated:
			return
		if canceled:
			ui.message(_("Update download canceled"))
			return
		if path is None:
			gui.messageBox(
				_("The update could not be downloaded or verified.\n\n{error}").format(
					error=error_message or _("Unknown error"),
				),
				_("Easy Audio Converter update"),
				wx.OK | wx.ICON_ERROR,
				gui.mainFrame,
			)
			return
		ui.message(_("The update is ready. Opening the NVDA add-on installer."))
		try:
			os.startfile(str(path))
		except OSError:
			gui.messageBox(
				_("Could not open the NVDA add-on installer. The update was saved to:\n{path}").format(
					path=path,
				),
				_("Easy Audio Converter update"),
				wx.OK | wx.ICON_ERROR,
				gui.mainFrame,
			)

	def _start_conversion(
		self,
		paths: list[str],
		*,
		source_root: str | None = None,
		settings: ConversionSettings | None = None,
	) -> None:
		settings = settings or _read_settings()
		try:
			settings.validate()
		except ValueError as error:
			gui.messageBox(
				str(error),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				gui.mainFrame,
			)
			return
		settings = replace(
			settings,
			metadata_fields=tuple(settings.metadata_fields),
			advanced_options=dict(settings.advanced_options),
		)
		if settings.replace_source_files:
			result = gui.messageBox(
				_(
					"Replacing source files cannot be undone. After each output is "
					"created and checked successfully, its source file will be "
					"permanently deleted. Source files will be kept if conversion "
					"or verification fails. Continue?",
				),
				_("Replace source files"),
				wx.YES_NO | getattr(wx, "NO_DEFAULT", 0) | wx.ICON_WARNING,
				gui.mainFrame,
			)
			if result != wx.YES:
				return
		job = _ConversionJob(tuple(paths), settings, source_root)
		if self._is_busy():
			if _read_busy_conversion_mode() == "parallel":
				try:
					self._launch_parallel_conversion_job(job)
				except Exception as error:
					log.error(
						"Easy Audio Converter: could not start a separate conversion",
						exc_info=True,
					)
					gui.messageBox(
						_("The separate conversion could not start:\n{error}").format(
							error=error,
						),
						_("Easy Audio Converter"),
						wx.OK | wx.ICON_ERROR,
						gui.mainFrame,
					)
				return
			self._job_queue.append(job)
			position = len(self._job_queue)
			if self._progress_dialog is not None:
				self._progress_dialog.set_queue_count(position)
			ui.message(
				_("Conversion job added to the queue. Queue position: {position}.").format(
					position=position
				)
			)
			return
		self._launch_conversion_job(job)

	def _launch_conversion_job(self, job: _ConversionJob) -> None:
		paths = list(job.paths)
		source_root = job.source_root
		settings = job.settings
		ffmpeg_path = self._ffmpeg_path()
		if not ffmpeg_path.is_file():
			gui.messageBox(
				_("The bundled FFmpeg component is missing. Reinstall Easy Audio Converter."),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				gui.mainFrame,
			)
			if _event_sound_enabled("errorSound"):
				_play_event_sound(ERROR_SOUND_PATH, "error")
			queued_count = len(self._job_queue)
			if queued_count:
				self._job_queue.clear()
				if self._progress_dialog is not None:
					self._progress_dialog.set_queue_count(0)
				ui.message(
					_("Cleared {count} queued conversion jobs").format(
						count=queued_count
					)
				)
			return
		self._current_job = job
		self._job_settings = settings
		self._job_source_root = source_root
		self._job_completion_mode, self._job_progress_mode = _read_notification_preferences()
		converter = Converter(ffmpeg_path)
		self._converter = converter
		self._progress = None
		self._job_started_at = time.monotonic()
		if self._progress_dialog is not None:
			self._progress_dialog.Destroy()
		if self._results_dialog is not None:
			self._results_dialog.Hide()
		self._progress_dialog = ConversionProgressDialog(
			gui.mainFrame,
			lambda: self.script_cancelConversion(None),
			lambda: self.script_stopAfterCurrent(None),
			lambda: self.script_clearQueue(None),
			lambda: self.script_reportStatus(None),
			lambda: self.script_showResults(None),
		)
		self._progress_dialog.set_queue_count(len(self._job_queue))
		self._progress_dialog.show_window()
		ui.message(_("Preparing the conversion"))
		if not settings.show_preflight:
			ui.message(CONVERSION_LIFECYCLE_WARNING)

		def on_collected(total: int, ignored: int) -> None:
			if total:
				if ignored:
					message = _("Files to convert: {count}. Skipped: {skipped}.").format(
						count=total,
						skipped=ignored,
					)
				else:
					message = _("Found {count} files to convert").format(count=total)
				workers = resolve_parallel_jobs(settings.parallel_jobs, total)
				if workers > 1:
					if settings.parallel_jobs == 0:
						message = _(
							"{message}. Starting with {workers} adaptive conversion workers.",
						).format(message=message, workers=workers)
					else:
						message = _(
							"{message}. Using {workers} parallel conversion workers.",
						).format(message=message, workers=workers)
				wx.CallAfter(ui.message, message)

		def on_file_start(index: int, total: int, source_name: str, output_name: str) -> None:
			percentage = int(index * 100 / max(1, total))
			previous_percentage = int((index - 1) * 100 / max(1, total))
			if self._job_progress_mode == "everyFile":
				announce = True
			elif self._job_progress_mode == "onDemand":
				announce = False
			else:
				announce = (
					total <= 10
					or index in {1, total}
					or percentage // 10 > previous_percentage // 10
				)
			if announce:
				wx.CallAfter(
					ui.message,
					_("Converting {index} of {total}: {name}").format(
						index=index,
						total=total,
						name=source_name,
					),
				)

		def on_progress(
			index: int,
			total: int,
			source_name: str,
			file_fraction: float | None,
			overall_fraction: float,
			processed_seconds: float,
			duration: float | None,
		) -> None:
			elapsed = max(0.0, time.monotonic() - self._job_started_at)
			self._progress = (
				index,
				total,
				source_name,
				file_fraction,
				overall_fraction,
				processed_seconds,
				duration,
				elapsed,
			)
			wx.CallAfter(
				self._set_progress,
				converter,
				index,
				total,
				source_name,
				file_fraction,
				overall_fraction,
				processed_seconds,
				duration,
				elapsed,
			)

		def on_stage(index: int, total: int, source_name: str, stage: str) -> None:
			self._job_stage = stage
			wx.CallAfter(
				self._set_stage,
				converter,
				index,
				total,
				source_name,
				stage,
			)

		def on_parallelism(active: int, target: int, adaptive: bool) -> None:
			wx.CallAfter(
				self._set_parallelism,
				converter,
				active,
				target,
				adaptive,
			)

		callbacks = ConversionCallbacks(
			on_collected=on_collected,
			on_file_start=on_file_start,
			on_progress=on_progress,
			on_stage=on_stage,
			on_parallelism=on_parallelism,
		)

		def run_job() -> None:
			try:
				plan = None
				if settings.show_preflight:
					plan = converter.create_plan(
						paths,
						settings,
						source_root=source_root,
						callbacks=ConversionCallbacks(on_stage=on_stage),
					)
					if converter.is_canceled:
						summary = converter.run(
							paths,
							settings,
							source_root=source_root,
							callbacks=callbacks,
							plan=plan,
						)
						wx.CallAfter(self._job_complete, converter, summary)
						return
					if plan.total and not self._request_plan_approval(converter, plan):
						summary = ConversionSummary(
							total=plan.total,
							ignored=plan.ignored,
							canceled=True,
							skipped_files=list(plan.skipped_files),
						)
						wx.CallAfter(self._job_complete, converter, summary)
						return
				summary = converter.run(
					paths,
					settings,
					source_root=source_root,
					callbacks=callbacks,
					plan=plan,
				)
			except Exception as error:
				wx.CallAfter(self._job_failed, converter, str(error))
			else:
				wx.CallAfter(self._job_complete, converter, summary)

		self._worker = threading.Thread(
			target=run_job,
			name="EasyAudioConverterWorker",
			daemon=True,
		)
		self._worker.start()

	def _request_plan_approval(
		self,
		converter: Converter,
		plan: ConversionPlan,
	) -> bool:
		decision = {"approved": False}
		finished = threading.Event()

		def show_dialog() -> None:
			try:
				if self._terminated or converter is not self._converter:
					return
				dialog = ConversionPlanDialog(gui.mainFrame, plan)
				try:
					gui.mainFrame.prePopup()
					try:
						decision["approved"] = dialog.ShowModal() == wx.ID_OK
					finally:
						gui.mainFrame.postPopup()
				finally:
					dialog.Destroy()
			finally:
				finished.set()

		wx.CallAfter(show_dialog)
		while not finished.wait(0.1):
			if self._terminated or converter is not self._converter:
				return False
		return bool(decision["approved"])

	def _set_stage(
		self,
		converter: Converter,
		index: int,
		total: int,
		source_name: str,
		stage: str,
	) -> None:
		if self._terminated or converter is not self._converter:
			return
		if self._progress_dialog is not None:
			self._progress_dialog.update_stage(
				index,
				total,
				source_name,
				stage,
			)

	def _set_parallelism(
		self,
		converter: Converter,
		active: int,
		target: int,
		adaptive: bool,
	) -> None:
		if self._terminated or converter is not self._converter:
			return
		if self._progress_dialog is not None:
			self._progress_dialog.set_parallelism(active, target, adaptive)

	def _set_progress(
		self,
		converter: Converter,
		index: int,
		total: int,
		source_name: str,
		file_fraction: float | None,
		overall_fraction: float,
		processed_seconds: float,
		duration: float | None,
		elapsed_seconds: float,
	) -> None:
		if self._terminated or converter is not self._converter:
			return
		if self._progress_dialog is not None:
			self._progress_dialog.update_progress(
				index,
				total,
				source_name,
				file_fraction,
				overall_fraction,
				processed_seconds,
				duration,
				elapsed_seconds,
			)

	def _job_failed(self, converter: Converter, message: str) -> None:
		if converter is not self._converter:
			return
		self._converter = None
		self._worker = None
		self._progress = None
		self._job_settings = None
		self._job_source_root = None
		self._current_job = None
		if self._terminated:
			return
		if self._progress_dialog is not None:
			self._progress_dialog.finish(
				_("The conversion could not start"),
				completed=False,
				has_results=False,
			)
		gui.messageBox(
			_("The conversion could not start:\n{error}").format(error=message),
			_("Easy Audio Converter"),
			wx.OK | wx.ICON_ERROR,
			gui.mainFrame,
		)
		if _event_sound_enabled("errorSound"):
			_play_event_sound(ERROR_SOUND_PATH, "error")
		self._launch_next_queued_job()
		parallel_parent = getattr(self, "_parallel_parent", None)
		if parallel_parent is not None:
			parallel_parent._parallel_job_finished(self)

	def _job_complete(self, converter: Converter, summary: ConversionSummary) -> None:
		if converter is not self._converter:
			return
		if self._terminated:
			return
		message = ""
		if summary.canceled:
			message = _("Conversion canceled. Completed {done} of {total} files.").format(
				done=summary.succeeded,
				total=summary.total,
			)
		elif summary.stopped_after_current:
			message = _(
				"Stopped after the current file. Completed {done} of {total} files.",
			).format(
				done=summary.succeeded,
				total=summary.total,
			)
		elif summary.total == 0 and summary.ignored:
			message = _("No files need conversion. Skipped: {skipped}.").format(
				skipped=summary.ignored,
			)
		elif summary.total == 0:
			message = _("No supported audio files were found")
		elif summary.ignored:
			message = _(
				"Conversion complete. Succeeded: {done}. Failed: {failed}. "
				"Skipped: {skipped}.",
			).format(
				done=summary.succeeded,
				failed=summary.failed,
				skipped=summary.ignored,
			)
		else:
			message = _("Conversion complete: {done} succeeded, {failed} failed.").format(
				done=summary.succeeded,
				failed=summary.failed,
			)
		successful = _conversion_completed_successfully(summary)
		completion_mode = getattr(self, "_job_completion_mode", "speechAndSound")
		if not successful or completion_mode in {"speechAndSound", "speechOnly"}:
			ui.message(message)
		has_results = bool(
			summary.total
			or summary.ignored
			or summary.outputs
			or summary.failures
			or summary.canceled
			or summary.stopped_after_current
		)
		if self._progress_dialog is not None:
			self._progress_dialog.finish(
				message,
				completed=bool(
					summary.total
					and not summary.canceled
					and not summary.stopped_after_current
				),
				has_results=has_results,
			)
		job_settings = getattr(self, "_job_settings", None)
		job_source_root = getattr(self, "_job_source_root", None)
		queue_pending = bool(getattr(self, "_job_queue", ()))
		self._last_summary = summary
		self._last_job_settings = job_settings
		self._last_source_root = job_source_root
		if getattr(self, "_parallel_parent", None) is None:
			self._last_results_controller = self
		if summary.failures and queue_pending:
			self._pending_failure_result = (
				summary,
				job_settings,
				job_source_root,
			)
		self._converter = None
		self._worker = None
		self._progress = None
		self._job_settings = None
		self._job_source_root = None
		self._current_job = None
		if successful and completion_mode in {"speechAndSound", "soundOnly"}:
			_play_completion_sound()
		elif (summary.canceled or summary.stopped_after_current) and _event_sound_enabled(
			"cancelSound"
		):
			_play_event_sound(CANCEL_SOUND_PATH, "cancel")
		elif summary.failed and _event_sound_enabled("errorSound"):
			_play_event_sound(ERROR_SOUND_PATH, "error")
		if not queue_pending:
			pending_failure = getattr(self, "_pending_failure_result", None)
			if not summary.failures and pending_failure is not None:
				(
					self._last_summary,
					self._last_job_settings,
					self._last_source_root,
				) = pending_failure
			self._pending_failure_result = None
		if self._last_summary is not None and self._last_summary.failures and not queue_pending:
			self._show_results_dialog()
		self._launch_next_queued_job()
		parallel_parent = getattr(self, "_parallel_parent", None)
		if parallel_parent is not None:
			parallel_parent._parallel_job_finished(self)

	def _launch_next_queued_job(self) -> None:
		if self._terminated or self._is_busy():
			return
		queue = getattr(self, "_job_queue", None)
		if not queue:
			return
		job = queue.popleft()
		ui.message(
			_("Starting the next queued conversion. Jobs remaining: {count}.").format(
				count=len(queue)
			)
		)
		self._launch_conversion_job(job)

	def _show_results_dialog(self) -> None:
		summary = self._last_summary
		if summary is None:
			ui.message(_("No conversion results are available"))
			return
		if (
			self._results_dialog is not None
			and getattr(self._results_dialog, "_summary", None) is summary
		):
			self._results_dialog.show_window()
			return
		if self._results_dialog is not None:
			self._results_dialog.Destroy()
		self._results_dialog = ConversionResultsDialog(
			gui.mainFrame,
			summary,
			self._retry_failed_files,
		)
		self._results_dialog.show_window()

	def _retry_failed_files(self) -> None:
		summary = self._last_summary
		settings = self._last_job_settings
		if summary is None or settings is None:
			ui.message(_("No failed files are available to retry"))
			return
		paths = list(
			dict.fromkeys(
				failure.source_path
				for failure in summary.failures
				if failure.source_path and not failure.output_path
			)
		)
		if not paths:
			ui.message(_("No failed files are available to retry"))
			return
		self._start_conversion(
			paths,
			source_root=self._last_source_root,
			settings=settings,
		)

	def _resume_after_script_picker(
		self,
		callback: Callable[[Any], None],
		value: Any,
	) -> None:
		"""Przywróć stan okien NVDA po zniszczeniu natywnego dialogu."""
		try:
			gui.mainFrame.postPopup()
		except Exception:
			log.debugWarning(
				"Easy Audio Converter: nie można przywrócić fokusu po oknie wyboru",
				exc_info=True,
			)
		if not getattr(self, "_terminated", False):
			callback(value)

	def _run_script_picker_dialog(
		self,
		dialog: wx.Dialog,
		completed: Callable[[int], None],
	) -> None:
		"""Pokaż dialog dopiero po zakończeniu bieżącego skryptu NVDA."""
		gui.mainFrame.prePopup()

		def show() -> None:
			try:
				try:
					result = dialog.ShowModal()
				except Exception:
					log.error(
						"Easy Audio Converter: nie można wyświetlić okna wyboru",
						exc_info=True,
					)
					result = getattr(wx, "ID_CANCEL", 0)
				completed(result)
			finally:
				dialog.Destroy()

		try:
			wx.CallAfter(show)
		except Exception:
			try:
				dialog.Destroy()
			finally:
				gui.mainFrame.postPopup()
			raise

	def _choose_files_for_conversion(
		self,
		callback: Callable[[list[str]], None],
		default_folder: str = "",
	) -> None:
		default_directory = default_folder if os.path.isdir(default_folder) else str(Path.home())
		dialog = wx.FileDialog(
			gui.mainFrame,
			_("Choose files to convert"),
			defaultDir=default_directory,
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
		)

		def completed(result: int) -> None:
			paths: list[str] = []
			try:
				if result == wx.ID_OK:
					paths = list(
						dict.fromkeys(
							path
							for path in dialog.GetPaths()
							if path and os.path.isfile(path)
						)
					)
			except Exception:
				log.error(
					"Easy Audio Converter: nie można odczytać wyniku wyboru plików",
					exc_info=True,
				)
			finally:
				# runScriptModalDialog niszczy dialog po powrocie z callbacku.
				wx.CallAfter(self._resume_after_script_picker, callback, paths)

		# Wywołanie z kolejki pozwala skryptowi NVDA zakończyć się przed
		# wejściem do natywnej pętli modalnej. Dzięki temu NVDA czyta dialog
		# i nie zgłasza zamrożenia własnego wątku.
		self._run_script_picker_dialog(dialog, completed)

	def _show_folder_picker(
		self,
		title: str,
		default_folder: str,
		callback: Callable[[str], None],
	) -> None:
		default_path = default_folder if os.path.isdir(default_folder) else str(Path.home())
		dialog = wx.DirDialog(
			gui.mainFrame,
			title,
			defaultPath=default_path,
			style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
		)

		def completed(result: int) -> None:
			folder = ""
			try:
				if result == wx.ID_OK:
					path = dialog.GetPath()
					folder = path if os.path.isdir(path) else ""
			except Exception:
				log.error(
					"Easy Audio Converter: nie można odczytać wyniku wyboru folderu",
					exc_info=True,
				)
			finally:
				wx.CallAfter(self._resume_after_script_picker, callback, folder)

		self._run_script_picker_dialog(dialog, completed)

	def _choose_folder_for_conversion(
		self,
		callback: Callable[[str], None],
		default_folder: str = "",
	) -> None:
		self._show_folder_picker(
			_("Choose a folder to convert"),
			default_folder,
			callback,
		)

	def _selection_for_conversion(self) -> tuple[list[str], str | None, str]:
		selection, current_folder = _explorer_context()
		if not selection:
			focused = _focused_path(current_folder)
			if focused:
				selection = [focused]
		source_root = selection[0] if len(selection) == 1 and os.path.isdir(selection[0]) else None
		return selection, source_root, current_folder

	def _confirm_folder_conversion(
		self,
		folder_description: str,
		settings: ConversionSettings | None = None,
	) -> bool:
		settings = settings or _read_settings()
		scope = (
			_("including subfolders")
			if settings.include_subfolders
			else _("excluding subfolders")
		)
		result = gui.messageBox(
			_(
				"Convert all supported audio files in {folder}, {scope}?",
			).format(folder=folder_description, scope=scope),
			_("Confirm folder conversion"),
			wx.YES_NO | getattr(wx, "NO_DEFAULT", 0) | wx.ICON_QUESTION,
			gui.mainFrame,
		)
		return result == wx.YES

	def _convert_paths_with_options(
		self,
		selection: list[str],
		*,
		source_root: str | None = None,
	) -> None:
		dialog = ConversionOptionsDialog(
			gui.mainFrame,
			item_count=len(selection),
			initial_settings=_read_settings(),
			preview_source=next(
				(path for path in selection if os.path.isfile(path)),
				selection[0],
			),
		)
		settings = _run_conversion_options_dialog(dialog)
		if settings is None:
			return
		selected_folders = [path for path in selection if os.path.isdir(path)]
		if selected_folders:
			description = (
				os.path.basename(selected_folders[0].rstrip("\\/"))
				if len(selected_folders) == 1
				else _("{count} selected folders").format(count=len(selected_folders))
			)
			if not settings.show_preflight and not self._confirm_folder_conversion(
				description,
				settings,
			):
				return
		self._start_conversion(
			selection,
			source_root=source_root,
			settings=settings,
		)

	def _quick_convert_paths(
		self,
		selection: list[str],
		*,
		source_root: str | None = None,
	) -> None:
		selected_folders = [path for path in selection if os.path.isdir(path)]
		settings = _read_settings()
		if selected_folders:
			description = (
				os.path.basename(selected_folders[0].rstrip("\\/"))
				if len(selected_folders) == 1
				else _("{count} selected folders").format(count=len(selected_folders))
			)
			if not settings.show_preflight and not self._confirm_folder_conversion(
				description,
				settings,
			):
				return
		else:
			settings = replace(settings, show_preflight=False)
		self._start_conversion(
			selection,
			source_root=source_root,
			settings=settings,
		)

	@script(
		# Translators: Input gesture description.
		description=_("Open Easy Audio Converter settings"),
		category=SCRIPT_CATEGORY,
	)
	def script_openSettings(self, gesture):
		wx.CallAfter(
			self._open_settings_dialog,
			EasyAudioConverterSettingsDialog.STANDARD_TAB,
		)

	@script(
		# Translators: Input gesture description.
		description=_("Open advanced codec settings"),
		category=SCRIPT_CATEGORY,
	)
	def script_openAdvancedSettings(self, gesture):
		wx.CallAfter(
			self._open_settings_dialog,
			EasyAudioConverterSettingsDialog.ADVANCED_TAB,
		)

	@script(
		# Translators: Input gesture description.
		description=_("Convert selected files or folders with one-time options"),
		category=SCRIPT_CATEGORY,
	)
	def script_convertSelectionWithOptions(self, gesture):
		selection, source_root, current_folder = self._selection_for_conversion()
		if selection:
			wx.CallAfter(
				self._convert_paths_with_options,
				selection,
				source_root=source_root,
			)
			return

		def convert(chosen: list[str]) -> None:
			if chosen:
				self._convert_paths_with_options(chosen)

		self._choose_files_for_conversion(convert, current_folder)

	@script(
		# Translators: Input gesture description.
		description=_("Quickly convert selected files or folders"),
		category=SCRIPT_CATEGORY,
	)
	def script_convertSelection(self, gesture):
		selection, source_root, current_folder = self._selection_for_conversion()
		if selection:
			wx.CallAfter(
				self._quick_convert_paths,
				selection,
				source_root=source_root,
			)
			return

		def convert(chosen: list[str]) -> None:
			if chosen:
				self._quick_convert_paths(chosen)

		self._choose_files_for_conversion(convert, current_folder)

	@script(
		description=_("Choose files to convert"),
		category=SCRIPT_CATEGORY,
	)
	def script_chooseFilesForConversion(self, gesture):
		def convert(selection: list[str]) -> None:
			if selection:
				self._quick_convert_paths(selection)

		self._choose_files_for_conversion(convert)

	@script(
		description=_("Choose a folder to convert"),
		category=SCRIPT_CATEGORY,
	)
	def script_chooseFolderForConversion(self, gesture):
		def convert(folder: str) -> None:
			if folder:
				self._quick_convert_paths([folder], source_root=folder)

		self._choose_folder_for_conversion(convert)

	@script(
		# Translators: Input gesture description.
		description=_("Convert every supported audio file in the current folder"),
		category=SCRIPT_CATEGORY,
	)
	def script_convertCurrentFolder(self, gesture):
		_selection, folder = _explorer_context()
		if folder and os.path.isdir(folder):
			wx.CallAfter(
				self._quick_convert_paths,
				[folder],
				source_root=folder,
			)
			return

		def convert(chosen_folder: str) -> None:
			if chosen_folder:
				self._quick_convert_paths(
					[chosen_folder],
					source_root=chosen_folder,
				)

		self._choose_folder_for_conversion(convert)

	@script(
		description=_("Show technical information about the selected audio file"),
		category=SCRIPT_CATEGORY,
	)
	def script_showSelectedAudioInfo(self, gesture):
		selection, _source_root, _current_folder = self._selection_for_conversion()
		files = [path for path in selection if os.path.isfile(path)]
		if len(files) != 1:
			ui.message(_("Select exactly one audio file"))
			return
		if self._media_info_worker is not None and self._media_info_worker.is_alive():
			ui.message(_("Audio information is already being read"))
			return
		source = files[0]
		ui.message(_("Reading audio file information"))

		def probe() -> None:
			try:
				info = Converter(self._ffmpeg_path()).probe_media_info(source)
			except Exception as error:
				wx.CallAfter(self._on_media_info_ready, None, str(error))
			else:
				wx.CallAfter(self._on_media_info_ready, info, None)

		self._media_info_worker = threading.Thread(
			target=probe,
			name="EasyAudioConverterMediaInfo",
			daemon=True,
		)
		self._media_info_worker.start()

	def _on_media_info_ready(
		self,
		info: MediaInfo | None,
		error_message: str | None,
	) -> None:
		self._media_info_worker = None
		if self._terminated:
			return
		if info is None:
			gui.messageBox(
				_("Could not read audio information:\n{error}").format(
					error=error_message or _("Unknown error")
				),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				gui.mainFrame,
			)
			return
		if self._audio_info_dialog is not None:
			self._audio_info_dialog.Destroy()
		self._audio_info_dialog = AudioInfoDialog(gui.mainFrame, info)
		self._audio_info_dialog.Show()
		self._audio_info_dialog.Raise()
		self._audio_info_dialog.details.SetFocus()
		ui.message(
			_(
				"Audio information ready. Codec {codec}, duration {duration}, "
				"sample rate {sampleRate}.",
			).format(
				codec=info.codec or _("unknown"),
				duration=(
					_format_elapsed(info.duration)
					if info.duration is not None
					else _("unknown")
				),
				sampleRate=(
					_("{value} Hz").format(value=info.sample_rate)
					if info.sample_rate is not None
					else _("unknown")
				),
			)
		)

	@script(
		# Translators: Input gesture description.
		description=_("Change the target audio format"),
		category=SCRIPT_CATEGORY,
	)
	def script_cycleTargetFormat(self, gesture):
		_ensure_config()
		conf = config.conf[CONFIG_SECTION]
		current = _validated_key(conf.get("targetFormat"), FORMAT_KEYS, "mp3")
		new_key = FORMAT_KEYS[(FORMAT_KEYS.index(current) + 1) % len(FORMAT_KEYS)]
		conf["targetFormat"] = new_key
		config.conf.save()
		ui.message(_("Target format: {format}").format(format=_format_labels()[new_key]))

	@script(
		# Translators: Input gesture description.
		description=_("Change the conversion quality"),
		category=SCRIPT_CATEGORY,
	)
	def script_cycleQuality(self, gesture):
		_ensure_config()
		conf = config.conf[CONFIG_SECTION]
		target_format = _validated_key(conf.get("targetFormat"), FORMAT_KEYS, "mp3")
		if target_format in STREAM_COPY_FORMATS:
			ui.message(
				_("Quality is not used when copying audio without re-encoding")
			)
			return
		current = _validated_key(conf.get("quality"), QUALITY_KEYS, "high")
		new_key = QUALITY_KEYS[(QUALITY_KEYS.index(current) + 1) % len(QUALITY_KEYS)]
		conf["quality"] = new_key
		config.conf.save()
		ui.message(_("Quality: {quality}").format(quality=_quality_labels()[new_key]))

	@script(
		# Translators: Input gesture description.
		description=_("Quickly choose the destination folder"),
		category=SCRIPT_CATEGORY,
	)
	def script_chooseDestinationFolder(self, gesture):
		settings = _read_settings()

		def save_destination(path: str) -> None:
			if not path:
				return
			conf = config.conf[CONFIG_SECTION]
			conf["outputFolder"] = path
			conf["sameFolder"] = False
			config.conf.save()
			ui.message(_("Destination folder: {folder}").format(folder=path))

		self._show_folder_picker(
			_("Choose the destination folder"),
			settings.output_folder,
			save_destination,
		)

	@script(
		# Translators: Input gesture description.
		description=_("Cancel the current audio conversion"),
		category=SCRIPT_CATEGORY,
	)
	def script_cancelConversion(self, gesture):
		controllers = self._conversion_controllers()
		if not controllers:
			ui.message(_("No conversion is in progress"))
			return
		for controller in controllers:
			converter = getattr(controller, "_converter", None)
			if converter is not None:
				converter.cancel()
		if len(controllers) == 1:
			ui.message(_("Canceling the conversion"))
		else:
			ui.message(
				_("Canceling {count} active conversions").format(count=len(controllers))
			)

	@script(
		description=_("Stop the conversion after the current file"),
		category=SCRIPT_CATEGORY,
	)
	def script_stopAfterCurrent(self, gesture):
		controllers = self._conversion_controllers()
		if not controllers:
			ui.message(_("No conversion is in progress"))
			return
		for controller in controllers:
			converter = getattr(controller, "_converter", None)
			if converter is not None:
				converter.stop_after_current()
		if len(controllers) == 1:
			ui.message(_("The conversion will stop after the current file"))
		else:
			ui.message(
				_("The {count} active conversions will stop after their current files").format(
					count=len(controllers)
				)
			)

	@script(
		description=_("Report queued conversion jobs"),
		category=SCRIPT_CATEGORY,
	)
	def script_reportQueue(self, gesture):
		count = len(getattr(self, "_job_queue", ()))
		active_count = len(self._conversion_controllers())
		if active_count == 1 and getattr(self, "_converter", None) is not None:
			ui.message(
				_("One conversion is active. Queued jobs: {count}.").format(count=count)
			)
		elif active_count == 1:
			ui.message(
				_("One separate conversion is active. Queued jobs: {count}.").format(
					count=count
				)
			)
		elif active_count > 1:
			ui.message(
				_("Active conversions: {active}. Queued jobs: {count}.").format(
					active=active_count,
					count=count,
				)
			)
		elif count:
			ui.message(_("Queued conversion jobs: {count}.").format(count=count))
		else:
			ui.message(_("The conversion queue is empty"))

	@script(
		description=_("Clear queued conversion jobs"),
		category=SCRIPT_CATEGORY,
	)
	def script_clearQueue(self, gesture):
		queue = getattr(self, "_job_queue", None)
		if not queue:
			ui.message(_("The conversion queue is empty"))
			return
		count = len(queue)
		queue.clear()
		if self._progress_dialog is not None:
			self._progress_dialog.set_queue_count(0)
		ui.message(
			_("Cleared {count} queued conversion jobs").format(count=count)
		)

	@script(
		# Translators: Input gesture description.
		description=_("Show the audio conversion progress window"),
		category=SCRIPT_CATEGORY,
	)
	def script_showProgress(self, gesture):
		dialogs = []
		if self._progress_dialog is not None:
			dialogs.append(self._progress_dialog)
		for controller in self._conversion_controllers(active_only=False):
			if controller is self:
				continue
			dialog = getattr(controller, "_progress_dialog", None)
			if dialog is not None:
				dialogs.append(dialog)
		if not dialogs:
			ui.message(_("No conversion progress is available"))
			return
		for dialog in dialogs:
			dialog.show_window()

	@script(
		# Translators: Input gesture description.
		description=_("Show the last audio conversion results"),
		category=SCRIPT_CATEGORY,
	)
	def script_showResults(self, gesture):
		controller = getattr(self, "_last_results_controller", None)
		if controller is not None and getattr(controller, "_last_summary", None) is not None:
			controller._show_results_dialog()
		else:
			self._show_results_dialog()

	@script(
		# Translators: Input gesture description.
		description=_("Report audio conversion status"),
		category=SCRIPT_CATEGORY,
	)
	def script_reportStatus(self, gesture):
		controllers = self._conversion_controllers()
		if not controllers:
			ui.message(_("No conversion is in progress"))
			return
		if len(controllers) == 1:
			controller = controllers[0]
			status = self._controller_status(controller)
			if getattr(controller, "_progress", None) is None:
				ui.message(
					_("{status}. Queued jobs: {count}.").format(
						status=status,
						count=len(getattr(self, "_job_queue", ())),
					)
				)
			else:
				ui.message(
					_("{status} Queued jobs: {count}.").format(
						status=status,
						count=len(getattr(self, "_job_queue", ())),
					)
				)
			return
		ui.message(_("Active conversions: {count}.").format(count=len(controllers)))
		for index, controller in enumerate(controllers, start=1):
			if controller is self:
				label = _("Main conversion")
			else:
				label = _("Separate conversion {index}").format(
					index=getattr(controller, "_parallel_task_id", index),
				)
			ui.message(
				_("{label}: {status}").format(
					label=label,
					status=self._controller_status(controller),
				)
			)
		if getattr(self, "_job_queue", None):
			ui.message(
				_("Queued jobs: {count}.").format(
					count=len(self._job_queue),
				)
			)

	@script(
		# Translators: Input gesture description.
		description=_("Check for Easy Audio Converter updates"),
		category=SCRIPT_CATEGORY,
	)
	def script_checkForUpdates(self, gesture):
		self._start_update_check(silent=False)

	@script(
		# Translators: Input gesture description.
		description=_("Open the author's support page"),
		category=SCRIPT_CATEGORY,
	)
	def script_openSupportPage(self, gesture):
		_open_support_page()
