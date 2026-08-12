from __future__ import annotations

import importlib
import sys
import types
import unittest
from collections import deque
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GLOBAL_PLUGINS = PROJECT_ROOT / "src" / "globalPlugins"


class _Log:
	def debugWarning(self, *args, **kwargs):
		pass

	def error(self, *args, **kwargs):
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

		wx_lib = types.ModuleType("wx.lib")
		scrolledpanel = types.ModuleType("wx.lib.scrolledpanel")
		scrolledpanel.ScrolledPanel = type("ScrolledPanel", (), {})
		wx_lib.scrolledpanel = scrolledpanel
		wx.lib = wx_lib
		install("wx.lib", wx_lib)
		install("wx.lib.scrolledpanel", scrolledpanel)

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
		self.assertEqual("1.7.0", self.module.ADDON_VERSION)
		self.assertIn("Do not close or restart NVDA", self.module.CONVERSION_LIFECYCLE_WARNING)
		self.assertIn("Cancel button", self.module.CONVERSION_LIFECYCLE_WARNING)
		dialog = self.module.EasyAudioConverterSettingsDialog
		self.assertEqual("Easy Audio Converter settings", dialog.title)
		self.assertEqual(0, dialog.STANDARD_TAB)
		self.assertEqual(1, dialog.ADVANCED_TAB)
		self.assertEqual(2, dialog.PROCESSING_TAB)
		self.assertEqual(18, len(self.module.FORMAT_KEYS))
		self.assertEqual(
			"boolean(default=False)",
			self.module.CONFIG_SPEC["preserveTimestamps"],
		)
		self.assertEqual(
			"boolean(default=False)",
			self.module.CONFIG_SPEC["replaceSourceFiles"],
		)
		self.assertEqual(
			"string(default='queue')",
			self.module.CONFIG_SPEC["busyConversionMode"],
		)
		self.assertEqual(
			"string(default='{}')",
			self.module.CONFIG_SPEC["metadataOverrides"],
		)
		flac_choices = self.module._lossless_compression_choices("flac")
		self.assertEqual(tuple(range(-1, 13)), tuple(value for value, _label in flac_choices))
		self.assertIn("maximum compression", flac_choices[-1][1])
		wavpack_choices = self.module._lossless_compression_choices("wavpack")
		self.assertEqual(tuple(range(-1, 9)), tuple(value for value, _label in wavpack_choices))
		self.assertIn("-hhx4", dict(wavpack_choices)[7])
		self.assertIn("-hhx6", dict(wavpack_choices)[8])
		self.assertEqual(
			"Extract original audio stream (no re-encoding)",
			self.module._format_labels()[self.module.ORIGINAL_AUDIO_COPY_FORMAT],
		)
		self.assertEqual(
			"Remux AAC to M4A (no re-encoding)",
			self.module._format_labels()[self.module.AAC_M4A_COPY_FORMAT],
		)

	def test_all_script_actions_are_exposed(self):
		expected = {
			"script_openSettings",
			"script_openAdvancedSettings",
			"script_convertSelectionWithOptions",
			"script_convertSelection",
			"script_chooseFilesForConversion",
			"script_chooseFolderForConversion",
			"script_convertCurrentFolder",
			"script_cycleTargetFormat",
			"script_cycleQuality",
			"script_chooseDestinationFolder",
			"script_cancelConversion",
			"script_stopAfterCurrent",
			"script_reportQueue",
			"script_clearQueue",
			"script_showSelectedAudioInfo",
			"script_showProgress",
			"script_showResults",
			"script_reportStatus",
			"script_openSupportPage",
			"script_checkForUpdates",
		}
		self.assertTrue(expected.issubset(set(dir(self.module.GlobalPlugin))))

	def test_plugin_does_not_register_a_category_in_nvda_preferences(self):
		settings_dialogs = sys.modules["gui.settingsDialogs"]
		settings_dialogs.NVDASettingsDialog.categoryClasses.clear()
		original_ensure = self.module._ensure_config
		original_install_menu = self.module.GlobalPlugin._install_menu
		original_updates_allowed = self.module.GlobalPlugin._updates_allowed
		self.module._ensure_config = lambda: None
		self.module.GlobalPlugin._install_menu = lambda plugin: None
		self.module.GlobalPlugin._updates_allowed = staticmethod(lambda: False)
		try:
			plugin = self.module.GlobalPlugin()
		finally:
			self.module._ensure_config = original_ensure
			self.module.GlobalPlugin._install_menu = original_install_menu
			self.module.GlobalPlugin._updates_allowed = original_updates_allowed
		self.assertEqual([], settings_dialogs.NVDASettingsDialog.categoryClasses)
		self.assertIsNone(plugin._settings_dialog)

	def test_standalone_settings_dialog_has_balanced_popup_lifecycle(self):
		calls = []
		gui_module = sys.modules["gui"]
		original_dialog = self.module.EasyAudioConverterSettingsDialog
		original_main_frame = gui_module.mainFrame

		class Dialog:
			def __init__(self, parent, initial_tab):
				calls.append(("create", parent, initial_tab))

			def ShowModal(self):
				calls.append(("show",))
				return 0

			def Destroy(self):
				calls.append(("destroy",))

		main_frame = types.SimpleNamespace(
			prePopup=lambda: calls.append(("pre",)),
			postPopup=lambda: calls.append(("post",)),
		)
		gui_module.mainFrame = main_frame
		self.module.EasyAudioConverterSettingsDialog = Dialog
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._settings_dialog = None
		plugin._terminated = False
		try:
			plugin._open_settings_dialog(original_dialog.ADVANCED_TAB)
		finally:
			self.module.EasyAudioConverterSettingsDialog = original_dialog
			gui_module.mainFrame = original_main_frame
		self.assertEqual(
			[
				("pre",),
				("create", main_frame, original_dialog.ADVANCED_TAB),
				("show",),
				("destroy",),
				("post",),
			],
			calls,
		)
		self.assertIsNone(plugin._settings_dialog)

	def test_existing_settings_dialog_is_focused_instead_of_duplicated(self):
		calls = []
		dialog = types.SimpleNamespace(
			Raise=lambda: calls.append("raise"),
			SetFocus=lambda: calls.append("focus"),
		)
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._settings_dialog = dialog
		plugin._terminated = False
		plugin._open_settings_dialog()
		self.assertEqual(["raise", "focus"], calls)
		self.assertIs(dialog, plugin._settings_dialog)

	def test_tools_menu_defers_action_until_the_menu_has_closed(self):
		calls = []
		bindings = []
		deferred = []

		class Menu:
			def Append(self, item_id, label):
				item = (item_id, label)
				calls.append(("append", item))
				return item

			def AppendSeparator(self):
				calls.append(("separator",))

		class ToolsMenu:
			def AppendSubMenu(self, menu, label):
				calls.append(("submenu", menu, label))
				return object()

		tray = types.SimpleNamespace(
			toolsMenu=ToolsMenu(),
			Bind=lambda event, handler, item: bindings.append((event, handler, item)),
		)
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._menu = None
		plugin._menu_root_item = None
		plugin._menu_bindings = []
		plugin.script_convertSelectionWithOptions = lambda gesture: calls.append(
			("action", gesture)
		)

		gui_module = sys.modules["gui"]
		wx_module = sys.modules["wx"]
		original_main_frame = gui_module.mainFrame
		missing = object()
		replacements = {
			"Menu": Menu,
			"ID_ANY": -1,
			"EVT_MENU": object(),
			"CallAfter": lambda callback, *args: deferred.append((callback, args)),
		}
		originals = {
			name: getattr(wx_module, name, missing)
			for name in replacements
		}
		gui_module.mainFrame = types.SimpleNamespace(sysTrayIcon=tray)
		for name, value in replacements.items():
			setattr(wx_module, name, value)
		try:
			plugin._install_menu()
			bindings[0][1](None)
			self.assertFalse(any(call[0] == "action" for call in calls))
			self.assertEqual(1, len(deferred))
			callback, arguments = deferred.pop()
			callback(*arguments)
		finally:
			gui_module.mainFrame = original_main_frame
			for name, original in originals.items():
				if original is missing:
					delattr(wx_module, name)
				else:
					setattr(wx_module, name, original)
		self.assertIn(("action", None), calls)

	def test_tools_submenu_is_destroyed_exactly_once(self):
		calls = []
		item = object()
		handler = object()
		root_item = object()

		class Submenu:
			def Destroy(self):
				calls.append(("destroy submenu",))

		class ToolsMenu:
			def DestroyItem(self, source):
				calls.append(("destroy item", source))

		tray = types.SimpleNamespace(
			toolsMenu=ToolsMenu(),
			Unbind=lambda event, *, handler, source: calls.append(
				("unbind", event, handler, source)
			),
		)
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._menu = Submenu()
		plugin._menu_root_item = root_item
		plugin._menu_bindings = [(item, handler)]

		gui_module = sys.modules["gui"]
		wx_module = sys.modules["wx"]
		original_main_frame = gui_module.mainFrame
		missing = object()
		original_event = getattr(wx_module, "EVT_MENU", missing)
		event = object()
		gui_module.mainFrame = types.SimpleNamespace(sysTrayIcon=tray)
		wx_module.EVT_MENU = event
		try:
			plugin._remove_menu()
		finally:
			gui_module.mainFrame = original_main_frame
			if original_event is missing:
				del wx_module.EVT_MENU
			else:
				wx_module.EVT_MENU = original_event
		self.assertEqual(
			[
				("unbind", event, handler, item),
				("destroy item", root_item),
			],
			calls,
		)
		self.assertIsNone(plugin._menu)
		self.assertIsNone(plugin._menu_root_item)
		self.assertEqual([], plugin._menu_bindings)

	def test_explorer_candidates_include_focus_saved_before_nvda_menu(self):
		current_focus = types.SimpleNamespace(windowHandle=20)
		previous_focus = types.SimpleNamespace(windowHandle=30)
		previous_ancestor = types.SimpleNamespace(windowHandle=31)
		api_module = sys.modules["api"]
		gui_module = sys.modules["gui"]
		original_get_focus = api_module.getFocusObject
		original_main_frame = gui_module.mainFrame
		original_foreground = self.module._top_level_foreground_window
		original_root = self.module._top_level_window_handle
		api_module.getFocusObject = lambda: current_focus
		gui_module.mainFrame = types.SimpleNamespace(
			prevFocus=previous_focus,
			prevFocusAncestors=(previous_ancestor,),
		)
		self.module._top_level_foreground_window = lambda: 10
		self.module._top_level_window_handle = lambda handle: {
			20: 10,
			30: 300,
			31: 300,
		}.get(handle, handle)
		try:
			self.assertEqual(
				(10, 300),
				self.module._explorer_candidate_window_handles(),
			)
		finally:
			api_module.getFocusObject = original_get_focus
			gui_module.mainFrame = original_main_frame
			self.module._top_level_foreground_window = original_foreground
			self.module._top_level_window_handle = original_root

	def test_explorer_context_uses_the_window_saved_before_nvda_menu(self):
		selected_path = r"C:\Media\nagranie.wav"
		selected_items = types.SimpleNamespace(
			Count=1,
			Item=lambda index: types.SimpleNamespace(Path=selected_path),
		)
		document = types.SimpleNamespace(
			Folder=types.SimpleNamespace(Self=types.SimpleNamespace(Path=r"C:\Media")),
			SelectedItems=lambda: selected_items,
		)
		explorer_window = types.SimpleNamespace(HWND=300, Document=document)
		windows = types.SimpleNamespace(Count=1, Item=lambda index: explorer_window)
		shell = types.SimpleNamespace(Windows=lambda: windows)
		client = types.ModuleType("comtypes.client")
		client.CreateObject = lambda name, dynamic=True: shell
		comtypes = types.ModuleType("comtypes")
		comtypes.client = client

		original_comtypes = sys.modules.get("comtypes")
		original_client = sys.modules.get("comtypes.client")
		original_candidates = self.module._explorer_candidate_window_handles
		original_root = self.module._top_level_window_handle
		original_exists = self.module.os.path.exists
		sys.modules["comtypes"] = comtypes
		sys.modules["comtypes.client"] = client
		self.module._explorer_candidate_window_handles = lambda: (10, 300)
		self.module._top_level_window_handle = lambda handle: handle
		self.module.os.path.exists = lambda path: path == selected_path
		try:
			self.assertEqual(
				([selected_path], r"C:\Media"),
				self.module._explorer_context(),
			)
		finally:
			if original_comtypes is None:
				sys.modules.pop("comtypes", None)
			else:
				sys.modules["comtypes"] = original_comtypes
			if original_client is None:
				sys.modules.pop("comtypes.client", None)
			else:
				sys.modules["comtypes.client"] = original_client
			self.module._explorer_candidate_window_handles = original_candidates
			self.module._top_level_window_handle = original_root
			self.module.os.path.exists = original_exists

	def test_focused_path_uses_focus_saved_before_nvda_menu(self):
		api_module = sys.modules["api"]
		gui_module = sys.modules["gui"]
		original_get_focus = api_module.getFocusObject
		original_main_frame = gui_module.mainFrame
		original_exists = self.module.os.path.exists
		expected = self.module.os.path.join(r"C:\Media", "nagranie.wav")
		api_module.getFocusObject = lambda: types.SimpleNamespace(name="Nieznane")
		gui_module.mainFrame = types.SimpleNamespace(
			prevFocus=types.SimpleNamespace(name="nagranie.wav", value=""),
			prevFocusAncestors=(),
		)
		self.module.os.path.exists = lambda path: path == expected
		try:
			self.assertEqual(expected, self.module._focused_path(r"C:\Media"))
		finally:
			api_module.getFocusObject = original_get_focus
			gui_module.mainFrame = original_main_frame
			self.module.os.path.exists = original_exists

	def test_missing_explorer_selection_opens_async_file_picker(self):
		chosen = [r"C:\Media\jeden.wav", r"C:\Media\dwa.mp4"]
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._terminated = False
		calls = []

		def choose(callback, folder=""):
			calls.append(("picker", folder))
			callback(chosen)

		plugin._choose_files_for_conversion = choose
		plugin._quick_convert_paths = lambda paths, source_root=None: calls.append(
			("convert", paths, source_root)
		)
		original_context = self.module._explorer_context
		original_focused_path = self.module._focused_path
		self.module._explorer_context = lambda: ([], r"C:\Media")
		self.module._focused_path = lambda folder="": ""
		try:
			plugin.script_convertSelection(None)
		finally:
			self.module._explorer_context = original_context
			self.module._focused_path = original_focused_path
		self.assertEqual(
			[("picker", r"C:\Media"), ("convert", chosen, None)],
			calls,
		)

	def test_existing_selection_is_deferred_until_the_nvda_script_returns(self):
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		chosen = [r"C:\Media\jeden.wav"]
		calls = []
		deferred = []
		plugin._selection_for_conversion = lambda: (chosen, None, r"C:\Media")
		plugin._quick_convert_paths = lambda paths, source_root=None: calls.append(
			("convert", paths, source_root)
		)
		wx_module = sys.modules["wx"]
		original_call_after = getattr(wx_module, "CallAfter", None)
		wx_module.CallAfter = lambda callback, *args, **kwargs: deferred.append(
			(callback, args, kwargs)
		)
		try:
			plugin.script_convertSelection(None)
			self.assertEqual([], calls)
			callback, arguments, keywords = deferred.pop()
			callback(*arguments, **keywords)
		finally:
			if original_call_after is None:
				del wx_module.CallAfter
			else:
				wx_module.CallAfter = original_call_after
		self.assertEqual([("convert", chosen, None)], calls)

	def test_file_picker_accepts_multiple_existing_files_and_closes(self):
		calls = []
		deferred = []
		chosen = [
			r"C:\Media\jeden.wav",
			r"C:\Media\dwa.mp4",
			r"C:\Media\jeden.wav",
			r"C:\Media\brak.wav",
		]

		class Dialog:
			def __init__(self, parent, message, **kwargs):
				calls.append(("create", parent, message, kwargs))

			def ShowModal(self):
				calls.append(("show",))
				return 5100

			def GetPaths(self):
				return chosen

			def Destroy(self):
				calls.append(("destroy",))

		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._terminated = False
		wx_module = sys.modules["wx"]
		gui_module = sys.modules["gui"]
		missing = object()
		replacements = {
			"FileDialog": Dialog,
			"FD_OPEN": 1,
			"FD_FILE_MUST_EXIST": 2,
			"FD_MULTIPLE": 4,
			"CallAfter": lambda callback, *args: deferred.append((callback, args)),
		}
		originals = {
			name: getattr(wx_module, name, missing)
			for name in replacements
		}
		original_isdir = self.module.os.path.isdir
		original_isfile = self.module.os.path.isfile
		original_main_frame = gui_module.mainFrame
		main_frame = types.SimpleNamespace(
			prePopup=lambda: calls.append(("pre",)),
			postPopup=lambda: calls.append(("post",)),
		)
		for name, value in replacements.items():
			setattr(wx_module, name, value)
		gui_module.mainFrame = main_frame
		self.module.os.path.isdir = lambda path: path == r"C:\Media"
		self.module.os.path.isfile = lambda path: path != r"C:\Media\brak.wav"
		try:
			plugin._choose_files_for_conversion(
				lambda paths: calls.append(("selected", paths)),
				r"C:\Media",
			)
			self.assertEqual(["create", "pre"], [call[0] for call in calls])
			callback, arguments = deferred.pop(0)
			callback(*arguments)
			callback, arguments = deferred.pop()
			callback(*arguments)
		finally:
			for name, original in originals.items():
				if original is missing:
					delattr(wx_module, name)
				else:
					setattr(wx_module, name, original)
			self.module.os.path.isdir = original_isdir
			self.module.os.path.isfile = original_isfile
			gui_module.mainFrame = original_main_frame
		self.assertEqual("create", calls[0][0])
		self.assertIs(main_frame, calls[0][1])
		self.assertEqual(r"C:\Media", calls[0][3]["defaultDir"])
		self.assertEqual(7, calls[0][3]["style"])
		self.assertEqual(("pre",), calls[1])
		self.assertEqual(("show",), calls[2])
		self.assertEqual(("destroy",), calls[3])
		self.assertEqual(("post",), calls[4])
		self.assertEqual(("selected", chosen[:2]), calls[5])

	def test_folder_picker_cancel_is_async_and_restores_popup_state(self):
		calls = []
		deferred = []

		class Dialog:
			def __init__(self, parent, message, **kwargs):
				calls.append(("create", parent, message, kwargs))

			def ShowModal(self):
				calls.append(("show",))
				return 5101

			def GetPath(self):
				raise AssertionError("Anulowany dialog nie może zwrócić folderu")

			def Destroy(self):
				calls.append(("destroy",))

		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._terminated = False
		wx_module = sys.modules["wx"]
		gui_module = sys.modules["gui"]
		missing = object()
		replacements = {
			"DirDialog": Dialog,
			"DD_DEFAULT_STYLE": 1,
			"DD_DIR_MUST_EXIST": 2,
			"ID_CANCEL": 5101,
			"CallAfter": lambda callback, *args: deferred.append((callback, args)),
		}
		originals = {
			name: getattr(wx_module, name, missing)
			for name in replacements
		}
		original_isdir = self.module.os.path.isdir
		original_main_frame = gui_module.mainFrame
		main_frame = types.SimpleNamespace(
			prePopup=lambda: calls.append(("pre",)),
			postPopup=lambda: calls.append(("post",)),
		)
		for name, value in replacements.items():
			setattr(wx_module, name, value)
		gui_module.mainFrame = main_frame
		self.module.os.path.isdir = lambda path: path == r"C:\Media"
		try:
			plugin._choose_folder_for_conversion(
				lambda folder: calls.append(("selected", folder)),
				r"C:\Media",
			)
			self.assertEqual(["create", "pre"], [call[0] for call in calls])
			callback, arguments = deferred.pop(0)
			callback(*arguments)
			callback, arguments = deferred.pop()
			callback(*arguments)
		finally:
			for name, original in originals.items():
				if original is missing:
					delattr(wx_module, name)
				else:
					setattr(wx_module, name, original)
			self.module.os.path.isdir = original_isdir
			gui_module.mainFrame = original_main_frame
		self.assertEqual("create", calls[0][0])
		self.assertIs(main_frame, calls[0][1])
		self.assertEqual("Choose a folder to convert", calls[0][2])
		self.assertEqual(r"C:\Media", calls[0][3]["defaultPath"])
		self.assertEqual(3, calls[0][3]["style"])
		self.assertEqual(
			[("pre",), ("show",), ("destroy",), ("post",), ("selected", "")],
			calls[1:],
		)

	def test_settings_commands_target_the_requested_standalone_tabs(self):
		calls = []
		wx_module = sys.modules["wx"]
		original_call_after = getattr(wx_module, "CallAfter", None)
		wx_module.CallAfter = lambda callback, *args: callback(*args)
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._open_settings_dialog = lambda tab: calls.append(tab)
		try:
			plugin.script_openSettings(None)
			plugin.script_openAdvancedSettings(None)
		finally:
			if original_call_after is None:
				del wx_module.CallAfter
			else:
				wx_module.CallAfter = original_call_after
		self.assertEqual(
			[
				self.module.EasyAudioConverterSettingsDialog.STANDARD_TAB,
				self.module.EasyAudioConverterSettingsDialog.ADVANCED_TAB,
			],
			calls,
		)

	def test_settings_ok_validates_then_saves_all_tabs(self):
		calls = []

		class Page:
			def __init__(self, name, valid=True):
				self.name = name
				self.valid = valid

			def isValid(self):
				calls.append(("validate", self.name))
				return self.valid

			def onSave(self):
				calls.append(("save", self.name))

		dialog = self.module.EasyAudioConverterSettingsDialog.__new__(
			self.module.EasyAudioConverterSettingsDialog
		)
		dialog.standard_page = Page("standard")
		dialog.advanced_page = Page("advanced")
		dialog.processing_page = Page("processing")
		dialog.EndModal = lambda result: calls.append(("close", result))
		conf = sys.modules["config"].conf
		original_save = getattr(conf, "save", None)
		conf.save = lambda: calls.append(("save", "configuration"))
		try:
			dialog._on_ok(None)
		finally:
			if original_save is None:
				del conf.save
			else:
				conf.save = original_save
		self.assertEqual(
			[
				("validate", "standard"),
				("save", "standard"),
				("save", "advanced"),
				("save", "processing"),
				("save", "configuration"),
				("close", sys.modules["wx"].ID_OK),
			],
			calls,
		)

	def test_invalid_settings_stay_open_on_the_standard_tab(self):
		calls = []
		wx_module = sys.modules["wx"]
		original_call_after = getattr(wx_module, "CallAfter", None)
		wx_module.CallAfter = lambda callback, *args: callback(*args)
		dialog = self.module.EasyAudioConverterSettingsDialog.__new__(
			self.module.EasyAudioConverterSettingsDialog
		)
		dialog.standard_page = types.SimpleNamespace(
			isValid=lambda: False,
			output_name_template=types.SimpleNamespace(
				SetFocus=lambda: calls.append("focus")
			),
			onSave=lambda: calls.append("save standard"),
		)
		dialog.advanced_page = types.SimpleNamespace(
			onSave=lambda: calls.append("save advanced")
		)
		dialog.processing_page = types.SimpleNamespace(
			onSave=lambda: calls.append("save processing")
		)
		dialog.notebook = types.SimpleNamespace(
			SetSelection=lambda tab: calls.append(("tab", tab))
		)
		dialog.EndModal = lambda result: calls.append(("close", result))
		try:
			dialog._on_ok(None)
		finally:
			if original_call_after is None:
				del wx_module.CallAfter
			else:
				wx_module.CallAfter = original_call_after
		self.assertEqual(
			[
				("tab", self.module.EasyAudioConverterSettingsDialog.STANDARD_TAB),
				"focus",
			],
			calls,
		)

	def test_notebook_accessibility_reports_the_real_tab_count(self):
		notebook = types.SimpleNamespace(GetPageCount=lambda: 2)
		accessible = self.module._SettingsNotebookAccessible(notebook)
		self.assertEqual((0, 2), accessible.GetChildCount())

	def test_decimal_spin_control_has_an_explicit_accessible_name(self):
		class Sizer:
			def __init__(self, orientation):
				self.orientation = orientation
				self.items = []

			def Add(self, item, proportion, flags=0, border=0):
				self.items.append((item, proportion, flags, border))

		class StaticText:
			def __init__(self, parent, label):
				self.parent = parent
				self.label = label

		class SpinCtrlDouble:
			def __init__(self, parent, **kwargs):
				self.parent = parent
				self.kwargs = kwargs
				self.digits = None
				self.name = ""

			def SetDigits(self, digits):
				self.digits = digits

			def SetName(self, name):
				self.name = name

		wx_module = sys.modules["wx"]
		missing = object()
		replacements = {
			"BoxSizer": Sizer,
			"StaticText": StaticText,
			"SpinCtrlDouble": SpinCtrlDouble,
			"HORIZONTAL": 1,
			"ALIGN_CENTER_VERTICAL": 2,
			"RIGHT": 4,
		}
		originals = {
			name: getattr(wx_module, name, missing)
			for name in replacements
		}
		for name, value in replacements.items():
			setattr(wx_module, name, value)
		added = []
		helper = types.SimpleNamespace(addItem=added.append)
		try:
			control = self.module._add_labeled_spin_double(
				helper,
				object(),
				"&Custom loudness:",
				minimum=-70.0,
				maximum=-5.0,
				initial=-16.0,
				increment=0.5,
			)
		finally:
			for name, original in originals.items():
				if original is missing:
					delattr(wx_module, name)
				else:
					setattr(wx_module, name, original)
		self.assertEqual("Custom loudness", control.name)
		self.assertEqual(1, control.digits)
		self.assertEqual(1, len(added))
		self.assertEqual(-16.0, control.kwargs["initial"])

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
		self.assertTrue(self.module.ERROR_SOUND_PATH.is_file())
		self.assertTrue(self.module.CANCEL_SOUND_PATH.is_file())

	def test_busy_conversion_is_queued_with_an_immutable_snapshot(self):
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._converter = object()
		plugin._job_queue = deque()
		plugin._progress_dialog = None
		settings = self.module.ConversionSettings(
			target_format="opus",
			advanced_options={"enabled": True, "bitrate": 96},
		)
		plugin._start_conversion([r"D:\input.wav"], settings=settings)
		self.assertEqual(1, len(plugin._job_queue))
		job = plugin._job_queue[0]
		self.assertEqual((r"D:\input.wav",), job.paths)
		self.assertEqual("opus", job.settings.target_format)
		self.assertIsNot(job.settings.advanced_options, settings.advanced_options)

	def test_busy_conversion_can_be_routed_to_a_separate_controller(self):
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._converter = object()
		plugin._parallel_plugins = {}
		plugin._job_queue = deque()
		launched = []
		plugin._launch_parallel_conversion_job = launched.append
		original_mode = self.module._read_busy_conversion_mode
		self.module._read_busy_conversion_mode = lambda: "parallel"
		try:
			plugin._start_conversion(
				[r"D:\input.wav"],
				settings=self.module.ConversionSettings(),
			)
		finally:
			self.module._read_busy_conversion_mode = original_mode
		self.assertEqual(1, len(launched))
		self.assertEqual(0, len(plugin._job_queue))
		self.assertEqual((r"D:\input.wav",), launched[0].paths)

	def test_busy_state_includes_active_separate_controllers(self):
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._converter = None
		plugin._parallel_plugins = {
			1: types.SimpleNamespace(_converter=object()),
			2: types.SimpleNamespace(_converter=None),
		}
		self.assertTrue(plugin._is_busy())
		self.assertEqual(1, len(plugin._conversion_controllers()))

	def test_separate_controller_gets_its_own_window_title_and_is_retained(self):
		class Dialog:
			def __init__(self):
				self.title = ""

			def SetTitle(self, title):
				self.title = title

		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._parallel_plugins = {}
		plugin._next_parallel_plugin_id = 1
		dialog = Dialog()
		parallel_plugin = types.SimpleNamespace(
			_parallel_task_id=0,
			_converter=object(),
			_worker=object(),
			_progress_dialog=dialog,
			_launch_conversion_job=lambda job: None,
		)
		plugin._create_parallel_plugin = lambda: parallel_plugin
		messages = []
		original_message = self.module.ui.message
		self.module.ui.message = messages.append
		try:
			plugin._launch_parallel_conversion_job(
				self.module._ConversionJob(("input.wav",), self.module.ConversionSettings())
			)
		finally:
			self.module.ui.message = original_message
		self.assertIs(parallel_plugin, plugin._parallel_plugins[1])
		self.assertIn("separate job 1", dialog.title)
		self.assertEqual(
			["Started a separate conversion window for the new job."],
			messages,
		)

	def test_cancel_and_stop_apply_to_all_active_controllers(self):
		calls = []

		class ConverterControl:
			def cancel(self):
				calls.append("cancel")

			def stop_after_current(self):
				calls.append("stop")

		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._converter = ConverterControl()
		plugin._parallel_plugins = {
			1: types.SimpleNamespace(_converter=ConverterControl()),
		}
		messages = []
		original_message = self.module.ui.message
		self.module.ui.message = messages.append
		try:
			plugin.script_cancelConversion(None)
			plugin.script_stopAfterCurrent(None)
		finally:
			self.module.ui.message = original_message
		self.assertEqual(["cancel", "cancel", "stop", "stop"], calls)
		self.assertIn("Canceling 2 active conversions", messages)
		self.assertIn(
			"The 2 active conversions will stop after their current files",
			messages,
		)

	def test_last_parallel_completion_releases_the_main_queue(self):
		parent = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		parent._converter = None
		parent._job_queue = deque([object()])
		parent._parallel_plugins = {}
		parent._last_results_controller = None
		started = []
		parent._launch_next_queued_job = lambda: started.append(True)
		child = types.SimpleNamespace(
			_parallel_parent=parent,
			_last_summary=self.module.ConversionSummary(total=1, succeeded=1),
			_converter=None,
		)
		parent._parallel_job_finished(child)
		self.assertIs(child, parent._last_results_controller)
		self.assertEqual([True], started)

	def test_source_replacement_warning_defaults_to_no_and_blocks_the_job(self):
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._converter = None
		plugin._job_queue = deque()
		plugin._progress_dialog = None
		launched = []
		plugin._launch_conversion_job = launched.append

		gui_module = sys.modules["gui"]
		wx_module = sys.modules["wx"]
		missing = object()
		original_message_box = getattr(gui_module, "messageBox", missing)
		constant_names = ("YES", "NO", "YES_NO", "NO_DEFAULT", "ICON_WARNING")
		original_constants = {
			name: getattr(wx_module, name, missing)
			for name in constant_names
		}
		wx_module.YES = 1
		wx_module.NO = 0
		wx_module.YES_NO = 2
		wx_module.NO_DEFAULT = 4
		wx_module.ICON_WARNING = 8
		decision = {"value": wx_module.NO}
		calls = []

		def message_box(*args):
			calls.append(args)
			return decision["value"]

		gui_module.messageBox = message_box
		try:
			settings = self.module.ConversionSettings(replace_source_files=True)
			plugin._start_conversion([r"D:\input.wav"], settings=settings)
			self.assertEqual([], launched)
			self.assertEqual(1, len(calls))
			self.assertIn("cannot be undone", calls[0][0])
			self.assertTrue(calls[0][2] & wx_module.NO_DEFAULT)

			decision["value"] = wx_module.YES
			plugin._start_conversion([r"D:\input.wav"], settings=settings)
			self.assertEqual(1, len(launched))
		finally:
			if original_message_box is missing:
				del gui_module.messageBox
			else:
				gui_module.messageBox = original_message_box
			for name, original in original_constants.items():
				if original is missing:
					delattr(wx_module, name)
				else:
					setattr(wx_module, name, original)

	def test_next_queued_job_starts_after_current_job_releases(self):
		started = []
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._terminated = False
		plugin._converter = None
		job = self.module._ConversionJob(
			("input.wav",),
			self.module.ConversionSettings(),
		)
		plugin._job_queue = deque([job])
		plugin._launch_conversion_job = started.append
		plugin._launch_next_queued_job()
		self.assertEqual([job], started)
		self.assertEqual(0, len(plugin._job_queue))

	def test_missing_ffmpeg_clears_jobs_that_cannot_run(self):
		job = self.module._ConversionJob(
			("input.wav",),
			self.module.ConversionSettings(),
		)
		queue_counts = []
		messages = []
		plugin = self.module.GlobalPlugin.__new__(self.module.GlobalPlugin)
		plugin._job_queue = deque([job, job])
		plugin._progress_dialog = types.SimpleNamespace(
			set_queue_count=queue_counts.append,
		)
		plugin._ffmpeg_path = lambda: Path(r"Z:\missing-easy-audio-converter-ffmpeg.exe")
		gui_module = sys.modules["gui"]
		wx_module = sys.modules["wx"]
		original_message_box = getattr(gui_module, "messageBox", None)
		original_ui_message = self.module.ui.message
		original_ok = getattr(wx_module, "OK", None)
		original_icon_error = getattr(wx_module, "ICON_ERROR", None)
		gui_module.messageBox = lambda *args, **kwargs: None
		self.module.ui.message = messages.append
		wx_module.OK = 1
		wx_module.ICON_ERROR = 2
		try:
			plugin._launch_conversion_job(job)
		finally:
			if original_message_box is None:
				del gui_module.messageBox
			else:
				gui_module.messageBox = original_message_box
			self.module.ui.message = original_ui_message
			if original_ok is None:
				del wx_module.OK
			else:
				wx_module.OK = original_ok
			if original_icon_error is None:
				del wx_module.ICON_ERROR
			else:
				wx_module.ICON_ERROR = original_icon_error
		self.assertEqual(0, len(plugin._job_queue))
		self.assertEqual([0], queue_counts)
		self.assertEqual(["Cleared 2 queued conversion jobs"], messages)

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

	def test_plan_and_results_reports_explain_source_replacement(self):
		plan = self.module.ConversionPlan(
			items=(),
			ignored=0,
			skipped_files=(),
			input_bytes=0,
			estimated_output_bytes=0,
			total_duration=0.0,
			destination=r"D:\out",
			free_space_bytes=None,
			lossy_to_lossy_count=0,
			replace_source_files=True,
		)
		self.assertIn(
			"source files will be permanently deleted",
			self.module._build_plan_report(plan).casefold(),
		)

		kept_output = r"D:\out\song.mp3"
		summary = self.module.ConversionSummary(
			total=1,
			failed=1,
			failures=[
				self.module.converter.ConversionFailure(
					"song.wav",
					"Could not remove source file after successful conversion: Access is denied",
					r"D:\in\song.wav",
					kept_output,
				)
			],
		)
		report = self.module._build_results_report(summary)
		self.assertIn("converted output was kept", report)
		self.assertIn(kept_output, report)

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
