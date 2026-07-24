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
	build_codec_arguments,
	collect_audio_files,
	make_unique_output_path,
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
