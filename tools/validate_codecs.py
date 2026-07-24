"""Perform short end-to-end conversions with every exposed encoder."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "globalPlugins" / "easyAudioConverter"))

from converter import FORMAT_KEYS, ConversionSettings, Converter  # noqa: E402


def main() -> int:
	parser = argparse.ArgumentParser()
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
	args = parser.parse_args()
	ffmpeg = args.ffmpeg.resolve()
	if not ffmpeg.is_file():
		raise FileNotFoundError(ffmpeg)

	failures: list[str] = []
	with tempfile.TemporaryDirectory(prefix="easy-audio-converter-test-") as temporary:
		root = Path(temporary)
		source = root / "źródło テスト.wav"
		create_command = [
			str(ffmpeg),
			"-nostdin",
			"-hide_banner",
			"-loglevel",
			"error",
			"-f",
			"lavfi",
			"-i",
			"sine=frequency=997:duration=0.35",
			"-c:a",
			"pcm_s16le",
			"-y",
			str(source),
		]
		if subprocess.run(create_command, check=False).returncode != 0:
			raise RuntimeError("Could not create the synthetic test source")

		cases = [(format_key, "lame") for format_key in FORMAT_KEYS]
		cases.append(("mp3", "fraunhofer"))
		for number, (format_key, encoder) in enumerate(cases, start=1):
			output_folder = root / f"case-{number:02d}-{format_key}-{encoder}"
			settings = ConversionSettings(
				target_format=format_key,
				quality="standard",
				mp3_encoder=encoder,
				same_folder=False,
				output_folder=str(output_folder),
			)
			summary = Converter(ffmpeg).run([source], settings)
			if summary.succeeded != 1 or summary.failed:
				detail = summary.failures[0].message if summary.failures else "no output"
				failures.append(f"{format_key}/{encoder}: {detail}")
				print(f"FAIL {format_key}/{encoder}")
			else:
				output = Path(summary.outputs[0])
				print(f"PASS {format_key}/{encoder}: {output.stat().st_size} bytes")

		source_tree = root / "album source"
		nested_source = source_tree / "Disc 1"
		nested_source.mkdir(parents=True)
		shutil.copy2(source, source_tree / "opening.wav")
		shutil.copy2(source, nested_source / "track.wav")
		nested_output = source_tree / "converted"
		nested_output.mkdir()
		(nested_output / "old-result.mp3").write_bytes(b"existing output must be excluded")
		batch_settings = ConversionSettings(
			target_format="mp3",
			quality="standard",
			mp3_encoder="lame",
			same_folder=False,
			output_folder=str(nested_output),
			include_subfolders=True,
			preserve_folder_structure=True,
		)
		batch_summary = Converter(ffmpeg).run(
			[source_tree],
			batch_settings,
			source_root=source_tree,
		)
		expected_nested_output = nested_output / "Disc 1" / "track.mp3"
		if (
			batch_summary.total != 2
			or batch_summary.succeeded != 2
			or not expected_nested_output.is_file()
		):
			failures.append("recursive batch: nested output exclusion or folder preservation failed")
			print("FAIL recursive batch")
		else:
			print("PASS recursive batch and folder preservation")

		same_folder_settings = ConversionSettings(
			target_format="wav",
			quality="standard",
			same_folder=True,
		)
		same_folder_summary = Converter(ffmpeg).run([source], same_folder_settings)
		expected_same_folder = source.with_name(f"{source.stem} - converted.wav")
		if same_folder_summary.succeeded != 1 or not expected_same_folder.is_file():
			failures.append("same-format naming: source-safe output was not created")
			print("FAIL same-format source protection")
		else:
			print("PASS same-format source protection")

	if failures:
		print("\nCodec validation failures:", file=sys.stderr)
		for failure in failures:
			print(f"- {failure}", file=sys.stderr)
		return 1
	print(f"\nAll {len(cases)} codec paths passed.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
