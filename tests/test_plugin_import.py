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


if __name__ == "__main__":
	unittest.main()
