# Copyright (C) 2026 Kazimierz Parzych
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pomiar niewidocznych okien wx; nie zastępuje testu wewnątrz NVDA.

Wymaga wxPython oraz katalogu źródeł NVDA podanego przez --nvda-source.
Używa prawdziwego guiHelper i metody budującej panel NVDA, ale pozostałe
usługi NVDA zastępuje modelami z testów jednostkowych. Nie uruchamia pętli
zdarzeń, nie pokazuje okien i nie przejmuje fokusu.
"""

from __future__ import annotations

import argparse
import ast
import gettext
import importlib.util
import json
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--nvda-source", required=True, type=Path)
	parser.add_argument("--interactive", action="store_true", help="Otwiera okna i testuje klawiaturę; wymaga odrębnej zgody.")
	args = parser.parse_args()
	import wx
	from wx.lib import scrolledpanel
	app = wx.App(False)
	real_wx = {name: value for name, value in sys.modules.items() if name == "wx" or name.startswith("wx.")}
	sys.path.insert(0, str(ROOT / "tests"))
	from test_plugin_import import PluginImportTests
	PluginImportTests.setUpClass()
	sys.modules.update(real_wx)
	for name in tuple(sys.modules):
		if name == "easyAudioConverter" or name.startswith("easyAudioConverter."):
			del sys.modules[name]
	helper_path = args.nvda_source / "gui" / "guiHelper.py"
	spec = importlib.util.spec_from_file_location("gui.guiHelper", helper_path)
	helper = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = helper
	spec.loader.exec_module(helper)
	sys.modules["gui"].guiHelper = helper
	sys.modules["gui"].mainFrame = None
	source = ast.parse((args.nvda_source / "gui" / "settingsDialogs.py").read_text(encoding="utf-8-sig"))
	panel_class = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "SettingsPanel")
	build_method = next(node for node in panel_class.body if isinstance(node, ast.FunctionDef) and node.name == "_buildGui")
	code = compile(ast.Module(body=[build_method], type_ignores=[]), "SettingsPanel._buildGui", "exec")
	namespace = {"wx": wx}
	exec(code, namespace)

	class SettingsPanel(wx.Panel):
		_buildGui = namespace["_buildGui"]

		def __init__(self, parent):
			super().__init__(parent)
			self._buildGui()

	sys.modules["gui.settingsDialogs"].SettingsPanel = SettingsPanel
	path = ROOT / "src" / "globalPlugins" / "easyAudioConverter" / "__init__.py"
	spec = importlib.util.spec_from_file_location("easyAudioConverter", path, submodule_search_locations=[str(path.parent)])
	module = importlib.util.module_from_spec(spec)
	module._ = gettext.translation("nvda", str(ROOT / "src" / "locale"), languages=["pl"]).gettext
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)

	class Config(dict):
		spec = {}

	defaults = {}
	for key, value in module.CONFIG_SPEC.items():
		call = ast.parse(value, mode="eval").body
		default = next(item.value for item in call.keywords if item.arg == "default")
		defaults[key] = [ast.literal_eval(item) for item in default.args] if isinstance(default, ast.Call) else ast.literal_eval(default)
	sys.modules["config"].conf = Config({module.CONFIG_SECTION: defaults})
	dialogs = sys.modules["easyAudioConverter.settings_dialogs"]
	other = wx.Dialog(None)
	other_button = wx.Button(other, wx.ID_OK, label="Przycisk obcego okna")
	for factory in (() if args.interactive else (
		lambda: dialogs.EasyAudioConverterSettingsDialog(None, initial_tab=1),
		lambda: dialogs.CodecOptionsDialog(None, module.ConversionSettings(mp3_encoder="gogo")),
		lambda: dialogs.ConversionOptionsDialog(None, item_count=1, initial_settings=module.ConversionSettings(mp3_encoder="gogo")),
	)):
		dialog = factory()
		try:
			dialog.Layout()
			area = wx.Display(0).GetClientArea()
			rect = dialog.GetScreenRect()
			button = wx.FindWindowById(wx.ID_OK, dialog)
			print(json.dumps({"okno": type(dialog).__name__, "rozmiar": list(rect), "obszar": list(area), "mieści_się": area.Contains(rect), "przycisk_OK": list(button.GetScreenRect()), "OK_w_oknie": rect.Contains(button.GetScreenRect()), "wx": wx.version()}, ensure_ascii=False), flush=True)
			assert area.Contains(rect) and rect.Contains(button.GetScreenRect())
			assert button.GetSize().height > 0 and button.GetSize().width > 0
			dialog.SetSize((660, 500))
			dialog.Layout()
			assert dialog.GetScreenRect().Contains(button.GetScreenRect())
			assert button.GetSize().height > 0
			assert other_button.GetLabel() == "Przycisk obcego okna"
			if isinstance(dialog, dialogs.ConversionOptionsDialog):
				assert button.GetLabel() == module._("Convert")
				assert isinstance(dialog.content_panel, scrolledpanel.ScrolledPanel)
				assert button.GetParent() is dialog
		finally:
			dialog.Destroy()
	other.Destroy()
	if args.interactive:
		# Modele usług dotyczą wyłącznie tego procesu, nie działającego NVDA.
		import ctypes
		from ctypes import wintypes
		import uuid
		import pythoncom
		import win32gui
		import validate_nvda_codec_dialogs

		def accessible_focus():
			control = wx.Window.FindFocus()
			if control is None:
				raise RuntimeError("Brak fokusu testowanego procesu.")
			pointer = ctypes.c_void_p()
			iid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID("618736e0-3c3d-11cf-810c-00aa00389b71").bytes_le)
			hresult = ctypes.windll.oleacc.AccessibleObjectFromWindow(wintypes.HWND(win32gui.GetFocus()), ctypes.c_uint(0xFFFFFFFC), ctypes.byref(iid), ctypes.byref(pointer))
			if hresult:
				raise RuntimeError("Nie można odczytać MSAA kontrolki: " + str(hresult))
			accessible = pythoncom.ObjectFromAddress(pointer.value, pythoncom.IID_IDispatch)
			def value(dispid):
				return accessible.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYGET, True, 0)
			return types.SimpleNamespace(name=value(-5003), value=value(-5004), role=value(-5006))

		class Validator:
			def get_default_value(self, value):
				call = ast.parse(value, mode="eval").body
				default = next(item.value for item in call.keywords if item.arg == "default")
				return [ast.literal_eval(item) for item in default.args] if isinstance(default, ast.Call) else ast.literal_eval(default)

		sys.modules["api"].getFocusObject = accessible_focus
		def message_box(message, caption, style, parent=None):
			dialog = wx.GenericMessageDialog(parent, message, caption, style)
			sys.modules["gui"].last_test_message = dialog
			try:
				return dialog.ShowModal()
			finally:
				dialog.Destroy()
		sys.modules["gui"].messageBox = message_box
		sys.modules["versionInfo"] = types.SimpleNamespace(version="niedostępna w osobnym procesie; odczyt MSAA zamiast rejestracji mowy")
		sys.modules["speechViewer"] = types.SimpleNamespace(appendSpeechSequence=lambda sequence: None)
		sys.modules["configobj.validate"] = types.SimpleNamespace(Validator=Validator)
		keeper = wx.Frame(None, title="Próba okien Easy Audio Converter", size=(500, 150))
		wx.StaticText(keeper, label="Trwa automatyczna próba okien. Konfiguracja użytkownika nie jest zmieniana.")
		app.SetTopWindow(keeper)
		keeper.Show()
		result = validate_nvda_codec_dialogs.start(require_speech=False)
		app.SetExitOnFrameDelete(False)
		timer = wx.Timer(app)
		app.Bind(wx.EVT_TIMER, lambda event: app.ExitMainLoop() if result["state"] != "running" else None, timer)
		timer.Start(500)
		app.MainLoop()
		keeper.Destroy()
		assert result["state"] == "completed", result.get("error")
	app.Destroy()


if __name__ == "__main__":
	main()
