"""Easy Audio Converter global plug-in for NVDA."""

from __future__ import annotations

import ctypes
import json
import os
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable

import addonHandler
import api
import config
import globalPluginHandler
import gui
import ui
import wx
from gui import guiHelper
from gui.settingsDialogs import NVDASettingsDialog, SettingsPanel
from logHandler import log
from scriptHandler import script

try:
	import globalVars
except Exception:
	globalVars = None

from .converter import (
	ADVANCED_BIT_DEPTHS,
	ADVANCED_CHANNEL_COUNTS,
	ADVANCED_SAMPLE_RATES,
	DEFAULT_METADATA_FIELDS,
	FORMAT_KEYS,
	METADATA_FIELD_KEYS,
	METADATA_MODE_KEYS,
	MP3_ENCODER_KEYS,
	QUALITY_KEYS,
	ConversionCallbacks,
	ConversionSettings,
	ConversionSummary,
	Converter,
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
ADDON_VERSION = "1.1.2"
CONFIG_SECTION = "easyAudioConverter"
SUPPORT_URL = "https://buycoffee.to/kazimierz-parzych"
CONFIG_SPEC = {
	"targetFormat": "string(default='mp3')",
	"quality": "string(default='high')",
	"mp3Encoder": "string(default='lame')",
	"sameFolder": "boolean(default=True)",
	"outputFolder": "string(default='')",
	"includeSubfolders": "boolean(default=True)",
	"preserveFolderStructure": "boolean(default=True)",
	"metadataMode": "string(default='all')",
	"metadataFields": (
		"string_list(default=list('title', 'artist', 'album', 'album_artist', "
		"'composer', 'genre', 'date', 'track', 'disc'))"
	),
	"advancedProfiles": "string(default='{}')",
	"autoCheckUpdates": "boolean(default=True)",
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
	profiles = _load_advanced_profiles(conf.get("advancedProfiles", "{}"))
	return ConversionSettings(
		target_format=target_format,
		quality=_validated_key(conf.get("quality"), QUALITY_KEYS, "high"),
		mp3_encoder=_validated_key(conf.get("mp3Encoder"), MP3_ENCODER_KEYS, "lame"),
		same_folder=bool(conf.get("sameFolder", True)),
		output_folder=str(conf.get("outputFolder") or _default_output_folder()),
		include_subfolders=bool(conf.get("includeSubfolders", True)),
		preserve_folder_structure=bool(conf.get("preserveFolderStructure", True)),
		metadata_mode=_validated_key(conf.get("metadataMode"), METADATA_MODE_KEYS, "all"),
		metadata_fields=metadata_fields,
		advanced_options=profiles.get(target_format, {}),
	)


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
	}


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
	}


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


def _top_level_foreground_window() -> int:
	user32 = ctypes.windll.user32
	user32.GetForegroundWindow.restype = ctypes.c_void_p
	user32.GetAncestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
	user32.GetAncestor.restype = ctypes.c_void_p
	foreground = int(user32.GetForegroundWindow() or 0)
	root = int(user32.GetAncestor(foreground, 2) or 0)
	return root or foreground


def _explorer_context() -> tuple[list[str], str]:
	"""Return selected Explorer paths and the current Explorer folder."""
	try:
		from comtypes.client import CreateObject

		foreground = _top_level_foreground_window()
		shell = CreateObject("Shell.Application", dynamic=True)
		windows = shell.Windows()
		best_selection: list[str] = []
		best_folder = ""
		for index in range(int(windows.Count)):
			window = windows.Item(index)
			try:
				if int(window.HWND) != foreground:
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
					best_selection = selection
					best_folder = folder
				elif not best_folder:
					best_folder = folder
			except Exception:
				continue
		if best_folder:
			return best_selection, best_folder
	except Exception:
		pass
	return [], ""


def _focused_path(current_folder: str = "") -> str:
	"""Best-effort fallback for a focused item outside Explorer's COM selection."""
	try:
		obj = api.getFocusObject()
	except Exception:
		return ""
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


class EasyAudioConverterSettingsPanel(SettingsPanel):
	# Translators: Title of the add-on settings category.
	title = _("Easy Audio Converter")

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

		self.auto_check_updates = helper.addItem(
			# Translators: Automatically query GitHub for a newer add-on release.
			wx.CheckBox(self, label=_("Automatically check for add-on updates")),
		)
		self.auto_check_updates.SetValue(
			bool(config.conf[CONFIG_SECTION].get("autoCheckUpdates", True))
		)

		self.support_button = helper.addItem(
			# Translators: Opens the author's support page.
			wx.Button(self, label=_("Support the author")),
		)

		self.target_format.Bind(wx.EVT_CHOICE, self._update_control_state)
		self.same_folder.Bind(wx.EVT_CHECKBOX, self._update_control_state)
		self.metadata_mode.Bind(wx.EVT_CHOICE, self._update_control_state)
		self.browse_button.Bind(wx.EVT_BUTTON, self._on_browse)
		self.support_button.Bind(wx.EVT_BUTTON, self._on_support)
		self._update_control_state()

	def _update_control_state(self, event=None):
		is_mp3 = FORMAT_KEYS[self.target_format.GetSelection()] == "mp3"
		self.mp3_encoder.Enable(is_mp3)
		use_destination = not self.same_folder.IsChecked()
		self.output_folder.Enable(use_destination)
		self.browse_button.Enable(use_destination)
		self.preserve_structure.Enable(use_destination)
		copy_selected_metadata = (
			METADATA_MODE_KEYS[self.metadata_mode.GetSelection()] == "selected"
		)
		self.metadata_fields_sizer.GetStaticBox().Enable(copy_selected_metadata)
		for checkbox in self.metadata_fields:
			checkbox.Enable(copy_selected_metadata)

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

	def _on_support(self, event):
		_open_support_page()

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
		conf["metadataMode"] = METADATA_MODE_KEYS[self.metadata_mode.GetSelection()]
		conf["metadataFields"] = [
			field_name
			for field_name, checkbox in zip(METADATA_FIELD_KEYS, self.metadata_fields)
			if checkbox.IsChecked()
		]
		conf["autoCheckUpdates"] = self.auto_check_updates.IsChecked()
		config.conf.save()


def _default_advanced_profile() -> dict[str, Any]:
	return {
		"enabled": False,
		"bitrate": 0,
		"sampleRate": 0,
		"channels": 0,
		"codecLevel": -1,
		"bitDepth": 0,
	}


class EasyAudioConverterAdvancedSettingsPanel(SettingsPanel):
	# Translators: Title of the advanced codec settings category.
	title = _("Easy Audio Converter - Advanced")

	_BITRATE_FORMATS = {"mp3", "opus", "m4a", "aac", "wma", "ac3", "eac3", "mp2", "amr", "amrwb"}
	_LEVEL_FORMATS = {"mp3", "flac", "ogg", "opus", "wavpack"}
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
		self._profiles[self._current_format] = {
			"enabled": self.enabled.IsChecked(),
			"bitrate": self.bitrate.GetValue(),
			"sampleRate": ADVANCED_SAMPLE_RATES[self.sample_rate.GetSelection()],
			"channels": ADVANCED_CHANNEL_COUNTS[self.channels.GetSelection()],
			"codecLevel": self.codec_level.GetValue(),
			"bitDepth": ADVANCED_BIT_DEPTHS[self.bit_depth.GetSelection()],
		}

	def _load_profile(self, format_key: str) -> None:
		profile = self._profile(format_key)
		self.enabled.SetValue(bool(profile["enabled"]))
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
		self.codec_level.SetValue(max(-1, min(12, _safe_int(profile["codecLevel"], -1))))
		bit_depth = _safe_int(profile["bitDepth"], 0)
		self.bit_depth.SetSelection(
			ADVANCED_BIT_DEPTHS.index(bit_depth)
			if bit_depth in ADVANCED_BIT_DEPTHS
			else 0
		)
		self._update_control_state()

	def _on_codec_changed(self, event):
		self._store_current_profile()
		self._current_format = FORMAT_KEYS[self.codec.GetSelection()]
		self._load_profile(self._current_format)

	def _update_control_state(self, event=None):
		enabled = self.enabled.IsChecked()
		self.bitrate.Enable(enabled and self._current_format in self._BITRATE_FORMATS)
		self.sample_rate.Enable(enabled and self._current_format not in {"amr", "amrwb", "opus"})
		self.channels.Enable(enabled and self._current_format not in {"amr", "amrwb"})
		self.codec_level.Enable(enabled and self._current_format in self._LEVEL_FORMATS)
		self.bit_depth.Enable(enabled and self._current_format in self._BIT_DEPTH_FORMATS)
		level_descriptions = {
			"mp3": _("For LAME MP3, level 0 is the slowest and highest algorithm quality; 9 is fastest."),
			"flac": _("For FLAC, level 0 is fastest and level 12 gives the strongest compression."),
			"ogg": _("For Ogg Vorbis, levels 0 to 10 select increasing variable-bitrate quality."),
			"opus": _("For Opus, levels 0 to 10 select increasing encoder complexity."),
			"wavpack": _("For WavPack, levels 0 to 8 select increasing compression effort."),
		}
		self.level_help.SetLabel(
			level_descriptions.get(
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
		config.conf.save()


def _format_elapsed(seconds: float | None) -> str:
	seconds = max(0, int(seconds or 0))
	hours, remainder = divmod(seconds, 3600)
	minutes, seconds = divmod(remainder, 60)
	if hours:
		return f"{hours:d}:{minutes:02d}:{seconds:02d}"
	return f"{minutes:d}:{seconds:02d}"


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
		on_report: Callable[[], None],
	):
		super().__init__(
			parent,
			title=_("Easy Audio Converter progress"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._on_cancel_callback = on_cancel
		self._on_report_callback = on_report
		self._running = True
		self._cancel_requested = False
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.current_file = wx.StaticText(panel, label=_("Preparing the conversion"))
		sizer.Add(self.current_file, 0, wx.ALL | wx.EXPAND, 8)
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

		button_sizer = wx.BoxSizer(wx.HORIZONTAL)
		self.cancel_button = wx.Button(panel, label=_("Cancel conversion"))
		self.report_button = wx.Button(panel, label=_("Report conversion status"))
		self.hide_button = wx.Button(panel, label=_("Hide"))
		button_sizer.Add(self.cancel_button, 0, wx.RIGHT, 8)
		button_sizer.Add(self.report_button, 0, wx.RIGHT, 8)
		button_sizer.Add(self.hide_button, 0)
		sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer_sizer = wx.BoxSizer(wx.VERTICAL)
		outer_sizer.Add(panel, 1, wx.EXPAND)
		self.SetSizerAndFit(outer_sizer)
		self.SetMinSize((560, self.GetSize().height))
		self.CentreOnParent()
		self.cancel_button.Bind(wx.EVT_BUTTON, self._on_cancel)
		self.report_button.Bind(wx.EVT_BUTTON, self._on_report)
		self.hide_button.Bind(wx.EVT_BUTTON, self._on_hide)
		self.Bind(wx.EVT_CLOSE, self._on_close)

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

	def finish(self, message: str, completed: bool) -> None:
		self._running = False
		self.current_file.SetLabel(message)
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
		self.report_button.Disable()

	def _on_cancel(self, event):
		if self._running and not self._cancel_requested:
			self._cancel_requested = True
			self.cancel_button.SetLabel(_("Canceling..."))
			self._on_cancel_callback()

	def _on_report(self, event):
		if self._running:
			self._on_report_callback()

	def _on_hide(self, event):
		self.Hide()

	def _on_close(self, event):
		self.Hide()
		if event.CanVeto():
			event.Veto()


SCRIPT_CATEGORY = _("Easy Audio Converter")


def _destroy_hidden_nvda_settings_dialogs() -> int:
	"""Remove stale hidden settings windows which block a new visible dialog."""
	try:
		windows = tuple(wx.GetTopLevelWindows())
	except Exception:
		log.debugWarning(
			"Easy Audio Converter: could not inspect NVDA settings windows",
			exc_info=True,
		)
		return 0
	destroyed = 0
	for window in windows:
		try:
			if isinstance(window, NVDASettingsDialog) and not window.IsShown():
				window.Destroy()
				destroyed += 1
		except Exception:
			log.debugWarning(
				"Easy Audio Converter: could not discard a hidden NVDA settings window",
				exc_info=True,
			)
	return destroyed


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = SCRIPT_CATEGORY

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		_ensure_config()
		self._converter: Converter | None = None
		self._worker: threading.Thread | None = None
		self._progress: tuple[int, int, str, float | None, float, float, float | None, float] | None = None
		self._progress_dialog: ConversionProgressDialog | None = None
		self._job_started_at = 0.0
		self._update_check_thread: threading.Thread | None = None
		self._update_download_thread: threading.Thread | None = None
		self._update_cancel_event: threading.Event | None = None
		self._update_progress_dialog = None
		self._update_timer = None
		self._settings_open_timer = None
		self._terminated = False
		self._menu: wx.Menu | None = None
		self._menu_root_item = None
		self._menu_bindings: list[tuple[Any, Callable]] = []
		if EasyAudioConverterSettingsPanel not in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.append(EasyAudioConverterSettingsPanel)
		if EasyAudioConverterAdvancedSettingsPanel not in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.append(EasyAudioConverterAdvancedSettingsPanel)
		self._install_menu()
		if self._updates_allowed() and bool(
			config.conf[CONFIG_SECTION].get("autoCheckUpdates", True)
		):
			self._update_timer = wx.CallLater(8000, self._start_update_check, True)

	def terminate(self):
		self._terminated = True
		converter = self._converter
		if converter is not None:
			converter.cancel()
		worker = self._worker
		if worker is not None and worker.is_alive():
			worker.join(timeout=3)
		if self._update_timer is not None:
			try:
				self._update_timer.Stop()
			except Exception:
				pass
		if self._settings_open_timer is not None:
			try:
				self._settings_open_timer.Stop()
			except Exception:
				pass
			self._settings_open_timer = None
		if self._update_cancel_event is not None:
			self._update_cancel_event.set()
		try:
			self._remove_menu()
			if EasyAudioConverterSettingsPanel in NVDASettingsDialog.categoryClasses:
				NVDASettingsDialog.categoryClasses.remove(EasyAudioConverterSettingsPanel)
			if EasyAudioConverterAdvancedSettingsPanel in NVDASettingsDialog.categoryClasses:
				NVDASettingsDialog.categoryClasses.remove(EasyAudioConverterAdvancedSettingsPanel)
			if self._progress_dialog is not None:
				self._progress_dialog.Destroy()
				self._progress_dialog = None
			if self._update_progress_dialog is not None:
				self._update_progress_dialog.Destroy()
				self._update_progress_dialog = None
		finally:
			super().terminate()

	def _install_menu(self) -> None:
		try:
			tray = gui.mainFrame.sysTrayIcon
			tools_menu = tray.toolsMenu
			self._menu = wx.Menu()
			entries: tuple[tuple[str | None, Callable | None], ...] = (
				(_("Convert selected files or folders"), self.script_convertSelection),
				(_("Convert the current folder"), self.script_convertCurrentFolder),
				(_("Show conversion progress"), self.script_showProgress),
				(_("Report conversion status"), self.script_reportStatus),
				(_("Cancel conversion"), self.script_cancelConversion),
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
					action(None)

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
				tray.toolsMenu.Remove(self._menu_root_item)
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

	def _is_busy(self) -> bool:
		return self._converter is not None

	def _open_settings_panel(self, panel_class: type[SettingsPanel]) -> None:
		if self._settings_open_timer is not None:
			try:
				self._settings_open_timer.Stop()
			except Exception:
				pass
			self._settings_open_timer = None
		removed_hidden_dialog = bool(_destroy_hidden_nvda_settings_dialogs())

		def open_dialog() -> None:
			self._settings_open_timer = None
			if self._terminated:
				return
			gui.mainFrame.popupSettingsDialog(
				NVDASettingsDialog,
				panel_class,
			)

		if removed_hidden_dialog:
			# Let wx finish destroying the stale instance before constructing
			# another NVDASettingsDialog of the same class.
			self._settings_open_timer = wx.CallLater(100, open_dialog)
		else:
			open_dialog()

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
	) -> None:
		if self._is_busy():
			ui.message(_("A conversion is already in progress"))
			return
		ffmpeg_path = self._ffmpeg_path()
		if not ffmpeg_path.is_file():
			gui.messageBox(
				_("The bundled FFmpeg component is missing. Reinstall Easy Audio Converter."),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				gui.mainFrame,
			)
			return
		settings = _read_settings()
		converter = Converter(ffmpeg_path)
		self._converter = converter
		self._progress = None
		self._job_started_at = time.monotonic()
		if self._progress_dialog is not None:
			self._progress_dialog.Destroy()
		self._progress_dialog = ConversionProgressDialog(
			gui.mainFrame,
			lambda: self.script_cancelConversion(None),
			lambda: self.script_reportStatus(None),
		)
		self._progress_dialog.show_window()
		ui.message(_("Preparing the conversion"))

		def on_collected(total: int, ignored: int) -> None:
			if total:
				if ignored:
					message = _("Files to convert: {count}. Skipped: {skipped}.").format(
						count=total,
						skipped=ignored,
					)
				else:
					message = _("Found {count} files to convert").format(count=total)
				wx.CallAfter(ui.message, message)

		def on_file_start(index: int, total: int, source_name: str, output_name: str) -> None:
			percentage = int(index * 100 / max(1, total))
			previous_percentage = int((index - 1) * 100 / max(1, total))
			announce = total <= 10 or index in {1, total} or percentage // 10 > previous_percentage // 10
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

		callbacks = ConversionCallbacks(
			on_collected=on_collected,
			on_file_start=on_file_start,
			on_progress=on_progress,
		)

		def run_job() -> None:
			try:
				summary = converter.run(
					paths,
					settings,
					source_root=source_root,
					callbacks=callbacks,
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
		if self._terminated:
			return
		if self._progress_dialog is not None:
			self._progress_dialog.finish(
				_("The conversion could not start"),
				completed=False,
			)
		gui.messageBox(
			_("The conversion could not start:\n{error}").format(error=message),
			_("Easy Audio Converter"),
			wx.OK | wx.ICON_ERROR,
			gui.mainFrame,
		)

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
		ui.message(message)
		if self._progress_dialog is not None:
			self._progress_dialog.finish(
				message,
				completed=bool(summary.total and not summary.canceled),
			)
		self._converter = None
		self._worker = None
		self._progress = None
		if summary.failures:
			lines = []
			for failure in summary.failures[:8]:
				last_line = failure.message.splitlines()[-1] if failure.message else _("Unknown error")
				lines.append(f"{failure.source_name}: {last_line[:300]}")
			if len(summary.failures) > len(lines):
				lines.append(
					_("...and {count} more errors").format(count=len(summary.failures) - len(lines))
				)
			gui.messageBox(
				_("Some files could not be converted:\n\n{details}").format(details="\n".join(lines)),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_WARNING,
				gui.mainFrame,
			)

	def _selection_for_conversion(self) -> tuple[list[str], str | None]:
		selection, current_folder = _explorer_context()
		if not selection:
			focused = _focused_path(current_folder)
			if focused:
				selection = [focused]
		source_root = selection[0] if len(selection) == 1 and os.path.isdir(selection[0]) else None
		return selection, source_root

	def _confirm_folder_conversion(self, folder_description: str) -> bool:
		settings = _read_settings()
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

	@script(
		# Translators: Input gesture description.
		description=_("Open Easy Audio Converter settings"),
		category=SCRIPT_CATEGORY,
	)
	def script_openSettings(self, gesture):
		wx.CallAfter(
			self._open_settings_panel,
			EasyAudioConverterSettingsPanel,
		)

	@script(
		# Translators: Input gesture description.
		description=_("Open advanced codec settings"),
		category=SCRIPT_CATEGORY,
	)
	def script_openAdvancedSettings(self, gesture):
		wx.CallAfter(
			self._open_settings_panel,
			EasyAudioConverterAdvancedSettingsPanel,
		)

	@script(
		# Translators: Input gesture description.
		description=_("Quickly convert selected files or folders"),
		category=SCRIPT_CATEGORY,
	)
	def script_convertSelection(self, gesture):
		selection, source_root = self._selection_for_conversion()
		if not selection:
			ui.message(_("No files or folders are selected"))
			return
		selected_folders = [path for path in selection if os.path.isdir(path)]
		if selected_folders:
			description = (
				os.path.basename(selected_folders[0].rstrip("\\/"))
				if len(selected_folders) == 1
				else _("{count} selected folders").format(count=len(selected_folders))
			)
			if not self._confirm_folder_conversion(description):
				return
		self._start_conversion(selection, source_root=source_root)

	@script(
		# Translators: Input gesture description.
		description=_("Convert every supported audio file in the current folder"),
		category=SCRIPT_CATEGORY,
	)
	def script_convertCurrentFolder(self, gesture):
		_selection, folder = _explorer_context()
		if not folder or not os.path.isdir(folder):
			dialog = wx.DirDialog(
				gui.mainFrame,
				_("Choose a folder to convert"),
				defaultPath=str(Path.home()),
				style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
			)
			try:
				if dialog.ShowModal() != wx.ID_OK:
					return
				folder = dialog.GetPath()
			finally:
				dialog.Destroy()
		description = os.path.basename(folder.rstrip("\\/")) or folder
		if self._confirm_folder_conversion(description):
			self._start_conversion([folder], source_root=folder)

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
		dialog = wx.DirDialog(
			gui.mainFrame,
			_("Choose the destination folder"),
			defaultPath=settings.output_folder,
			style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
		)
		try:
			if dialog.ShowModal() != wx.ID_OK:
				return
			path = dialog.GetPath()
		finally:
			dialog.Destroy()
		conf = config.conf[CONFIG_SECTION]
		conf["outputFolder"] = path
		conf["sameFolder"] = False
		config.conf.save()
		ui.message(_("Destination folder: {folder}").format(folder=path))

	@script(
		# Translators: Input gesture description.
		description=_("Cancel the current audio conversion"),
		category=SCRIPT_CATEGORY,
	)
	def script_cancelConversion(self, gesture):
		if not self._is_busy() or self._converter is None:
			ui.message(_("No conversion is in progress"))
			return
		self._converter.cancel()
		ui.message(_("Canceling the conversion"))

	@script(
		# Translators: Input gesture description.
		description=_("Show the audio conversion progress window"),
		category=SCRIPT_CATEGORY,
	)
	def script_showProgress(self, gesture):
		if self._progress_dialog is None:
			ui.message(_("No conversion progress is available"))
			return
		self._progress_dialog.show_window()

	@script(
		# Translators: Input gesture description.
		description=_("Report audio conversion status"),
		category=SCRIPT_CATEGORY,
	)
	def script_reportStatus(self, gesture):
		if not self._is_busy():
			ui.message(_("No conversion is in progress"))
			return
		if self._progress is None:
			ui.message(_("Preparing the conversion"))
			return
		(
			index,
			total,
			source_name,
			file_fraction,
			overall_fraction,
			processed_seconds,
			duration,
			elapsed_seconds,
		) = self._progress
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
		ui.message(message)

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
