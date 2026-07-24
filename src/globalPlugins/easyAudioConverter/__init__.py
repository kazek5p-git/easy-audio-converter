"""Easy Audio Converter global plug-in for NVDA."""

from __future__ import annotations

import ctypes
import os
import threading
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

from .converter import (
	FORMAT_KEYS,
	MP3_ENCODER_KEYS,
	QUALITY_KEYS,
	ConversionCallbacks,
	ConversionSettings,
	ConversionSummary,
	Converter,
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
}


def _default_output_folder() -> str:
	return str(Path.home() / "Music" / ADDON_NAME)


def _ensure_config() -> None:
	config.conf.spec[CONFIG_SECTION] = CONFIG_SPEC


def _validated_key(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
	value = str(value or "")
	return value if value in allowed else fallback


def _read_settings() -> ConversionSettings:
	_ensure_config()
	conf = config.conf[CONFIG_SECTION]
	return ConversionSettings(
		target_format=_validated_key(conf.get("targetFormat"), FORMAT_KEYS, "mp3"),
		quality=_validated_key(conf.get("quality"), QUALITY_KEYS, "high"),
		mp3_encoder=_validated_key(conf.get("mp3Encoder"), MP3_ENCODER_KEYS, "lame"),
		same_folder=bool(conf.get("sameFolder", True)),
		output_folder=str(conf.get("outputFolder") or _default_output_folder()),
		include_subfolders=bool(conf.get("includeSubfolders", True)),
		preserve_folder_structure=bool(conf.get("preserveFolderStructure", True)),
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

		self.support_button = helper.addItem(
			# Translators: Opens the author's support page.
			wx.Button(self, label=_("Support the author")),
		)

		self.target_format.Bind(wx.EVT_CHOICE, self._update_control_state)
		self.same_folder.Bind(wx.EVT_CHECKBOX, self._update_control_state)
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
		config.conf.save()


SCRIPT_CATEGORY = _("Easy Audio Converter")


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = SCRIPT_CATEGORY

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		_ensure_config()
		self._converter: Converter | None = None
		self._worker: threading.Thread | None = None
		self._progress: tuple[int, int, str] | None = None
		self._terminated = False
		self._menu: wx.Menu | None = None
		self._menu_root_item = None
		self._menu_bindings: list[tuple[Any, Callable]] = []
		if EasyAudioConverterSettingsPanel not in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.append(EasyAudioConverterSettingsPanel)
		self._install_menu()

	def terminate(self):
		self._terminated = True
		converter = self._converter
		if converter is not None:
			converter.cancel()
		worker = self._worker
		if worker is not None and worker.is_alive():
			worker.join(timeout=3)
		try:
			self._remove_menu()
			if EasyAudioConverterSettingsPanel in NVDASettingsDialog.categoryClasses:
				NVDASettingsDialog.categoryClasses.remove(EasyAudioConverterSettingsPanel)
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
				(_("Report conversion status"), self.script_reportStatus),
				(_("Cancel conversion"), self.script_cancelConversion),
				(None, None),
				(_("Settings..."), self.script_openSettings),
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
		return self._worker is not None and self._worker.is_alive()

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
		ui.message(_("Preparing the conversion"))

		def on_collected(total: int, ignored: int) -> None:
			if total:
				wx.CallAfter(ui.message, _("Found {count} files to convert").format(count=total))

		def on_file_start(index: int, total: int, source_name: str, output_name: str) -> None:
			wx.CallAfter(self._set_progress, index, total, source_name)
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

		callbacks = ConversionCallbacks(
			on_collected=on_collected,
			on_file_start=on_file_start,
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

	def _set_progress(self, index: int, total: int, source_name: str) -> None:
		if not self._terminated:
			self._progress = (index, total, source_name)

	def _job_failed(self, converter: Converter, message: str) -> None:
		if converter is not self._converter:
			return
		self._converter = None
		self._worker = None
		self._progress = None
		if self._terminated:
			return
		gui.messageBox(
			_("The conversion could not start:\n{error}").format(error=message),
			_("Easy Audio Converter"),
			wx.OK | wx.ICON_ERROR,
			gui.mainFrame,
		)

	def _job_complete(self, converter: Converter, summary: ConversionSummary) -> None:
		if converter is not self._converter:
			return
		self._converter = None
		self._worker = None
		self._progress = None
		if self._terminated:
			return
		if summary.canceled:
			ui.message(
				_("Conversion canceled. Completed {done} of {total} files.").format(
					done=summary.succeeded,
					total=summary.total,
				)
			)
		elif summary.total == 0:
			ui.message(_("No supported audio files were found"))
		else:
			ui.message(
				_("Conversion complete: {done} succeeded, {failed} failed.").format(
					done=summary.succeeded,
					failed=summary.failed,
				)
			)
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
			gui.mainFrame.popupSettingsDialog,
			NVDASettingsDialog,
			EasyAudioConverterSettingsPanel,
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
		index, total, source_name = self._progress
		ui.message(
			_("Converting {index} of {total}: {name}").format(
				index=index,
				total=total,
				name=source_name,
			)
		)

	@script(
		# Translators: Input gesture description.
		description=_("Open the author's support page"),
		category=SCRIPT_CATEGORY,
	)
	def script_openSupportPage(self, gesture):
		_open_support_page()
