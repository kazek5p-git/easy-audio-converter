from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "globalPlugins" / "easyAudioConverter"))

from converter import (  # noqa: E402
	FORMAT_KEYS,
	QUALITY_KEYS,
	ConversionSettings,
	apply_advanced_codec_arguments,
	build_codec_arguments,
	build_metadata_arguments,
	collect_audio_files,
	collect_audio_files_detailed,
	make_unique_output_path,
	parse_duration,
	parse_ffmetadata,
	parse_progress_time,
)


class ConversionSettingsTests(unittest.TestCase):
	def test_every_format_and_quality_has_codec_arguments(self):
		for format_key in FORMAT_KEYS:
			for quality in QUALITY_KEYS:
				with self.subTest(format=format_key, quality=quality):
					arguments = build_codec_arguments(format_key, quality, "lame")
					self.assertIn("-c:a", arguments)

	def test_fraunhofer_selects_media_foundation(self):
		arguments = build_codec_arguments("mp3", "high", "fraunhofer")
		self.assertIn("mp3_mf", arguments)

	def test_invalid_settings_are_rejected(self):
		with self.assertRaises(ValueError):
			ConversionSettings(target_format="invalid").validate()

	def test_advanced_codec_overrides_are_validated_and_applied(self):
		arguments = build_codec_arguments(
			"opus",
			"high",
			"lame",
			{
				"enabled": True,
				"bitrate": 48,
				"sampleRate": 16000,
				"channels": 1,
				"codecLevel": 7,
			},
		)
		self.assertEqual("48k", arguments[arguments.index("-b:a") + 1])
		self.assertNotIn("-ar", arguments)
		self.assertEqual("1", arguments[arguments.index("-ac") + 1])
		self.assertEqual("7", arguments[arguments.index("-compression_level") + 1])
		flac_arguments = build_codec_arguments(
			"flac",
			"high",
			"lame",
			{"enabled": True, "sampleRate": 16000, "channels": 1, "codecLevel": 10},
		)
		self.assertEqual("16000", flac_arguments[flac_arguments.index("-ar") + 1])
		self.assertEqual("1", flac_arguments[flac_arguments.index("-ac") + 1])

	def test_disabled_advanced_profile_does_not_change_arguments(self):
		base = build_codec_arguments("flac", "high", "lame")
		advanced = apply_advanced_codec_arguments(
			base,
			"flac",
			"lame",
			{"enabled": False, "codecLevel": 12},
		)
		self.assertEqual(base, advanced)


class MetadataTests(unittest.TestCase):
	def test_ffmetadata_parser_handles_aliases_and_escaping(self):
		metadata = parse_ffmetadata(
			";FFMETADATA1\n"
			"title=Title\\=part\n"
			"album artist=Various Artists\n"
			"comment=Hash\\# and semicolon\\;\n"
			"[CHAPTER]\n"
			"title=Chapter title\n"
		)
		self.assertEqual("Title=part", metadata["title"])
		self.assertEqual("Various Artists", metadata["album_artist"])
		self.assertEqual("Hash# and semicolon;", metadata["comment"])
		self.assertNotEqual("Chapter title", metadata["title"])

	def test_selected_metadata_arguments_include_only_requested_fields(self):
		arguments = build_metadata_arguments(
			"selected",
			("title", "artist"),
			{"title": "Song", "artist": "Person", "album": "Album"},
		)
		self.assertEqual(["-map_metadata", "-1"], arguments[:2])
		self.assertIn("title=Song", arguments)
		self.assertIn("artist=Person", arguments)
		self.assertNotIn("album=Album", arguments)

	def test_metadata_all_and_none_modes(self):
		self.assertEqual(["-map_metadata", "0"], build_metadata_arguments("all", ()))
		self.assertEqual(["-map_metadata", "-1"], build_metadata_arguments("none", ()))


class ProgressParsingTests(unittest.TestCase):
	def test_duration_parser(self):
		self.assertEqual(3723.5, parse_duration("Duration: 01:02:03.50, start: 0"))
		self.assertIsNone(parse_duration("Duration: N/A"))

	def test_progress_time_parser(self):
		self.assertEqual(62.25, parse_progress_time("00:01:02.250000"))
		self.assertIsNone(parse_progress_time("invalid"))


class FileCollectionTests(unittest.TestCase):
	def test_recursive_collection_filters_and_deduplicates(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			child = root / "album"
			child.mkdir()
			audio = child / "track.FLAC"
			audio.write_bytes(b"audio")
			(root / "notes.txt").write_text("not audio", encoding="utf-8")
			files, ignored = collect_audio_files([root, audio], recursive=True)
			self.assertEqual([audio], files)
			self.assertEqual(1, ignored)

	def test_excluded_destination_tree_is_not_scanned(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			output = root / "converted"
			output.mkdir()
			inside = output / "old.mp3"
			inside.write_bytes(b"audio")
			source = root / "source.wav"
			source.write_bytes(b"audio")
			files, _ignored = collect_audio_files(
				[root],
				recursive=True,
				excluded_roots=[output],
			)
			self.assertEqual([source], files)

	def test_folder_skips_target_extension_but_explicit_file_is_kept(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "source.wave"
			source.write_bytes(b"wave audio")
			existing_target = root / "existing.mp3"
			existing_target.write_bytes(b"mp3 audio")

			files, ignored = collect_audio_files(
				[root],
				folder_excluded_extensions=(".mp3",),
			)
			self.assertEqual([source], files)
			self.assertEqual(1, ignored)

			files, ignored = collect_audio_files(
				[root, existing_target],
				folder_excluded_extensions=("mp3",),
			)
			self.assertEqual({source, existing_target}, set(files))
			self.assertEqual(0, ignored)

	def test_detailed_collection_records_skip_reasons(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "source.wav"
			source.write_bytes(b"wav")
			target = root / "existing.mp3"
			target.write_bytes(b"mp3")
			unsupported = root / "notes.txt"
			unsupported.write_text("text", encoding="utf-8")
			files, ignored, skipped = collect_audio_files_detailed(
				[root],
				folder_excluded_extensions=(".mp3",),
			)
			self.assertEqual([source], files)
			self.assertEqual(2, ignored)
			self.assertEqual(
				{
					(str(target), "targetFormat"),
					(str(unsupported), "unsupported"),
				},
				{(item.source_path, item.reason) for item in skipped},
			)


class OutputNamingTests(unittest.TestCase):
	def test_same_format_does_not_overwrite_source(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "track.mp3"
			source.write_bytes(b"source")
			output = make_unique_output_path(source, root, ".mp3")
			self.assertEqual("track - converted.mp3", output.name)

	def test_existing_destination_gets_number(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "track.wav"
			source.write_bytes(b"source")
			(root / "track.mp3").write_bytes(b"existing")
			output = make_unique_output_path(source, root, ".mp3")
			self.assertEqual("track (2).mp3", output.name)


if __name__ == "__main__":
	unittest.main()
