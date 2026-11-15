# Copyright (C) 2026 Kazimierz Parzych
# SPDX-License-Identifier: GPL-3.0-or-later
"""Jawnie uruchamiany test okien w konsoli NVDA; nie instaluje dodatku.

Wymaga uzgodnionej interakcji z pulpitem. Konfiguracja jest osobnym obiektem
w pamięci. Raport zawiera tylko kontrolki i mowę z okien tej próby.
"""

from __future__ import annotations

import copy
import gettext
import importlib.util
import json
import sys
import traceback
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_eac_codec_ui_probe"
REPORT = ROOT / "docs" / "test-results" / "nvda-codec-dialogs.json"


def start(*, require_speech=True):
	"""Uruchom wyłącznie w działającym NVDA, po zgodzie na test jego okien."""
	try:
		return _start(require_speech=require_speech)
	except Exception:
		if ROOT.is_relative_to(Path(r"C:\Codex work space")):
			REPORT.parent.mkdir(exist_ok=True)
			REPORT.write_text(json.dumps({"state": "error", "error": traceback.format_exc()}, ensure_ascii=False, indent=2), encoding="utf-8")
		raise


def _start(*, require_speech=True):
	import api
	import gui
	import speechViewer
	import versionInfo
	import wx
	from configobj.validate import Validator

	if not ROOT.is_relative_to(Path(r"C:\Codex work space")):
		raise RuntimeError("Test wymaga katalogu projektu we workspace.")
	if PACKAGE in sys.modules:
		raise RuntimeError("Poprzednia próba nadal działa.")
	translation = gettext.translation("nvda", str(ROOT / "src" / "locale"), languages=["pl"])
	old_bytecode = sys.dont_write_bytecode
	sys.dont_write_bytecode = True
	try:
		path = ROOT / "src" / "globalPlugins" / "easyAudioConverter" / "__init__.py"
		spec = importlib.util.spec_from_file_location(PACKAGE, path, submodule_search_locations=[str(path.parent)])
		module = importlib.util.module_from_spec(spec)
		module._ = translation.gettext
		sys.modules[PACKAGE] = module
		spec.loader.exec_module(module)
	finally:
		sys.dont_write_bytecode = old_bytecode

	class TestConfig(dict):
		spec = {}
		saves = 0

		def save(self):
			self.saves += 1

	validator = Validator()
	conf = TestConfig({module.CONFIG_SECTION: {
		key: validator.get_default_value(value) for key, value in module.CONFIG_SPEC.items()
	}})
	conf[module.CONFIG_SECTION]["outputFolder"] = str(ROOT / "_tymczasowe")
	for name, loaded in tuple(sys.modules.items()):
		if name == PACKAGE or name.startswith(PACKAGE + "."):
			if hasattr(loaded, "config"):
				loaded.config = types.SimpleNamespace(conf=conf)
			loaded._ = translation.gettext
	dialogs = sys.modules[PACKAGE + ".settings_dialogs"]
	result = {"state": "running", "host": "NVDA" if require_speech else "osobny proces wx z modelami usług NVDA", "nvda": versionInfo.version, "wx": wx.version(), "checks": [], "speech": []}
	owned = []
	ended = False
	original_speech = speechViewer.appendSpeechSequence

	def belongs(window):
		while window:
			if window in owned:
				return True
			window = window.GetParent()
		return False

	def record_speech(sequence):
		original_speech(sequence)
		if not ended and belongs(wx.Window.FindFocus()):
			result["speech"].append(" ".join(item for item in sequence if isinstance(item, str)))

	def save():
		REPORT.parent.mkdir(exist_ok=True)
		REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

	def check(condition, description):
		result["checks"].append({"ok": bool(condition), "description": description})
		if not condition:
			raise AssertionError(description)

	def show(dialog):
		owned.append(dialog)
		wx.CallAfter(dialog.ShowModal)
		return dialog

	def click(control):
		check(belongs(control), "Akcja dotyczy własnego okna próby")
		event = wx.CommandEvent(wx.EVT_BUTTON.typeId, control.GetId())
		event.SetEventObject(control)
		wx.PostEvent(control, event)

	def choose(page, target, encoder="lame", mode="auto"):
		page.codec.SetSelection(module.FORMAT_KEYS.index(target))
		page.encoder.SetSelection(module.MP3_ENCODER_KEYS.index(encoder))
		page._on_codec_changed(None)
		page.enabled.SetValue(True)
		page.rate_mode.SetSelection(page._rate_modes.index(mode))
		page._update_control_state()

	def finish(error=None):
		nonlocal ended
		if ended:
			return
		ended = True
		speechViewer.appendSpeechSequence = original_speech
		result["state"] = "error" if error else "completed"
		if error:
			result["error"] = error
		save()
		for dialog in reversed(owned):
			if dialog:
				if dialog.IsModal():
					dialog.EndModal(wx.ID_CANCEL)
				wx.CallAfter(dialog.Destroy)
		for name in tuple(sys.modules):
			if name == PACKAGE or name.startswith(PACKAGE + "."):
				del sys.modules[name]
		save()
		print("Test okien: " + result["state"] + "; raport: " + str(REPORT))

	def steps():
		settings = show(dialogs.EasyAudioConverterSettingsDialog(gui.mainFrame, initial_tab=1))
		yield 1200
		page = settings.advanced_page
		check(settings.IsShown(), "Otwarto rzeczywiste okno ustawień dodatku")
		check(settings.notebook.GetPageCount() == 3, "Trzy zakładki ustawień")
		choose(page, "mp3", "gogo", "vbr")
		page.vbr_quality.SetValue(3)
		page.min_bitrate.SetValue(96)
		page.max_bitrate.SetValue(192)
		for control, expected in (
			(page.rate_mode, "Tryb"), (page.vbr_quality, "VBR"),
			(page.min_bitrate, "Minimalna"), (page.max_bitrate, "Maksymalna"),
		):
			control.SetFocus()
			yield 800
			focus = api.getFocusObject()
			name = focus.name or ""
			result["checks"].append({"focus": name, "value": str(focus.value), "role": str(focus.role)})
			check(expected.casefold() in name.casefold(), "Nazwa dostępności: " + expected)
		page.rate_mode.SetFocus()
		yield 350
		check(belongs(wx.Window.FindFocus()), "Fokus przed próbą Tab jest we własnym oknie")
		wx.Window.FindFocus().Navigate()
		yield 800
		check("VBR" in (api.getFocusObject().name or ""), "Nawigacja Tab przez wx pomija niedostępny bitrate w VBR")
		choose(page, "mp3", "lame", "vbr")
		check(not page.min_bitrate.IsEnabled() and page.copyright.IsEnabled(), "LAME: bez granic, dostępne flagi")
		page.vbr_quality.SetValue(2)
		page.copyright.SetSelection(2)
		page.original.SetSelection(1)
		page.copyright.SetFocus()
		yield 750
		check("copyright" in (api.getFocusObject().name or "").casefold(), "Nazwa dostępności flagi copyright")
		choose(page, "mp3", "fraunhofer", "cbr")
		check(page._rate_modes == ("auto", "cbr"), "Fraunhofer: tylko domyślny i CBR")
		page.bitrate.SetValue(192)
		for target, mode in (("ogg", "abr"), ("opus", "cvbr"), ("aac", "vbr"), ("m4a", "vbr"), ("flac", "auto"), ("wavpack", "auto"), ("ac3", "cbr"), ("eac3", "cbr")):
			choose(page, target, mode=mode)
			check(page.rate_mode.IsEnabled() == (target not in {"flac", "wavpack"}), "Tryb kodeka " + target)
			if target in {"aac", "m4a"}:
				page.vbr_quality.SetValue(0.1)
				check(abs(page.vbr_quality.GetValue() - 0.1) < 0.001, "Ułamkowa jakość AAC " + target)
			if target in {"flac", "wavpack"}:
				page.lossless_compression.SetSelection(page.lossless_compression.GetCount() - 1)
			page.enabled.SetFocus()
			yield 300
		choose(page, "mp3", "gogo", "vbr")
		check(page.min_bitrate.GetValue() == 96, "GOGO zachowuje osobny profil po zmianach kodeka")
		settings.notebook.SetSelection(2)
		processing = settings.processing_page
		processing.loudness_preset.SetSelection(module.LOUDNESS_PRESET_KEYS.index("custom"))
		processing._update_control_state()
		for control, unit in ((processing.loudness_target_i, "LUFS"), (processing.loudness_target_tp, "dBTP"), (processing.loudness_target_lra, "LU")):
			control.SetFocus()
			yield 600
			focus = api.getFocusObject()
			check(unit in (focus.name or ""), "Nazwa dostępności pola głośności " + unit)
			result["checks"].append({"focus": focus.name, "value": str(focus.value)})
		processing.loudness_preset.SetSelection(module.LOUDNESS_PRESET_KEYS.index("off"))
		processing._update_control_state()
		click(settings.ok_button)
		yield 900
		check(not settings.IsModal() and conf.saves == 1, "OK zapisuje wszystkie profile tylko do konfiguracji testowej")
		snapshot = copy.deepcopy(dict(conf))
		settings.Destroy()
		settings = show(dialogs.EasyAudioConverterSettingsDialog(gui.mainFrame, initial_tab=1))
		yield 700
		page = settings.advanced_page
		choose(page, "mp3", "gogo", "vbr")
		check(page.max_bitrate.GetValue() == 192, "Ponowne otwarcie odtwarza granice GOGO")
		page.max_bitrate.SetValue(320)
		click(settings.cancel_button)
		yield 500
		check(dict(conf) == snapshot, "Anuluj nie zmienia zapisanej konfiguracji")
		settings.Destroy()
		job = show(dialogs.ConversionOptionsDialog(gui.mainFrame, item_count=1, initial_settings=module.ConversionSettings(mp3_encoder="gogo")))
		yield 1000
		check(job.IsShown(), "Otwarto okno konwersji jednorazowej")
		job.codec_options_button.SetFocus()
		yield 650
		check(module._("Advanced codec settings...") == api.getFocusObject().name, "Dostępna nazwa przycisku edytora kodeka")
		click(job.codec_options_button)
		yield 850
		editor = next(window for window in wx.GetTopLevelWindows() if isinstance(window, dialogs.CodecOptionsDialog) and window.IsShown())
		owned.append(editor)
		check(not editor.page.codec.IsEnabled() and not editor.page.encoder.IsEnabled(), "Edytor jednorazowy blokuje zmianę kodeka")
		editor.page.enabled.SetValue(True)
		editor.page.rate_mode.SetSelection(editor.page._rate_modes.index("vbr"))
		editor.page._update_control_state()
		editor.page.min_bitrate.SetValue(96)
		editor.page.max_bitrate.SetValue(192)
		click(wx.FindWindowById(wx.ID_OK, editor))
		yield 700
		check(job._advanced_options["maxBitrate"] == 192, "OK przenosi opcje do zadania")
		check(dict(conf) == snapshot, "Edytor jednorazowy nie zmienia ustawień domyślnych")
		click(job.codec_options_button)
		yield 750
		editor = next(window for window in wx.GetTopLevelWindows() if isinstance(window, dialogs.CodecOptionsDialog) and window.IsShown())
		owned.append(editor)
		editor.page.max_bitrate.SetValue(320)
		if not require_speech:
			editor.page.min_bitrate.SetValue(256)
			editor.page.max_bitrate.SetValue(96)
			click(wx.FindWindowById(wx.ID_OK, editor))
			yield 700
			message = gui.last_test_message
			owned.append(message)
			check(message.IsModal() and message.GetMessage(), "Błędne granice otwierają rzeczywisty komunikat walidacji")
			result["checks"].append({"validation_message": message.GetMessage()})
			message.EndModal(wx.ID_OK)
			yield 400
			check(editor.IsModal() and job._advanced_options["maxBitrate"] == 192, "Błąd nie zamyka edytora i nie zmienia opcji zadania")
		click(wx.FindWindowById(wx.ID_CANCEL, editor))
		yield 600
		check(job._advanced_options["maxBitrate"] == 192, "Anuluj w edytorze zachowuje opcje zadania")
		click(job.save_profile_button)
		yield 700
		entry = next(window for window in wx.GetTopLevelWindows() if isinstance(window, wx.TextEntryDialog) and window.IsShown())
		owned.append(entry)
		entry.SetValue("Próba kodeków 1.10")
		click(wx.FindWindowById(wx.ID_OK, entry))
		yield 600
		profiles = module._load_user_conversion_profiles(module.ConversionSettings())
		check(len(profiles) == 1 and profiles[0].settings.advanced_options["maxBitrate"] == 192, "Nazwany profil zachowuje nowe opcje")
		click(wx.FindWindowById(wx.ID_CANCEL, job))
		yield 600
		if require_speech:
			check(result["speech"], "Zarejestrowano rzeczywiste komunikaty mowy NVDA")

	speechViewer.appendSpeechSequence = record_speech
	iterator = steps()

	def advance():
		if ended:
			return
		try:
			delay = next(iterator)
			save()
			wx.CallLater(delay, advance)
		except StopIteration:
			finish()
		except Exception:
			finish(traceback.format_exc())

	wx.CallLater(1000, advance)
	wx.CallLater(90000, lambda: finish("Przekroczono limit czasu próby") if not ended else None)
	return result
