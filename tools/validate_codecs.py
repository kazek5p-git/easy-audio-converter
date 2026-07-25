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

from converter import (  # noqa: E402
	FORMAT_KEYS,
	ConversionCallbacks,
	ConversionSettings,
	Converter,
	parse_ffmetadata,
)


def read_metadata(ffmpeg: Path, path: Path) -> dict[str, str]:
	result = subprocess.run(
		[
			str(ffmpeg),
			"-nostdin",
			"-hide_banner",
			"-loglevel",
			"error",
			"-i",
			str(path),
			"-f",
			"ffmetadata",
			"-",
		],
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
		encoding="utf-8",
		errors="replace",
		check=False,
	)
	return parse_ffmetadata(result.stdout)


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
		existing_target = source_tree / "already mp3.mp3"
		existing_target_command = [
			str(ffmpeg),
			"-nostdin",
			"-hide_banner",
			"-loglevel",
			"error",
			"-i",
			str(source),
			"-c:a",
			"libmp3lame",
			"-y",
			str(existing_target),
		]
		if subprocess.run(existing_target_command, check=False).returncode != 0:
			raise RuntimeError("Could not create the existing target-format file")
		existing_target_contents = existing_target.read_bytes()
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
			or batch_summary.ignored != 1
			or not expected_nested_output.is_file()
			or existing_target.read_bytes() != existing_target_contents
			or (source_tree / "already mp3 - converted.mp3").exists()
		):
			failures.append(
				"recursive batch: target-format skip, output exclusion, or folder preservation failed"
			)
			print("FAIL recursive batch")
		else:
			print("PASS recursive batch, target-format skip, and folder preservation")

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

		tagged_source = root / "tagged source.mp3"
		tag_command = [
			str(ffmpeg),
			"-nostdin",
			"-hide_banner",
			"-loglevel",
			"error",
			"-i",
			str(source),
			"-c:a",
			"libmp3lame",
			"-metadata",
			"title=Metadata title",
			"-metadata",
			"artist=Metadata artist",
			"-metadata",
			"album=Metadata album",
			"-metadata",
			"comment=Metadata comment",
			"-y",
			str(tagged_source),
		]
		if subprocess.run(tag_command, check=False).returncode != 0:
			failures.append("metadata source creation failed")
		else:
			progress_samples = []
			selected_settings = ConversionSettings(
				target_format="flac",
				quality="standard",
				same_folder=False,
				output_folder=str(root / "metadata-selected"),
				metadata_mode="selected",
				metadata_fields=("title", "artist"),
			)
			selected_summary = Converter(ffmpeg).run(
				[tagged_source],
				selected_settings,
				callbacks=ConversionCallbacks(
					on_progress=lambda *values: progress_samples.append(values),
				),
			)
			selected_tags = (
				read_metadata(ffmpeg, Path(selected_summary.outputs[0]))
				if selected_summary.succeeded
				else {}
			)
			if (
				selected_tags.get("title") != "Metadata title"
				or selected_tags.get("artist") != "Metadata artist"
				or "album" in selected_tags
			):
				failures.append("selected metadata filtering failed")
				print("FAIL selected metadata filtering")
			else:
				print("PASS selected metadata filtering")
			if (
				not progress_samples
				or progress_samples[-1][3] != 1.0
				or progress_samples[-1][4] != 1.0
			):
				failures.append("FFmpeg progress callback did not reach 100 percent")
				print("FAIL FFmpeg progress callback")
			else:
				print(f"PASS FFmpeg progress callbacks: {len(progress_samples)} updates")

			all_summary = Converter(ffmpeg).run(
				[tagged_source],
				ConversionSettings(
					target_format="flac",
					same_folder=False,
					output_folder=str(root / "metadata-all"),
					metadata_mode="all",
				),
			)
			all_tags = (
				read_metadata(ffmpeg, Path(all_summary.outputs[0]))
				if all_summary.succeeded
				else {}
			)
			if all_tags.get("album") != "Metadata album" or all_tags.get("comment") != "Metadata comment":
				failures.append("all-metadata copy failed")
				print("FAIL all metadata copy")
			else:
				print("PASS all metadata copy")

			none_summary = Converter(ffmpeg).run(
				[tagged_source],
				ConversionSettings(
					target_format="flac",
					same_folder=False,
					output_folder=str(root / "metadata-none"),
					metadata_mode="none",
				),
			)
			none_tags = (
				read_metadata(ffmpeg, Path(none_summary.outputs[0]))
				if none_summary.succeeded
				else {}
			)
			if any(key in none_tags for key in ("title", "artist", "album", "comment")):
				failures.append("metadata removal failed")
				print("FAIL metadata removal")
			else:
				print("PASS metadata removal")

		advanced_summary = Converter(ffmpeg).run(
			[source],
			ConversionSettings(
				target_format="flac",
				same_folder=False,
				output_folder=str(root / "advanced"),
				advanced_options={
					"enabled": True,
					"sampleRate": 16000,
					"channels": 1,
					"codecLevel": 10,
				},
			),
		)
		if advanced_summary.succeeded:
			probe = subprocess.run(
				[
					str(ffmpeg),
					"-hide_banner",
					"-i",
					advanced_summary.outputs[0],
				],
				stdout=subprocess.DEVNULL,
				stderr=subprocess.PIPE,
				text=True,
				encoding="utf-8",
				errors="replace",
				check=False,
			).stderr
		else:
			probe = ""
		if "16000 Hz" not in probe or "mono" not in probe:
			failures.append("advanced sample-rate/channel overrides failed")
			print("FAIL advanced codec overrides")
		else:
			print("PASS advanced codec overrides")

	if failures:
		print("\nCodec validation failures:", file=sys.stderr)
		for failure in failures:
			print(f"- {failure}", file=sys.stderr)
		return 1
	print(f"\nAll {len(cases)} codec paths passed.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
