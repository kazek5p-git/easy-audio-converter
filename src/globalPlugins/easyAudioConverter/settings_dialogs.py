# Copyright (C) 2026 Kazimierz Parzych
# SPDX-License-Identifier: GPL-3.0-or-later
"""Okna ustawień i dialogi opcji Easy Audio Converter dla NVDA."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import config
import gui
import ui
import wx
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel
from logHandler import log
from wx.lib import scrolledpanel

from . import (
	_,
	ADVANCED_BIT_DEPTHS,
	ADVANCED_CHANNEL_COUNTS,
	ADVANCED_SAMPLE_RATES,
	BUSY_CONVERSION_MODE_KEYS,
	CANCEL_SOUND_PATH,
	COMPLETION_NOTIFICATION_KEYS,
	CONFIG_SECTION,
	ERROR_SOUND_PATH,
	FLAC_COMPRESSION_LEVELS,
	FORMAT_KEYS,
	GOGO_BITRATE_PRESETS,
	GOGO_QUALITY_VALUES,
	LOUDNESS_PRESET_KEYS,
	MAX_PROFILE_DOCUMENT_BYTES,
	METADATA_FIELD_KEYS,
	METADATA_MODE_KEYS,
	MP3_ENCODER_KEYS,
	ORIGINAL_AUDIO_COPY_FORMAT,
	PARALLEL_JOB_COUNTS,
	PROGRESS_ANNOUNCEMENT_KEYS,
	QUALITY_KEYS,
	STREAM_COPY_FORMATS,
	WAVPACK_COMPRESSION_PROFILES,
	ConversionSettings,
	_add_labeled_spin_double,
	_builtin_conversion_profiles,
	_busy_conversion_mode_labels,
	_completion_notification_labels,
	_default_output_folder,
	_dump_metadata_overrides,
	_ensure_config,
	_format_labels,
	_load_advanced_profiles,
	_load_user_conversion_profiles,
	_loudness_preset_labels,
	_metadata_field_labels,
	_metadata_mode_labels,
	_mp3_encoder_labels,
	read_gogo_help,
	validate_gogo_options,
	_open_support_page,
	_output_name_preview,
	_parallel_job_labels,
	_progress_announcement_labels,
	_quality_labels,
	_read_busy_conversion_mode,
	_read_notification_preferences,
	_read_settings,
	resolve_gogo_path,
	_safe_int,
	_save_user_conversion_profiles,
	_stream_copy_description,
	_validated_key,
	_write_conversion_settings,
	dump_user_profiles,
	load_user_profiles,
	merge_user_profiles,
	normalize_metadata_overrides,
	normalize_profile_name,
	remove_user_profile,
	render_output_name,
	upsert_user_profile,
	validate_output_name_template,
)
from .conversion_dialogs import _play_completion_sound, _play_event_sound


def _gogo_bitrate_labels() -> dict[int, str]:
	return {
		0: _("Define manually in GOGO arguments"),
		64: _("64 kb/s joint stereo"),
		128: _("128 kb/s joint stereo"),
		160: _("160 kb/s joint stereo"),
		192: _("192 kb/s joint stereo"),
		256: _("256 kb/s stereo"),
		320: _("320 kb/s stereo"),
	}


def _gogo_quality_labels() -> list[str]:
	return [
		_("GOGO Q {value} — highest quality").format(value=value)
		if value == 0
		else _("GOGO Q {value} — fastest at Q9").format(value=value)
		if value == 9
		else _("GOGO Q {value}").format(value=value)
		for value in GOGO_QUALITY_VALUES
	]


class GogoHelpDialog(wx.Dialog):
	"""Wyświetl pomoc zwróconą przez zewnętrzny proces GOGO."""

	def __init__(self, parent, executable: str):
		super().__init__(
			parent,
			title=_("GOGO commands"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		try:
			help_text = read_gogo_help(executable)
		except Exception as error:
			help_text = _("Could not read GOGO help:\n{error}").format(error=error)
		self.text = wx.TextCtrl(
			panel,
			value=help_text,
			style=wx.TE_MULTILINE | wx.TE_READONLY | getattr(wx, "HSCROLL", 0),
		)
		sizer.Add(self.text, 1, wx.ALL | wx.EXPAND, 8)
		buttons = wx.StdDialogButtonSizer()
		buttons.AddButton(wx.Button(panel, wx.ID_CLOSE))
		buttons.Realize()
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizerAndFit(outer)
		self.SetSize((720, 520))
		self.SetMinSize((500, 320))
		self.CentreOnParent()
		self.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(wx.ID_CLOSE), id=wx.ID_CLOSE)


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
		self.gogo_path = helper.addLabeledControl(
			_("GOGO executable (gogo.exe):"),
			wx.TextCtrl,
		)
		self.gogo_path.SetValue(settings.gogo_path)
		self.gogo_browse_button = helper.addItem(
			wx.Button(self, label=_("Browse for GOGO executable..."))
		)
		gogo_bitrate_labels = _gogo_bitrate_labels()
		self.gogo_bitrate = helper.addLabeledControl(
			_("GOGO bitrate:"),
			wx.Choice,
			choices=[gogo_bitrate_labels[key] for key in GOGO_BITRATE_PRESETS],
		)
		self.gogo_bitrate.SetSelection(
			GOGO_BITRATE_PRESETS.index(settings.gogo_bitrate)
			if settings.gogo_bitrate in GOGO_BITRATE_PRESETS
			else 0
		)
		self.gogo_quality = helper.addLabeledControl(
			_("GOGO quality:"),
			wx.Choice,
			choices=_gogo_quality_labels(),
		)
		self.gogo_quality.SetSelection(
			settings.gogo_quality
			if settings.gogo_quality in GOGO_QUALITY_VALUES
			else 0
		)
		self.gogo_extra_arguments = helper.addLabeledControl(
			_("Additional GOGO arguments:"),
			wx.TextCtrl,
		)
		self.gogo_extra_arguments.SetValue(settings.gogo_extra_arguments)
		self.gogo_help_button = helper.addItem(
			wx.Button(self, label=_("Show GOGO commands"))
		)
		self.gogo_note = helper.addItem(wx.StaticText(self, label=""))

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
		self.mp3_encoder.Bind(wx.EVT_CHOICE, self._update_control_state)
		self.same_folder.Bind(wx.EVT_CHECKBOX, self._update_control_state)
		self.metadata_mode.Bind(wx.EVT_CHOICE, self._update_control_state)
		self.metadata_overrides_button.Bind(wx.EVT_BUTTON, self._on_metadata_overrides)
		self.output_name_template.Bind(wx.EVT_TEXT, self._update_name_preview)
		self.browse_button.Bind(wx.EVT_BUTTON, self._on_browse)
		self.gogo_browse_button.Bind(wx.EVT_BUTTON, self._on_gogo_browse)
		self.gogo_help_button.Bind(wx.EVT_BUTTON, self._on_gogo_help)
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
		is_gogo = is_mp3 and MP3_ENCODER_KEYS[self.mp3_encoder.GetSelection()] == "gogo"
		self.quality.Enable(not stream_copy)
		self.mp3_encoder.Enable(is_mp3)
		for control in (
			self.gogo_path,
			self.gogo_browse_button,
			self.gogo_bitrate,
			self.gogo_quality,
			self.gogo_extra_arguments,
			self.gogo_help_button,
		):
			control.Enable(is_gogo)
		self.stream_copy_note.SetLabel(_stream_copy_description(target_format))
		self.stream_copy_note.Show(stream_copy)
		self.gogo_note.SetLabel(
			_(
				"GOGO encodes WAV/WAVE files to MP3 without metadata or loudness "
				"processing. The add-on includes GOGO-no-coda; leave the executable "
				"field empty to use it, or choose another gogo.exe."
			)
			if is_gogo
			else ""
		)
		self.gogo_note.Show(is_gogo)
		if is_gogo:
			self.gogo_note.Wrap(max(360, self.GetClientSize().GetWidth() - 20))
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

	def _on_gogo_browse(self, event):
		current = self.gogo_path.GetValue().strip()
		dialog = wx.FileDialog(
			self,
			_("Choose the GOGO executable"),
			defaultDir=str(resolve_gogo_path(current).parent),
			wildcard=_("GOGO executable (gogo.exe)|gogo.exe|Executable files (*.exe)|*.exe|All files (*.*)|*.*"),
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
		)
		try:
			if dialog.ShowModal() == wx.ID_OK:
				self.gogo_path.SetValue(dialog.GetPath())
		finally:
			dialog.Destroy()

	def _on_gogo_help(self, event):
		path = self.gogo_path.GetValue().strip()
		dialog = GogoHelpDialog(self, path)
		try:
			dialog.ShowModal()
		finally:
			dialog.Destroy()

	def isValid(self) -> bool:
		try:
			validate_output_name_template(self.output_name_template.GetValue())
			if (
				FORMAT_KEYS[self.target_format.GetSelection()] == "mp3"
				and MP3_ENCODER_KEYS[self.mp3_encoder.GetSelection()] == "gogo"
			):
				validate_gogo_options(
					path=self.gogo_path.GetValue().strip(),
					bitrate=GOGO_BITRATE_PRESETS[self.gogo_bitrate.GetSelection()],
					quality=GOGO_QUALITY_VALUES[self.gogo_quality.GetSelection()],
					extra_arguments=self.gogo_extra_arguments.GetValue(),
				)
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
		conf["gogoPath"] = self.gogo_path.GetValue().strip()
		conf["gogoBitrate"] = GOGO_BITRATE_PRESETS[self.gogo_bitrate.GetSelection()]
		conf["gogoQuality"] = GOGO_QUALITY_VALUES[self.gogo_quality.GetSelection()]
		conf["gogoExtraArguments"] = self.gogo_extra_arguments.GetValue()
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
		self._is_gogo = (
			settings.target_format == "mp3" and settings.mp3_encoder == "gogo"
		)
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
		self.loudness_preset.Enable(not stream_copy and not self._is_gogo)
		custom = (
			not stream_copy
			and not self._is_gogo
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
		is_gogo = target_format == "mp3" and conf.get("mp3Encoder") == "gogo"
		conf["loudnessPreset"] = (
			"off"
			if target_format in STREAM_COPY_FORMATS or is_gogo
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
		self._is_gogo = (
			settings.target_format == "mp3" and settings.mp3_encoder == "gogo"
		)
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
		self.loudness_preset.Enable(not stream_copy and not self._is_gogo)
		custom = (
			not stream_copy
			and not self._is_gogo
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
				if stream_copy or self._is_gogo
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
		self.gogo_path = helper.addLabeledControl(
			_("GOGO executable (gogo.exe):"),
			wx.TextCtrl,
		)
		self.gogo_browse_button = helper.addItem(
			wx.Button(panel, label=_("Browse for GOGO executable..."))
		)
		gogo_bitrate_labels = _gogo_bitrate_labels()
		self.gogo_bitrate = helper.addLabeledControl(
			_("GOGO bitrate:"),
			wx.Choice,
			choices=[gogo_bitrate_labels[key] for key in GOGO_BITRATE_PRESETS],
		)
		self.gogo_quality = helper.addLabeledControl(
			_("GOGO quality:"),
			wx.Choice,
			choices=_gogo_quality_labels(),
		)
		self.gogo_extra_arguments = helper.addLabeledControl(
			_("Additional GOGO arguments:"),
			wx.TextCtrl,
		)
		self.gogo_help_button = helper.addItem(
			wx.Button(panel, label=_("Show GOGO commands"))
		)
		self.gogo_note = helper.addItem(wx.StaticText(panel, label=""))

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
		self.mp3_encoder.Bind(wx.EVT_CHOICE, self._update_control_state)
		self.gogo_path.Bind(wx.EVT_TEXT, self._on_setting_changed)
		self.gogo_bitrate.Bind(wx.EVT_CHOICE, self._on_setting_changed)
		self.gogo_quality.Bind(wx.EVT_CHOICE, self._on_setting_changed)
		self.gogo_extra_arguments.Bind(wx.EVT_TEXT, self._on_setting_changed)
		self.same_folder.Bind(wx.EVT_CHECKBOX, self._on_setting_changed)
		self.output_folder.Bind(wx.EVT_TEXT, self._on_setting_changed)
		self.output_name_template.Bind(wx.EVT_TEXT, self._on_setting_changed)
		self.include_subfolders.Bind(wx.EVT_CHECKBOX, self._on_setting_changed)
		self.preserve_structure.Bind(wx.EVT_CHECKBOX, self._on_setting_changed)
		self.preserve_timestamps.Bind(wx.EVT_CHECKBOX, self._on_setting_changed)
		self.replace_source_files.Bind(wx.EVT_CHECKBOX, self._on_setting_changed)
		self.metadata_mode.Bind(wx.EVT_CHOICE, self._on_setting_changed)
		self.browse_button.Bind(wx.EVT_BUTTON, self._on_browse)
		self.gogo_browse_button.Bind(wx.EVT_BUTTON, self._on_gogo_browse)
		self.gogo_help_button.Bind(wx.EVT_BUTTON, self._on_gogo_help)
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
			self.gogo_path.SetValue(settings.gogo_path)
			self.gogo_bitrate.SetSelection(
				GOGO_BITRATE_PRESETS.index(settings.gogo_bitrate)
				if settings.gogo_bitrate in GOGO_BITRATE_PRESETS
				else 0
			)
			self.gogo_quality.SetSelection(
				settings.gogo_quality
				if settings.gogo_quality in GOGO_QUALITY_VALUES
				else 0
			)
			self.gogo_extra_arguments.SetValue(settings.gogo_extra_arguments)
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
		selected_encoder = MP3_ENCODER_KEYS[max(0, self.mp3_encoder.GetSelection())]
		if target_format == "mp3" and selected_encoder == "gogo":
			advanced_options["enabled"] = False
		settings = replace(
			self._processing_settings,
			target_format=target_format,
			quality=QUALITY_KEYS[max(0, self.quality.GetSelection())],
			mp3_encoder=selected_encoder,
			gogo_path=self.gogo_path.GetValue().strip(),
			gogo_bitrate=GOGO_BITRATE_PRESETS[max(0, self.gogo_bitrate.GetSelection())],
			gogo_quality=GOGO_QUALITY_VALUES[max(0, self.gogo_quality.GetSelection())],
			gogo_extra_arguments=self.gogo_extra_arguments.GetValue(),
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
				"off"
				if stream_copy
				or (
					target_format == "mp3"
					and MP3_ENCODER_KEYS[max(0, self.mp3_encoder.GetSelection())] == "gogo"
				)
				else self._processing_settings.loudness_preset
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
		is_gogo = (
			target_format == "mp3"
			and MP3_ENCODER_KEYS[max(0, self.mp3_encoder.GetSelection())] == "gogo"
		)
		self.quality.Enable(not stream_copy)
		self.mp3_encoder.Enable(target_format == "mp3")
		for control in (
			self.gogo_path,
			self.gogo_browse_button,
			self.gogo_bitrate,
			self.gogo_quality,
			self.gogo_extra_arguments,
			self.gogo_help_button,
		):
			control.Enable(is_gogo)
		self.gogo_note.SetLabel(
			_(
				"GOGO encodes WAV/WAVE files to MP3 without metadata or loudness "
				"processing. The add-on includes GOGO-no-coda; leave the executable "
				"field empty to use it, or choose another gogo.exe."
			)
			if is_gogo
			else ""
		)
		self.gogo_note.Show(is_gogo)
		if is_gogo:
			self.gogo_note.Wrap(max(360, self.GetClientSize().GetWidth() - 20))
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
			else _("Advanced codec overrides are not used by GOGO") if is_gogo
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
		elif is_gogo:
			self.processing_status.SetLabel(
				_(
					"GOGO processing: WAV/WAVE input only; metadata, loudness, "
					"artwork, and chapters are not written."
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

	def _on_gogo_browse(self, event) -> None:
		current = self.gogo_path.GetValue().strip()
		dialog = wx.FileDialog(
			self,
			_("Choose the GOGO executable"),
			defaultDir=str(resolve_gogo_path(current).parent),
			wildcard=_(
				"GOGO executable (gogo.exe)|gogo.exe|Executable files (*.exe)|*.exe|"
				"All files (*.*)|*.*"
			),
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
		)
		try:
			if dialog.ShowModal() == wx.ID_OK:
				self.gogo_path.SetValue(dialog.GetPath())
		finally:
			dialog.Destroy()

	def _on_gogo_help(self, event) -> None:
		path = self.gogo_path.GetValue().strip()
		dialog = GogoHelpDialog(self, path)
		try:
			dialog.ShowModal()
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
