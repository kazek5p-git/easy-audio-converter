# Copyright (C) 2026 Kazimierz Parzych
# SPDX-License-Identifier: GPL-3.0-or-later
"""Integracja Easy Audio Converter z cyklem życia NVDA i skryptami użytkownika."""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

import config
import globalPluginHandler
import gui
import ui
import wx
from logHandler import log
from scriptHandler import script

try:
	import globalVars
except Exception:
	globalVars = None

from . import (
	_,
	ADDON_VERSION,
	CANCEL_SOUND_PATH,
	CONFIG_SECTION,
	CONVERSION_LIFECYCLE_WARNING,
	ERROR_SOUND_PATH,
	FORMAT_KEYS,
	GITHUB_REPOSITORY_URL,
	QUALITY_KEYS,
	STREAM_COPY_FORMATS,
	ConversionCallbacks,
	ConversionPlan,
	ConversionSettings,
	ConversionSummary,
	Converter,
	MediaInfo,
	ReleaseInfo,
	UpdateCanceled,
	_ensure_config as _core_ensure_config,
	_explorer_context as _core_explorer_context,
	_focused_path as _core_focused_path,
	_format_labels,
	_open_support_page,
	_read_busy_conversion_mode as _core_read_busy_conversion_mode,
	_read_notification_preferences,
	_read_settings,
	_quality_labels,
	_validated_key,
	download_release,
	fetch_latest_release,
	is_newer_version,
	resolve_parallel_jobs,
)
from .conversion_dialogs import (
	AudioInfoDialog,
	ConversionPlanDialog,
	ConversionProgressDialog,
	ConversionResultsDialog,
	_conversion_completed_successfully,
	_estimate_remaining,
	_event_sound_enabled,
	_format_elapsed,
	_play_completion_sound as _default_play_completion_sound,
	_play_event_sound as _default_play_event_sound,
	_stage_status_label,
)
from .settings_dialogs import (
	ConversionOptionsDialog,
	EasyAudioConverterSettingsDialog,
	_run_conversion_options_dialog,
)


def _package_module():
	"""Zwróć pakiet główny dla zachowania zgodności publicznych eksportów."""
	return sys.modules.get(__package__)


def _ensure_config() -> None:
	"""Wywołaj konfigurację z warstwy pakietu zgodnie z publicznym API."""
	package = _package_module()
	(getattr(package, "_ensure_config", _core_ensure_config))()


def _explorer_context():
	package = _package_module()
	return getattr(package, "_explorer_context", _core_explorer_context)()


def _focused_path(current_folder: str = ""):
	package = _package_module()
	return getattr(package, "_focused_path", _core_focused_path)(current_folder)


def _read_busy_conversion_mode() -> str:
	package = _package_module()
	return getattr(package, "_read_busy_conversion_mode", _core_read_busy_conversion_mode)()


def _play_completion_sound() -> None:
	package = _package_module()
	(getattr(package, "_play_completion_sound", _default_play_completion_sound))()


def _play_event_sound(path: Path, event_name: str) -> None:
	package = _package_module()
	(getattr(package, "_play_event_sound", _default_play_event_sound))(path, event_name)

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
			package = _package_module()
			dialog_class = getattr(
				package,
				"EasyAudioConverterSettingsDialog",
				EasyAudioConverterSettingsDialog,
			)
			dialog = dialog_class(
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
