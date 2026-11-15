# Copyright (C) 2026 Kazimierz Parzych
# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy trybów kodeków bez NVDA i bez uruchamiania pulpitu."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/globalPlugins/easyAudioConverter"))
from codec_options import apply_rate_arguments, codec_capabilities, get_codec_profile, validate_rate_options
from converter import ConversionSettings, build_codec_arguments, _estimated_output_size
from gogo import gogo_codec_arguments


class CodecOptionsTests(unittest.TestCase):
	def test_lame_modes_and_flags(self):
		for mode in ("cbr", "abr", "vbr"):
			with self.subTest(mode=mode):
				args = build_codec_arguments("mp3", "high", "lame", {
					"enabled": True, "rateMode": mode, "bitrate": 192,
					"copyright": 1, "original": 0, "codecLevel": 7,
				})
				self.assertEqual(str(int(mode == "abr")), args[args.index("-abr") + 1])
				self.assertEqual(mode == "vbr", "-q:a" in args)
				self.assertEqual(mode != "vbr", "-b:a" in args)
				self.assertEqual("7", args[args.index("-compression_level") + 1])
				self.assertEqual("1", args[args.index("-copyright") + 1])
				self.assertEqual("0", args[args.index("-original") + 1])

	def test_vorbis_abr_removes_all_quality_overrides(self):
		args = build_codec_arguments("ogg", "high", "lame", {
			"enabled": True, "rateMode": "abr", "codecLevel": 8,
			"bitrate": 160, "minBitrate": 96, "maxBitrate": 192,
		})
		self.assertNotIn("-q:a", args)
		self.assertEqual("160k", args[args.index("-b:a") + 1])
		self.assertEqual("96k", args[args.index("-minrate:a") + 1])
		self.assertEqual("192k", args[args.index("-maxrate:a") + 1])

	def test_vorbis_abr_default_bitrate_is_also_validated(self):
		with self.assertRaises(ValueError):
			ConversionSettings(target_format="ogg", quality="high", advanced_options={
				"enabled": True, "rateMode": "abr", "maxBitrate": 128,
			}).validate()

	def test_aac_quality_removes_bitrate(self):
		for target in ("aac", "m4a"):
			args = build_codec_arguments(target, "high", "lame", {
				"enabled": True, "rateMode": "vbr", "vbrQuality": 1.5,
			})
			self.assertNotIn("-b:a", args)
			self.assertEqual("1.5", args[args.index("-q:a") + 1])

	def test_opus_modes_keep_target_bitrate(self):
		for mode, expected in (("cbr", "off"), ("vbr", "on"), ("cvbr", "constrained")):
			args = build_codec_arguments("opus", "high", "lame", {"enabled": True, "rateMode": mode, "bitrate": 96})
			self.assertEqual(expected, args[args.index("-vbr") + 1])
			self.assertEqual("96k", args[args.index("-b:a") + 1])

	def test_invalid_or_unsupported_options_are_rejected(self):
		cases = [
			("mp3", "fraunhofer", {"rateMode": "vbr"}),
			("mp3", "lame", {"rateMode": "vbr", "minBitrate": 96}),
			("mp3", "gogo", {"copyright": 1}),
			("mp3", "lame", {"crc": 1}),
			("mp3", "lame", {"rateMode": "cbr", "bitrate": 123}),
			("mp3", "lame", {"rateMode": "cbr", "bitrate": 144, "sampleRate": 44100}),
			("mp3", "gogo", {"rateMode": "vbr", "vbrQuality": 2.5}),
			("mp3", "gogo", {"rateMode": "vbr", "minBitrate": 192, "maxBitrate": 96}),
			("mp3", "gogo", {"rateMode": "abr", "bitrate": 64, "minBitrate": 96}),
			("mp3", "gogo", {"rateMode": "vbr", "maxBitrate": 200}),
			("mp3", "gogo", {"sampleRate": 96000}),
			("mp3", "gogo", {"codecLevel": 12}),
			("ogg", "lame", {"rateMode": "vbr", "maxBitrate": 192}),
			("opus", "lame", {"rateMode": "vbr", "vbrQuality": 2}),
			("flac", "lame", {"rateMode": "cbr"}),
			("aac", "lame", {"rateMode": "vbr", "vbrQuality": 0}),
			("aac", "lame", {"rateMode": "vbr", "vbrQuality": float("nan")}),
			("aac", "lame", {"rateMode": "vbr", "vbrQuality": float("inf")}),
			("aac", "lame", {"rateMode": "vbr", "vbrQuality": True}),
			("aac", "lame", {"rateMode": "vbr", "vbrQuality": "2"}),
			("aac", "lame", {"minBitrate": "96"}),
			("aac", "lame", {"original": 2}),
			("aac", "lame", {"rateMode": 1}),
		]
		for target, encoder, values in cases:
			with self.subTest(target=target, encoder=encoder, values=values):
				with self.assertRaises(ValueError):
					validate_rate_options(target, encoder, dict(enabled=True, **values))

	def test_gogo_modes_and_standard_override(self):
		args = gogo_codec_arguments(128, 0, "-silent", {
			"enabled": True, "rateMode": "abr", "bitrate": 128,
			"minBitrate": 96, "maxBitrate": 160, "sampleRate": 22050,
			"codecLevel": 3, "channels": 1,
		})
		self.assertIn("-a", args)
		self.assertEqual("128", args[args.index("-b") + 1])
		self.assertEqual(["96", "160"], args[args.index("-vb") + 1:args.index("-vb") + 3])
		self.assertEqual("22.05", args[args.index("-d") + 1])
		self.assertEqual("m", args[args.index("-m") + 1])
		self.assertEqual(1, args.count("-m"))
		self.assertEqual("3", args[args.index("-q") + 1])
		vbr = gogo_codec_arguments(256, 0, "", {"enabled": True, "rateMode": "vbr", "vbrQuality": 4})
		self.assertIn("-v", vbr)
		self.assertNotIn("-b", vbr)

	def test_gogo_rejects_conflicting_manual_arguments(self):
		for extra in ("-a", "-b 128", "-v 3", "-vb 96 192"):
			with self.subTest(extra=extra), self.assertRaises(ValueError):
				gogo_codec_arguments(0, 0, extra, {"enabled": True, "rateMode": "vbr"})
		self.assertEqual(["-q", "0"], gogo_codec_arguments(0, 0, "-v 3", {"enabled": True}))

	def test_disabled_and_legacy_profiles_keep_existing_behavior(self):
		for target in ("mp3", "ogg", "opus", "flac", "wavpack"):
			base = build_codec_arguments(target, "high", "lame")
			self.assertEqual(base, build_codec_arguments(target, "high", "lame", {"enabled": True}))
			self.assertEqual(base, apply_rate_arguments(base, target, "lame", {"enabled": False, "rateMode": "invalid"}))

	def test_mp3_profiles_are_separate_and_legacy_gogo_is_ignored(self):
		profiles = {"mp3": {"bitrate": 192}, "mp3:lame": {"bitrate": 128}}
		self.assertEqual({"bitrate": 128}, get_codec_profile(profiles, "mp3", "lame"))
		self.assertEqual({"bitrate": 192}, get_codec_profile(profiles, "mp3", "fraunhofer"))
		self.assertEqual({}, get_codec_profile(profiles, "mp3", "gogo"))

	def test_gogo_vbr_does_not_estimate_size_as_cbr(self):
		settings = ConversionSettings(mp3_encoder="gogo", gogo_bitrate=128, advanced_options={"enabled": True, "rateMode": "vbr"})
		self.assertIsNone(_estimated_output_size(1000, 10, settings))

	def test_copyright_flags_are_limited_to_supported_codecs(self):
		for target in ("ac3", "eac3", "mp3"):
			self.assertTrue(codec_capabilities(target).flags)
			args = build_codec_arguments(target, "high", "lame", {"enabled": True, "copyright": 0, "original": 1})
			self.assertEqual("0", args[args.index("-copyright") + 1])
			self.assertEqual("1", args[args.index("-original") + 1])


if __name__ == "__main__":
	unittest.main()
