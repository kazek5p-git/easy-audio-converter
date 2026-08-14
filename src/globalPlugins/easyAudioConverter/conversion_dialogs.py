# Copyright (C) 2026 Kazimierz Parzych
# SPDX-License-Identifier: GPL-3.0-or-later
"""Okna postępu, wyników i informacji o konwersji dla NVDA."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import api
import config
import gui
import nvwave
import ui
import wx
from logHandler import log

from . import (
	_,
	COMPLETION_SOUND_PATH,
	CONFIG_SECTION,
	CONVERSION_LIFECYCLE_WARNING,
	ConversionPlan,
	ConversionSummary,
	MediaInfo,
	_ensure_config,
	_metadata_field_labels,
)


def _format_bytes(value: int | None) -> str:
	if value is None:
		return _("unknown")
	size = max(0.0, float(value))
	for unit in (_("bytes"), _("KB"), _("MB"), _("GB"), _("TB")):
		if size < 1024.0 or unit == _("TB"):
			return f"{size:.0f} {unit}" if unit == _("bytes") else f"{size:.1f} {unit}"
		size /= 1024.0
	return f"{size:.1f} TB"


def _build_plan_report(plan: ConversionPlan) -> str:
	lines = [
		_("Conversion plan"),
		_("Files to convert: {count}").format(count=plan.total),
		_("Skipped inputs: {count}").format(count=plan.ignored),
		_("Destination: {destination}").format(
			destination=plan.destination or _("source folders")
		),
		_("Input size: {size}").format(size=_format_bytes(plan.input_bytes)),
		_("Estimated output size: {size}").format(
			size=_format_bytes(plan.estimated_output_bytes)
		),
		_("Free disk space: {size}").format(size=_format_bytes(plan.free_space_bytes)),
		_("Total audio duration: {duration}").format(
			duration=(
				_format_elapsed(plan.total_duration)
				if plan.total_duration is not None
				else _("unknown")
			)
		),
	]
	if plan.replace_source_files:
		lines.append(
			_(
				"Warning: source files will be permanently deleted after "
				"successful conversion.",
			)
		)
	if plan.lossy_to_lossy_count:
		lines.append(
			_(
				"Warning: {count} files will be converted from a lossy format "
				"to another lossy format, which can reduce quality.",
			).format(count=plan.lossy_to_lossy_count)
		)
	if (
		plan.estimated_output_bytes is not None
		and plan.free_space_bytes is not None
		and plan.estimated_output_bytes > plan.free_space_bytes
	):
		lines.append(
			_("Warning: the estimated output is larger than the available disk space.")
		)
	if plan.items:
		lines.extend(("", _("Planned output files:")))
		for item in plan.items[:500]:
			lines.append(f"{item.source_path} -> {item.output_path}")
		if len(plan.items) > 500:
			lines.append(
				_("...and {count} more files").format(count=len(plan.items) - 500)
			)
	return "\n".join(lines)


class ConversionPlanDialog(wx.Dialog):
	"""Accessible confirmation of the exact files and output names."""

	def __init__(self, parent, plan: ConversionPlan):
		super().__init__(
			parent,
			title=_("Review conversion plan"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		if plan.replace_source_files:
			description = _(
				"Review the plan below. Size estimates are approximate. "
				"Source files will be permanently deleted after their outputs "
				"are completed successfully.",
			)
		else:
			description = _(
				"Review the plan below. Size estimates are approximate. "
				"No source file will be overwritten.",
			)
		description = f"{description}\n\n{CONVERSION_LIFECYCLE_WARNING}"
		sizer.Add(
			wx.StaticText(
				panel,
				label=description,
			),
			0,
			wx.ALL | wx.EXPAND,
			8,
		)
		self.report = wx.TextCtrl(
			panel,
			value=_build_plan_report(plan),

			style=wx.TE_MULTILINE | wx.TE_READONLY,
		)
		sizer.Add(self.report, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		buttons = wx.StdDialogButtonSizer()
		start_button = wx.Button(panel, wx.ID_OK, _("Start conversion"))
		cancel_button = wx.Button(panel, wx.ID_CANCEL)
		buttons.AddButton(start_button)
		buttons.AddButton(cancel_button)
		buttons.Realize()
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizer(outer)
		self.SetSize((820, 580))
		self.SetMinSize((620, 400))
		self.CentreOnParent()
		start_button.SetDefault()
		self.report.SetInsertionPoint(0)


def _build_media_info_report(info: MediaInfo) -> str:
	lines = [
		_("Audio file information"),
		_("Path: {path}").format(path=info.source_path),
		_("Container: {value}").format(value=info.container or _("unknown")),
		_("Audio codec: {value}").format(value=info.codec or _("unknown")),
		_("Duration: {value}").format(
			value=_format_elapsed(info.duration) if info.duration is not None else _("unknown")
		),
		_("Bitrate: {value}").format(
			value=(
				_("{value} kbps").format(value=info.bitrate_kbps)
				if info.bitrate_kbps is not None
				else _("unknown")
			)
		),
		_("Channels: {value}").format(value=info.channels or _("unknown")),
		_("Sample rate: {value}").format(
			value=(
				_("{value} Hz").format(value=info.sample_rate)
				if info.sample_rate is not None
				else _("unknown")
			)
		),
		_("File size: {value}").format(value=_format_bytes(info.size_bytes)),
		_("Embedded artwork: {value}").format(
			value=_("yes") if info.has_artwork else _("no")
		),
		_("Chapters: {value}").format(value=info.chapter_count),
	]
	if info.metadata:
		lines.extend(("", _("Metadata:")))
		labels = _metadata_field_labels()
		for key, value in sorted(info.metadata.items()):
			lines.append(f"{labels.get(key, key)}: {value}")
	return "\n".join(lines)


class AudioInfoDialog(wx.Dialog):
	"""Modeless, copyable technical information for a selected audio file."""

	def __init__(self, parent, info: MediaInfo):
		super().__init__(
			parent,
			title=_("Audio file information"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._report = _build_media_info_report(info)
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.details = wx.TextCtrl(
			panel,
			value=self._report,
			style=wx.TE_MULTILINE | wx.TE_READONLY,
		)
		sizer.Add(self.details, 1, wx.ALL | wx.EXPAND, 8)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		copy_button = wx.Button(panel, label=_("Copy information"))
		close_button = wx.Button(panel, wx.ID_CLOSE, _("Close"))
		buttons.Add(copy_button, 0, wx.RIGHT, 8)
		buttons.Add(close_button, 0)
		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizer(outer)
		self.SetSize((700, 500))
		self.SetMinSize((520, 360))
		self.CentreOnParent()
		copy_button.Bind(wx.EVT_BUTTON, self._on_copy)
		close_button.Bind(wx.EVT_BUTTON, lambda event: self.Hide())
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self.details.SetInsertionPoint(0)

	def _on_copy(self, event):
		try:
			if api.copyToClip(self._report) is False:
				raise RuntimeError
		except Exception:

			ui.message(_("Could not copy the audio information"))
		else:
			ui.message(_("Audio information copied"))

	def _on_close(self, event):
		self.Hide()
		if event.CanVeto():
			event.Veto()


def _format_elapsed(seconds: float | None) -> str:
	seconds = max(0, int(seconds or 0))
	hours, remainder = divmod(seconds, 3600)
	minutes, seconds = divmod(remainder, 60)
	if hours:
		return f"{hours:d}:{minutes:02d}:{seconds:02d}"
	return f"{minutes:d}:{seconds:02d}"


def _estimate_remaining(elapsed_seconds: float, overall_fraction: float) -> float | None:
	"""Estimate remaining time from stable, bounded overall progress."""
	elapsed_seconds = max(0.0, float(elapsed_seconds))
	overall_fraction = max(0.0, min(1.0, float(overall_fraction)))
	if overall_fraction >= 1.0:
		return 0.0
	if elapsed_seconds < 2.0 or overall_fraction < 0.01:
		return None
	remaining = elapsed_seconds * (1.0 - overall_fraction) / overall_fraction
	if remaining > 30 * 24 * 60 * 60:
		return None
	return max(0.0, remaining)


def _conversion_completed_successfully(summary: ConversionSummary) -> bool:
	"""Return whether every planned conversion completed without errors."""
	return bool(
		summary.total > 0
		and summary.succeeded == summary.total
		and summary.failed == 0
		and not summary.canceled
		and not summary.stopped_after_current
	)


def _play_event_sound(path: Path, event_name: str) -> None:
	"""Play one bundled event sound without blocking NVDA."""
	try:
		nvwave.playWaveFile(str(path), asynchronous=True)
	except Exception:
		log.debugWarning(
			f"Easy Audio Converter: failed to play the {event_name} sound",
			exc_info=True,
		)


def _play_completion_sound() -> None:
	"""Play the bundled success notification without blocking NVDA."""
	_play_event_sound(COMPLETION_SOUND_PATH, "completion")


def _event_sound_enabled(config_key: str, default: bool = True) -> bool:
	try:
		_ensure_config()
		return bool(config.conf[CONFIG_SECTION].get(config_key, default))
	except Exception:
		return default


def _stage_status_label(stage: str) -> str:
	return {
		"planning": _("Building the conversion plan"),
		"probing": _("Reading audio information"),
		"analyzingLoudness": _("Analyzing loudness, first pass"),
		"converting": _("Converting audio, second pass"),
		"verifying": _("Verifying the output by decoding it"),
	}.get(stage, _("Preparing the conversion"))


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
		on_stop_after_current: Callable[[], None],
		on_clear_queue: Callable[[], None],
		on_report: Callable[[], None],
		on_results: Callable[[], None],
	):
		self._progress_title = _("Converting — Easy Audio Converter")
		self._last_overall_percent = 0
		super().__init__(
			parent,
			title=f"0% — {self._progress_title}",
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._on_cancel_callback = on_cancel
		self._on_stop_after_current_callback = on_stop_after_current
		self._on_clear_queue_callback = on_clear_queue
		self._on_report_callback = on_report
		self._on_results_callback = on_results
		self._running = True
		self._cancel_requested = False
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.current_file = wx.StaticText(panel, label=_("Preparing the conversion"))
		sizer.Add(self.current_file, 0, wx.ALL | wx.EXPAND, 8)
		self.lifecycle_warning = wx.StaticText(panel, label=CONVERSION_LIFECYCLE_WARNING)
		self.lifecycle_warning.Wrap(520)
		sizer.Add(self.lifecycle_warning, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
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
		self.remaining_status = wx.StaticText(
			panel,
			label=_("Estimated time remaining: calculating"),
		)
		sizer.Add(self.remaining_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		self.queue_status = wx.StaticText(panel, label=_("Queued jobs: 0"))
		sizer.Add(self.queue_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		self.parallel_status = wx.StaticText(
			panel,
			label=_("Parallel workers: waiting"),
		)
		sizer.Add(self.parallel_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

		button_sizer = wx.FlexGridSizer(rows=2, cols=3, vgap=8, hgap=8)
		self.cancel_button = wx.Button(panel, label=_("Cancel conversion"))
		self.stop_button = wx.Button(panel, label=_("Stop after current file"))
		self.clear_queue_button = wx.Button(panel, label=_("Clear queued jobs"))
		self.report_button = wx.Button(panel, label=_("Report conversion status"))
		self.results_button = wx.Button(panel, label=_("Show results"))
		self.hide_button = wx.Button(panel, label=_("Hide"))
		button_sizer.Add(self.cancel_button, 0)
		button_sizer.Add(self.stop_button, 0)
		button_sizer.Add(self.clear_queue_button, 0)
		button_sizer.Add(self.report_button, 0)
		button_sizer.Add(self.results_button, 0)
		button_sizer.Add(self.hide_button, 0)
		sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer_sizer = wx.BoxSizer(wx.VERTICAL)
		outer_sizer.Add(panel, 1, wx.EXPAND)
		self.SetSizerAndFit(outer_sizer)
		self.SetMinSize((560, self.GetSize().height))

		self.CentreOnParent()
		self.cancel_button.Bind(wx.EVT_BUTTON, self._on_cancel)
		self.stop_button.Bind(wx.EVT_BUTTON, self._on_stop)
		self.clear_queue_button.Bind(wx.EVT_BUTTON, self._on_clear_queue)
		self.report_button.Bind(wx.EVT_BUTTON, self._on_report)
		self.results_button.Bind(wx.EVT_BUTTON, self._on_results)
		self.hide_button.Bind(wx.EVT_BUTTON, self._on_hide)
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self.results_button.Disable()
		self.clear_queue_button.Disable()

	def _update_progress_title(self, percent: int | None = None) -> None:
		"""Ustaw tytuł okna z aktualnym postępem całej konwersji."""
		if percent is not None:
			self._last_overall_percent = max(0, min(100, int(percent)))
		title = f"{self._last_overall_percent}% — {self._progress_title}"
		self.SetTitle(title)

	def set_title_prefix(self, title: str) -> None:
		"""Ustaw opis okna, zachowując dopisywanie procentu postępu."""
		self._progress_title = str(title or "")
		self._update_progress_title()

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
		self._update_progress_title(overall_percent)
		self.overall_gauge.SetValue(overall_percent * 10)
		self.overall_status.SetLabel(
			_("Overall progress: {percent}%").format(percent=overall_percent)
		)
		self.elapsed_status.SetLabel(
			_("Elapsed time: {elapsed}").format(elapsed=_format_elapsed(elapsed_seconds))
		)
		remaining = _estimate_remaining(elapsed_seconds, overall_fraction)
		self.remaining_status.SetLabel(
			_("Estimated time remaining: {remaining}").format(
				remaining=(
					_format_elapsed(remaining)
					if remaining is not None
					else _("calculating")
				)
			)
		)

	def update_stage(self, index: int, total: int, source_name: str, stage: str) -> None:
		if not self._running:
			return
		label = _stage_status_label(stage)
		if source_name and total:
			label = _("{stage}. File {index} of {total}: {name}").format(
				stage=label,
				index=index,
				total=total,
				name=source_name,
			)
		self.current_file.SetLabel(label)

	def set_queue_count(self, count: int) -> None:
		count = max(0, int(count))
		self.queue_status.SetLabel(_("Queued jobs: {count}").format(count=count))
		self.clear_queue_button.Enable(self._running and count > 0)

	def set_parallelism(self, active: int, target: int, adaptive: bool) -> None:
		if not self._running:
			return
		active = max(0, int(active))
		target = max(1, int(target))
		if adaptive:

			self.parallel_status.SetLabel(
				_("Adaptive workers: {active} active, target {target}").format(
					active=active,
					target=target,
				)
			)
		else:
			self.parallel_status.SetLabel(
				_("Parallel workers: {active} active of {target}").format(
					active=active,
					target=target,
				)
			)

	def finish(self, message: str, completed: bool, has_results: bool = False) -> None:
		self._running = False
		self.current_file.SetLabel(message)
		self.remaining_status.SetLabel(_("Estimated time remaining: 0:00"))
		self.parallel_status.SetLabel(_("Parallel workers: finished"))
		if completed:
			self._update_progress_title(100)
			self.file_gauge.SetValue(1000)
			self.overall_gauge.SetValue(1000)
			self.file_status.SetLabel(_("Current file progress: 100%"))
			self.overall_status.SetLabel(_("Overall progress: 100%"))
		self.hide_button.SetLabel(_("Close"))
		if self.IsShown():
			self.hide_button.SetFocus()
		self.cancel_button.SetLabel(_("Cancel conversion"))
		self.cancel_button.Disable()
		self.stop_button.Disable()
		self.clear_queue_button.Disable()
		self.report_button.Disable()
		self.results_button.Enable(has_results)

	def _on_cancel(self, event):
		if self._running and not self._cancel_requested:
			self._cancel_requested = True
			self.cancel_button.SetLabel(_("Canceling..."))
			self._on_cancel_callback()

	def _on_stop(self, event):
		if self._running:
			self.stop_button.SetLabel(_("Stopping after this file..."))
			self.stop_button.Disable()
			self._on_stop_after_current_callback()

	def _on_clear_queue(self, event):
		if self._running:
			self._on_clear_queue_callback()

	def _on_report(self, event):
		if self._running:
			self._on_report_callback()

	def _on_results(self, event):
		if not self._running:
			self._on_results_callback()

	def _on_hide(self, event):
		self.Hide()

	def _on_close(self, event):
		self.Hide()
		if event.CanVeto():
			event.Veto()


def _friendly_failure_message(message: str) -> str:
	"""Translate common FFmpeg and filesystem failures into actionable text."""
	last_line = message.splitlines()[-1].strip() if message else ""
	lowered = last_line.casefold()
	if "the gogo output path already exists; no file was overwritten" in lowered:
		return _("The GOGO output path already exists; no file was overwritten.")
	if "could not remove source file after successful conversion" in message.casefold():
		return _(
			"The converted output was kept, but the source file could not be removed."
		)
	if "permission denied" in lowered or "access is denied" in lowered:
		return _("Access to the source or destination was denied.")
	if "no space left on device" in lowered or "not enough space" in lowered:
		return _("There is not enough free disk space.")
	if "invalid data found" in lowered:
		return _("The input file is damaged or uses an unsupported encoding.")
	if "does not contain any stream" in lowered or "matches no streams" in lowered:
		return _("The input does not contain a readable audio stream.")
	if "output duration differs" in lowered:
		return _("Output verification failed because its duration differs from the source.")
	if "could not preserve source file dates" in lowered:
		return _("The source file dates could not be preserved.")
	return last_line[:1000] if last_line else _("Unknown error")


def _skipped_reason_label(reason: str) -> str:
	return {
		"targetFormat": _("Already uses the target format"),
		"unsupported": _("Unsupported file type"),
		"unavailable": _("File or folder is unavailable"),
		"noAudioStream": _("No readable audio stream was found"),
		"requiresAac": _(
			"The first audio stream is not AAC, so it cannot be remuxed to M4A"
		),
		"gogoRequiresWav": _(
			"GOGO can encode only WAV/WAVE source files"
		),
	}.get(reason, _("Skipped"))



def _format_timing_seconds(seconds: float | None) -> str:
	"""Formatuj krótki pomiar, zachowując ułamki dla szybkich etapów."""
	value = max(0.0, float(seconds or 0.0))
	if value < 60.0:
		return f"{value:.2f} s"
	return _format_elapsed(value)


def _build_timing_report(summary: ConversionSummary) -> list[str]:
	timing = summary.timing
	return [
		_("Timing:"),
		_("Total wall time: {value}").format(
			value=_format_timing_seconds(timing.wall_seconds),
		),
		_("Input recognition: {value}").format(
			value=_format_timing_seconds(timing.probe_seconds),
		),
		_("Loudness analysis: {value}").format(
			value=_format_timing_seconds(timing.analysis_seconds),
		),
		_("Encoding and output writing: {value}").format(
			value=_format_timing_seconds(timing.encode_seconds),
		),
		_("Verification and finalization: {value}").format(
			value=_format_timing_seconds(timing.finalize_seconds),
		),
		_("Probe cache hits: {count}; misses: {misses}").format(
			count=timing.probe_cache_hits,
			misses=timing.probe_cache_misses,
		),
	]


def _build_results_report(summary: ConversionSummary) -> str:
	"""Build a complete localized plain-text report for the clipboard."""
	lines = [
		_("Conversion results"),
		_("Succeeded: {done}. Failed: {failed}. Skipped: {skipped}.").format(
			done=summary.succeeded,
			failed=summary.failed,
			skipped=summary.ignored,
		),
	]
	lines.extend(("", *_build_timing_report(summary)))
	if summary.canceled:
		lines.append(_("The conversion was canceled."))
	if summary.stopped_after_current:
		lines.append(_("The job was stopped after the current file."))
	if summary.successes:
		lines.extend(("", _("Successful files:")))
		for success in summary.successes:
			lines.append(f"{success.source_path} -> {success.output_path}")
	elif summary.outputs:
		lines.extend(("", _("Output files:"), *summary.outputs))
	if summary.failures:
		lines.extend(("", _("Failed files:")))
		for failure in summary.failures:
			source = failure.source_path or failure.source_name
			lines.append(f"{source}: {_friendly_failure_message(failure.message)}")
			if failure.output_path:
				lines.append(
					_("Converted output kept at: {output}").format(
						output=failure.output_path,
					)
				)
	if summary.skipped_files:
		lines.extend(("", _("Skipped files:")))
		for skipped in summary.skipped_files:
			lines.append(f"{skipped.source_path}: {_skipped_reason_label(skipped.reason)}")
		hidden_count = max(0, summary.ignored - len(summary.skipped_files))
		if hidden_count:
			lines.append(
				_("...and {count} more skipped files").format(count=hidden_count)
			)
	return "\n".join(lines)


class ConversionResultsDialog(wx.Dialog):
	"""Accessible modeless view of the most recent conversion results."""

	def __init__(
		self,
		parent,
		summary: ConversionSummary,
		on_retry_failed: Callable[[], None],
	):
		super().__init__(
			parent,
			title=_("Easy Audio Converter results"),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self._summary = summary
		self._on_retry_failed_callback = on_retry_failed
		self._entries: list[tuple[str, str, str | None]] = []
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(

			wx.StaticText(
				panel,
				label=_("Succeeded: {done}. Failed: {failed}. Skipped: {skipped}.").format(
					done=summary.succeeded,
					failed=summary.failed,
					skipped=summary.ignored,
				),
			),
			0,
			wx.ALL | wx.EXPAND,
			8,
		)
		for success in summary.successes:
			self._entries.append(
				(
					_("Success: {name}").format(name=Path(success.output_path).name),
					_(
						"Source:\n{source}\n\nOutput:\n{output}",
					).format(
						source=success.source_path,
						output=success.output_path,
					),
					success.output_path,
				)
			)
		if not summary.successes:
			for output in summary.outputs:
				self._entries.append(
					(
						_("Success: {name}").format(name=Path(output).name),
						_("Output:\n{output}").format(output=output),
						output,
					)
				)
		for failure in summary.failures:
			source = failure.source_path or failure.source_name
			details = _("Source:\n{source}\n\nError:\n{error}").format(
				source=source,
				error=_friendly_failure_message(failure.message),
			)
			if failure.output_path:
				details += "\n\n" + _(
					"Converted output kept at:\n{output}",
				).format(output=failure.output_path)
			self._entries.append(
				(
					_("Failed: {name}").format(name=failure.source_name),
					details,
					failure.output_path or None,
				)
			)
		for skipped in summary.skipped_files:
			self._entries.append(
				(
					_("Skipped: {name}").format(name=Path(skipped.source_path).name),
					_("Source:\n{source}\n\nReason:\n{reason}").format(
						source=skipped.source_path,
						reason=_skipped_reason_label(skipped.reason),
					),
					None,
				)
			)
		hidden_count = max(0, summary.ignored - len(summary.skipped_files))
		if hidden_count:
			self._entries.append(
				(
					_("Additional skipped files: {count}").format(count=hidden_count),
					_(
						"Details are limited to the first {limit} skipped files.",
					).format(limit=len(summary.skipped_files)),
					None,
				)
			)
		self.result_list = wx.ListBox(
			panel,
			choices=[entry[0] for entry in self._entries],
			style=wx.LB_SINGLE,
		)
		sizer.Add(self.result_list, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
		sizer.Add(
			wx.StaticText(panel, label=_("Details:")),
			0,
			wx.LEFT | wx.RIGHT | wx.BOTTOM,
			8,
		)
		self.details = wx.TextCtrl(
			panel,
			style=wx.TE_MULTILINE | wx.TE_READONLY,
		)
		sizer.Add(self.details, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

		buttons = wx.BoxSizer(wx.HORIZONTAL)
		self.retry_button = wx.Button(panel, label=_("Retry failed files"))
		self.open_button = wx.Button(panel, label=_("Open output folder"))
		self.copy_button = wx.Button(panel, label=_("Copy report"))
		self.close_button = wx.Button(panel, wx.ID_CLOSE, _("Close"))
		buttons.Add(self.retry_button, 0, wx.RIGHT, 8)
		buttons.Add(self.open_button, 0, wx.RIGHT, 8)
		buttons.Add(self.copy_button, 0, wx.RIGHT, 8)
		buttons.Add(self.close_button, 0)

		sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
		panel.SetSizer(sizer)
		outer = wx.BoxSizer(wx.VERTICAL)
		outer.Add(panel, 1, wx.EXPAND)
		self.SetSizer(outer)
		self.SetSize((760, 520))
		self.SetMinSize((600, 400))
		self.CentreOnParent()

		self.result_list.Bind(wx.EVT_LISTBOX, self._on_selected)
		self.retry_button.Bind(wx.EVT_BUTTON, self._on_retry)
		self.open_button.Bind(wx.EVT_BUTTON, self._on_open_output)
		self.copy_button.Bind(wx.EVT_BUTTON, self._on_copy_report)
		self.close_button.Bind(wx.EVT_BUTTON, self._on_close_button)
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self.retry_button.Enable(
			any(
				failure.source_path and not failure.output_path
				for failure in summary.failures
			)
		)
		self.open_button.Enable(any(entry[2] for entry in self._entries))
		if self._entries:
			self.result_list.SetSelection(0)
			self._show_entry(0)
		else:
			self.result_list.Disable()
			self.details.SetValue(_("No file details are available."))

	def show_window(self) -> None:
		if not self.IsShown():
			self.Show()
		self.Raise()
		if self._entries:
			self.result_list.SetFocus()
		else:
			self.close_button.SetFocus()

	def _show_entry(self, index: int) -> None:
		if 0 <= index < len(self._entries):
			self.details.SetValue(self._entries[index][1])
			self.details.SetInsertionPoint(0)

	def _on_selected(self, event) -> None:
		self._show_entry(self.result_list.GetSelection())
		event.Skip()

	def _selected_output(self) -> str | None:
		selection = self.result_list.GetSelection()
		if 0 <= selection < len(self._entries):
			output = self._entries[selection][2]
			if output:
				return output
		return self._summary.outputs[0] if self._summary.outputs else None

	def _on_retry(self, event) -> None:
		self.Hide()
		self._on_retry_failed_callback()

	def _on_open_output(self, event) -> None:
		output = self._selected_output()
		if not output:
			return
		try:
			os.startfile(str(Path(output).parent))
		except OSError:
			gui.messageBox(
				_("Could not open the output folder."),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)

	def _on_copy_report(self, event) -> None:
		try:
			copied = api.copyToClip(_build_results_report(self._summary))
			if copied is False:
				raise RuntimeError("NVDA could not access the clipboard")
		except Exception:
			gui.messageBox(
				_("Could not copy the conversion report."),
				_("Easy Audio Converter"),
				wx.OK | wx.ICON_ERROR,
				self,
			)
			return
		ui.message(_("Conversion report copied"))

	def _on_close_button(self, event) -> None:
		self.Hide()

	def _on_close(self, event) -> None:
		self.Hide()
		if event.CanVeto():
			event.Veto()
