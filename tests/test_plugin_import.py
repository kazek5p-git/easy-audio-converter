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
		for name in ("easyAudioConverter.converter", "easyAudioConverter"):
			sys.modules.pop(name, None)
		for name, original in cls._original_modules.items():
			if original is None:
				sys.modules.pop(name, None)
			else:
				sys.modules[name] = original

	def test_module_imports_with_the_documented_nvda_api_surface(self):
		self.assertEqual("Easy Audio Converter", self.module.ADDON_NAME)
		self.assertEqual("Easy Audio Converter", self.module.EasyAudioConverterSettingsPanel.title)
		self.assertEqual(0, self.module.EasyAudioConverterSettingsPanel.STANDARD_TAB)
		self.assertEqual(1, self.module.EasyAudioConverterSettingsPanel.ADVANCED_TAB)
		self.assertEqual(16, len(self.module.FORMAT_KEYS))

	def test_all_script_actions_are_exposed(self):
		expected = {
			"script_openSettings",
			"script_openAdvancedSettings",
			"script_convertSelection",
			"script_convertCurrentFolder",
			"script_cycleTargetFormat",
			"script_cycleQuality",
			"script_chooseDestinationFolder",
			"script_cancelConversion",
			"script_showProgress",
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


if __name__ == "__main__":
	unittest.main()
