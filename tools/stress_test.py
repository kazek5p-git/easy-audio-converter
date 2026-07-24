"""Stress and cancellation tests for the conversion engine."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "globalPlugins" / "easyAudioConverter"))

from converter import ConversionCallbacks, ConversionSettings, Converter  # noqa: E402


def create_audio(ffmpeg: Path, output: Path, source_filter: str) -> None:
	command = [
		str(ffmpeg),
		"-nostdin",
		"-hide_banner",
		"-loglevel",
		"error",
		"-f",
		"lavfi",
		"-i",
		source_filter,
		"-c:a",
		"pcm_s16le",
		"-y",
		str(output),
	]
	if subprocess.run(command, check=False).returncode != 0:
		raise RuntimeError(f"Could not create stress-test source: {output.name}")


def run_batch_stress(ffmpeg: Path, root: Path, file_count: int) -> None:
	source_root = root / "źródła masowe"
	source_root.mkdir()
	seed = root / "seed.wav"
	create_audio(ffmpeg, seed, "sine=frequency=431:duration=0.06")
	for index in range(file_count):
		directory = source_root / f"grupa-{index % 12:02d}" / f"część-{index % 5:02d}"
		directory.mkdir(parents=True, exist_ok=True)
		long_component = "długi_plik_音声_" + ("x" * 72)
		destination = directory / f"{index:04d}_{long_component}.wav"
		shutil.copy2(seed, destination)
	(source_root / "notes.txt").write_text("unsupported", encoding="utf-8")

	output_root = source_root / "converted"
	output_root.mkdir()
	(output_root / "old.flac").write_bytes(b"must not be scanned")
	progress_values: list[float] = []
	settings = ConversionSettings(
		target_format="flac",
		quality="high",
		same_folder=False,
		output_folder=str(output_root),
		include_subfolders=True,
		preserve_folder_structure=True,
		metadata_mode="none",
		advanced_options={"enabled": True, "codecLevel": 8},
	)
	callbacks = ConversionCallbacks(
		on_progress=lambda _index, _total, _name, _file, overall, _seconds, _duration: (
			progress_values.append(overall)
		),
	)
	tracemalloc.start()
	started = time.monotonic()
	summary = Converter(ffmpeg).run(
		[source_root],
		settings,
		source_root=source_root,
		callbacks=callbacks,
	)
	elapsed = time.monotonic() - started
	_current, peak_memory = tracemalloc.get_traced_memory()
	tracemalloc.stop()
	if summary.total != file_count:
		raise AssertionError(f"Expected {file_count} files, collected {summary.total}")
	if summary.succeeded != file_count or summary.failed:
		raise AssertionError(
			f"Batch result: {summary.succeeded} succeeded, {summary.failed} failed"
		)
	if not progress_values or progress_values[-1] != 1.0:
		raise AssertionError("Overall progress did not reach 100 percent")
	if any(later < earlier for earlier, later in zip(progress_values, progress_values[1:])):
		raise AssertionError("Overall progress moved backwards")
	if len(list(output_root.rglob("*.flac"))) != file_count + 1:
		raise AssertionError("Output count or nested-output exclusion is incorrect")
	print(
		f"PASS batch stress: {file_count} files in {elapsed:.2f}s; "
		f"Python peak memory {peak_memory / (1024 * 1024):.1f} MB"
	)


def run_cancellation_stress(ffmpeg: Path, root: Path) -> None:
	source = root / "long noise.wav"
	create_audio(
		ffmpeg,
		source,
		"anoisesrc=color=white:sample_rate=48000:duration=300",
	)
	output_root = root / "cancel-output"
	settings = ConversionSettings(
		target_format="flac",
		same_folder=False,
		output_folder=str(output_root),
		metadata_mode="none",
		advanced_options={"enabled": True, "codecLevel": 12},
	)
	converter = Converter(ffmpeg)
	result_holder = {}

	def convert() -> None:
		result_holder["summary"] = converter.run([source], settings)

	worker = threading.Thread(target=convert, name="StressCancelWorker")
	worker.start()
	deadline = time.monotonic() + 20
	partial_seen = False
	while time.monotonic() < deadline:
		if any(output_root.glob("*.flac")):
			partial_seen = True
			break
		if not worker.is_alive():
			break
		time.sleep(0.01)
	if not partial_seen:
		converter.cancel()
		worker.join(timeout=10)
		raise AssertionError("Conversion completed before a partial output could be observed")
	converter.cancel()
	worker.join(timeout=20)
	if worker.is_alive():
		raise AssertionError("Canceled conversion thread did not stop")
	summary = result_holder["summary"]
	if not summary.canceled:
		raise AssertionError("Canceled conversion was not reported as canceled")
	if any(output_root.glob("*.flac")):
		raise AssertionError("Partial output remained after cancellation")
	print("PASS cancellation stress: active FFmpeg process stopped and partial output removed")


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--files", type=int, default=250)
	parser.add_argument(
		"--ffmpeg",
		type=Path,
		default=PROJECT_ROOT
		/ "src"
		/ "globalPlugins"
		/ "easyAudioConverter"
		/ "bin"
		/ "ffmpeg.exe",
	)
	arguments = parser.parse_args()
	if arguments.files < 1 or arguments.files > 5000:
		raise ValueError("--files must be between 1 and 5000")
	ffmpeg = arguments.ffmpeg.resolve()
	if not ffmpeg.is_file():
		raise FileNotFoundError(ffmpeg)
	with tempfile.TemporaryDirectory(prefix="easy-audio-converter-stress-") as temporary:
		root = Path(temporary)
		run_batch_stress(ffmpeg, root, arguments.files)
		run_cancellation_stress(ffmpeg, root)
	print("All stress tests passed.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
