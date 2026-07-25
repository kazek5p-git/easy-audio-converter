from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GLOBAL_PLUGINS = PROJECT_ROOT / "src" / "globalPlugins"


class _Log:
	def debugWarning(self, *args, **kwargs):
		pass


class _Config:
	def __init__(self):
		self.spec = {}


class PluginImportTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls._original_modules = {}

		def install(name: str, module: types.ModuleType) -> None:
			cls._original_modules[name] = sys.modules.get(name)
			sys.modules[name] = module

		addon_handler = types.ModuleType("addonHandler")
		addon_handler.initTranslation = lambda: None
		install("addonHandler", addon_handler)

		api = types.ModuleType("api")
		api.getFocusObject = lambda: None
		install("api", api)

		config = types.ModuleType("config")
		config.conf = _Config()
		install("config", config)

		global_plugin_handler = types.ModuleType("globalPluginHandler")
		global_plugin_handler.GlobalPlugin = type(
			"GlobalPlugin",
			(),
			{"__init__": lambda self, *args, **kwargs: None, "terminate": lambda self: None},
		)
		install("globalPluginHandler", global_plugin_handler)

		settings_dialogs = types.ModuleType("gui.settingsDialogs")
		settings_dialogs.SettingsPanel = type("SettingsPanel", (), {})
		settings_dialogs.NVDASettingsDialog = type("NVDASettingsDialog", (), {"categoryClasses": []})
		install("gui.settingsDialogs", settings_dialogs)

		gui = types.ModuleType("gui")
		gui.guiHelper = types.SimpleNamespace(BoxSizerHelper=object)
		gui.settingsDialogs = settings_dialogs
		gui.mainFrame = types.SimpleNamespace()
		install("gui", gui)

		nvwave = types.ModuleType("nvwave")
		nvwave.playWaveFile = lambda *args, **kwargs: None
		install("nvwave", nvwave)

		ui = types.ModuleType("ui")
		ui.message = lambda message: None
		install("ui", ui)

		wx = types.ModuleType("wx")
		wx.Dialog = type("Dialog", (), {})
		wx.Accessible = type(
			"Accessible",
			(),
			{"__init__": lambda self, window=None: setattr(self, "Window", window)},
		)
		wx.ACC_OK = 0
		wx.ID_OK = 5100
		install("wx", wx)

		log_handler = types.ModuleType("logHandler")
		log_handler.log = _Log()
		install("logHandler", log_handler)

		script_handler = types.ModuleType("scriptHandler")

		def script(**metadata):
			return lambda function: function

		script_handler.script = script
		install("scriptHandler", script_handler)

		sys.path.insert(0, str(GLOBAL_PLUGINS))
		cls.module = importlib.import_module("easyAudioConverter")

	@classmethod
	def tearDownClass(cls):
		sys.path.remove(str(GLOBAL_PLUGINS))
		for name in (
			"easyAudioConverter.profiles",
			"easyAudioConverter.converter",
			"easyAudioConverter",
		):
			sys.modules.pop(name, None)
		for name, original in cls._original_modules.items():
			if original is None:
				sys.modules.pop(name, None)
			else:
				sys.modules[name] = original

	def test_module_imports_with_the_documented_nvda_api_surface(self):
		self.assertEqual("Easy Audio Converter", self.module.ADDON_NAME)
		self.assertEqual("1.2.0", self.module.ADDON_VERSION)
		self.assertEqual("Easy Audio Converter", self.module.EasyAudioConverterSettingsPanel.title)
		self.assertEqual(0, self.module.EasyAudioConverterSettingsPanel.STANDARD_TAB)
		self.assertEqual(1, self.module.EasyAudioConverterSettingsPanel.ADVANCED_TAB)
		self.assertEqual(16, len(self.module.FORMAT_KEYS))

	def test_all_script_actions_are_exposed(self):
		expected = {
			"script_openSettings",
			"script_openAdvancedSettings",
			"script_convertSelectionWithOptions",
			"script_convertSelection",
			"script_convertCurrentFolder",
			"script_cycleTargetFormat",
			"script_cycleQuality",
			"script_chooseDestinationFolder",
			"script_cancelConversion",
			"script_showProgress",
			"script_showResults",
			"script_reportStatus",
			"script_openSupportPage",
			"script_checkForUpdates",
		}
		self.assertTrue(expected.issubset(set(dir(self.module.GlobalPlugin))))

	def test_stale_hidden_nvda_settings_dialog_is_destroyed(self):
		class Dialog(self.module.NVDASettingsDialog):
			def __init__(self, shown):
				self.shown = shown
				self.destroyed = False

			def IsShown(self):
				return self.shown

			def Destroy(self):
				self.destroyed = True

		visible = Dialog(True)
		hidden = Dialog(False)
		wx_module = sys.modules["wx"]
		original = getattr(wx_module, "GetTopLevelWindows", None)
		wx_module.GetTopLevelWindows = lambda: (visible, hidden)
		try:
			self.assertEqual(1, self.module._destroy_hidden_nvda_settings_dialogs())
		finally:
			if original is None:
				del wx_module.GetTopLevelWindows
			else:
				wx_module.GetTopLevelWindows = original
		self.assertFalse(visible.destroyed)
		self.assertTrue(hidden.destroyed)

	def test_settings_recovery_retains_delayed_open_until_it_runs(self):
		class Timer:
			def Stop(self):
				pass

		timer = Timer()
		callbacks = []
		popup_calls = []
		wx_module = sys.modules["wx"]
		gui_module = sys.modules["gui"]
		original_destroy = self.module._destroy_hidden_nvda_settings_dialogs
		original_call_later = getattr(wx_module, "CallLater", None)
		original_popup = getattr(gui_module.mainFrame, "popupSettingsDialog", None)
		self.module._destroy_hidden_nvda_settings_dialogs = lambda: 1
		wx_module.CallLater = lambda _delay, callback: callbacks.append(callback) or timer
		gui_module.mainFrame.popupSettingsDialog = lambda *args: popup_calls.append(args)
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._settings_open_timer = None
		plugin._terminated = False
		try:
			plugin._open_settings_panel(self.module.EasyAudioConverterSettingsPanel)
			self.assertIs(timer, plugin._settings_open_timer)
			self.assertEqual(1, len(callbacks))
			callbacks[0]()
			self.assertIsNone(plugin._settings_open_timer)
			self.assertEqual(
				[
					(
						self.module.NVDASettingsDialog,
						self.module.EasyAudioConverterSettingsPanel,
					)
				],
				popup_calls,
			)
		finally:
			self.module._destroy_hidden_nvda_settings_dialogs = original_destroy
			if original_call_later is None:
				del wx_module.CallLater
			else:
				wx_module.CallLater = original_call_later
			if original_popup is None:
				del gui_module.mainFrame.popupSettingsDialog
			else:
				gui_module.mainFrame.popupSettingsDialog = original_popup

	def test_advanced_settings_command_targets_the_unified_panel(self):
		calls = []
		wx_module = sys.modules["wx"]
		original_call_after = getattr(wx_module, "CallAfter", None)
		wx_module.CallAfter = lambda callback, *args: callback(*args)
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._open_settings_panel = lambda panel, tab: calls.append((panel, tab))
		try:
			plugin.script_openAdvancedSettings(None)
		finally:
			if original_call_after is None:
				del wx_module.CallAfter
			else:
				wx_module.CallAfter = original_call_after
		self.assertEqual(
			[
				(
					self.module.EasyAudioConverterSettingsPanel,
					self.module.EasyAudioConverterSettingsPanel.ADVANCED_TAB,
				)
			],
			calls,
		)

	def test_advanced_tab_request_is_one_shot(self):
		panel = self.module.EasyAudioConverterSettingsPanel
		panel.requestInitialTab(panel.ADVANCED_TAB)
		self.assertEqual(panel.ADVANCED_TAB, panel._takeInitialTab())
		self.assertEqual(panel.STANDARD_TAB, panel._takeInitialTab())

	def test_notebook_accessibility_reports_the_real_tab_count(self):
		notebook = types.SimpleNamespace(GetPageCount=lambda: 2)
		accessible = self.module._SettingsNotebookAccessible(notebook)
		self.assertEqual((0, 2), accessible.GetChildCount())

	def test_completion_sound_uses_the_bundled_wave_file(self):
		calls = []
		original = self.module.nvwave.playWaveFile
		self.module.nvwave.playWaveFile = (
			lambda path, asynchronous=True: calls.append((path, asynchronous))
		)
		try:
			self.module._play_completion_sound()
		finally:
			self.module.nvwave.playWaveFile = original
		self.assertEqual(
			[(str(self.module.COMPLETION_SOUND_PATH), True)],
			calls,
		)
		self.assertTrue(self.module.COMPLETION_SOUND_PATH.is_file())

	def test_job_completion_sound_requires_every_file_to_succeed(self):
		summaries = (
			(self.module.ConversionSummary(total=2, succeeded=2), True),
			(self.module.ConversionSummary(total=2, succeeded=1, failed=1), False),
			(self.module.ConversionSummary(total=2, succeeded=1), False),
			(self.module.ConversionSummary(total=2, succeeded=2, canceled=True), False),
			(self.module.ConversionSummary(total=0, succeeded=0), False),
		)
		for summary, expected in summaries:
			with self.subTest(summary=summary):
				self.assertEqual(
					expected,
					self.module._conversion_completed_successfully(summary),
				)

	def test_successful_job_completion_triggers_the_sound(self):
		sound_calls = []
		original = self.module._play_completion_sound
		self.module._play_completion_sound = lambda: sound_calls.append(True)
		try:
			converter = object()
			plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
			plugin._converter = converter
			plugin._terminated = False
			plugin._progress_dialog = None
			plugin._worker = object()
			plugin._progress = object()
			plugin._job_complete(
				converter,
				self.module.ConversionSummary(total=1, succeeded=1),
			)
		finally:
			self.module._play_completion_sound = original
		self.assertEqual([True], sound_calls)

	def test_remaining_time_estimate_is_bounded(self):
		self.assertIsNone(self.module._estimate_remaining(1, 0.5))
		self.assertIsNone(self.module._estimate_remaining(20, 0.001))
		self.assertEqual(30.0, self.module._estimate_remaining(10, 0.25))
		self.assertEqual(0.0, self.module._estimate_remaining(10, 1.0))

	def test_options_dialog_balances_nvda_popup_state(self):
		calls = []

		class Dialog:
			def ShowModal(self):
				calls.append("show")
				return self.module.wx.ID_OK

			def get_settings(self):
				calls.append("settings")
				return "snapshot"

			def Destroy(self):
				calls.append("destroy")

		dialog = Dialog()
		dialog.module = self.module
		gui_module = sys.modules["gui"]
		original_pre = getattr(gui_module.mainFrame, "prePopup", None)
		original_post = getattr(gui_module.mainFrame, "postPopup", None)
		gui_module.mainFrame.prePopup = lambda: calls.append("pre")
		gui_module.mainFrame.postPopup = lambda: calls.append("post")
		try:
			self.assertEqual(
				"snapshot",
				self.module._run_conversion_options_dialog(dialog),
			)
		finally:
			if original_pre is None:
				del gui_module.mainFrame.prePopup
			else:
				gui_module.mainFrame.prePopup = original_pre
			if original_post is None:
				del gui_module.mainFrame.postPopup
			else:
				gui_module.mainFrame.postPopup = original_post
		self.assertEqual(
			["pre", "show", "post", "settings", "destroy"],
			calls,
		)

	def test_results_report_retains_paths_and_friendly_errors(self):
		summary = self.module.ConversionSummary(
			total=2,
			succeeded=1,
			failed=1,
			ignored=1,
			outputs=[r"D:\out\song.mp3"],
			successes=[
				self.module.converter.ConversionSuccess(
					r"D:\in\song.wav",
					r"D:\out\song.mp3",
				)
			],
			failures=[
				self.module.converter.ConversionFailure(
					"broken.wav",
					"Permission denied",
					r"D:\in\broken.wav",
				)
			],
			skipped_files=[
				self.module.converter.SkippedFile(
					r"D:\in\already.mp3",
					"targetFormat",
				)
			],
		)
		report = self.module._build_results_report(summary)
		self.assertIn(r"D:\in\song.wav -> D:\out\song.mp3", report)
		self.assertIn(r"D:\in\broken.wav", report)
		self.assertIn("Access to the source or destination was denied.", report)
		self.assertIn(r"D:\in\already.mp3", report)

	def test_sound_only_completion_does_not_speak(self):
		sound_calls = []
		spoken = []
		original_sound = self.module._play_completion_sound
		original_message = self.module.ui.message
		self.module._play_completion_sound = lambda: sound_calls.append(True)
		self.module.ui.message = spoken.append
		try:
			converter = object()
			plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
			plugin._converter = converter
			plugin._terminated = False
			plugin._progress_dialog = None
			plugin._worker = object()
			plugin._progress = object()
			plugin._job_settings = None
			plugin._job_source_root = None
			plugin._job_completion_mode = "soundOnly"
			plugin._job_complete(
				converter,
				self.module.ConversionSummary(total=1, succeeded=1),
			)
		finally:
			self.module._play_completion_sound = original_sound
			self.module.ui.message = original_message
		self.assertEqual([True], sound_calls)
		self.assertEqual([], spoken)


if __name__ == "__main__":
	unittest.main()
