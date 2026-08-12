# Copyright (C) 2026 Kazimierz Parzych
# SPDX-License-Identifier: GPL-3.0-or-later
"""Easy Audio Converter global plug-in for NVDA."""

from __future__ import annotations

import ctypes
import json
import os
import webbrowser
from dataclasses import replace
from pathlib import Path
from typing import Any

import addonHandler
import api
import config
import gui
import nvwave
import ui
import wx
from gui import guiHelper
from logHandler import log

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
ADDON_VERSION = "1.8.2"
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


# Moduły interfejsu są importowane dopiero po zdefiniowaniu wspólnych ustawień
# i funkcji pomocniczych. Dzięki temu każdy z nich ma jasno określone zależności,
# a ten plik pozostaje cienką warstwą zgodności dla NVDA.
from .conversion_dialogs import (
	AudioInfoDialog,
	ConversionPlanDialog,
	ConversionProgressDialog,
	ConversionResultsDialog,
	_VisualProgressBar,
	_build_media_info_report,
	_build_plan_report,
	_build_results_report,
	_build_timing_report,
	_conversion_completed_successfully,
	_estimate_remaining,
	_event_sound_enabled,
	_format_bytes,
	_format_elapsed,
	_format_timing_seconds,
	_friendly_failure_message,
	_play_completion_sound,
	_play_event_sound,
	_skipped_reason_label,
	_stage_status_label,
)
from .settings_dialogs import (
	ConversionOptionsDialog,
	EasyAudioConverterSettingsDialog,
	JobProcessingOptionsDialog,
	MetadataFieldsDialog,
	MetadataOverridesDialog,
	_SettingsNotebookAccessible,
)
from .plugin import GlobalPlugin, SCRIPT_CATEGORY, _ConversionJob

from .settings_dialogs import _run_conversion_options_dialog, _default_advanced_profile, _lossless_compression_choices
