from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "globalPlugins" / "easyAudioConverter"
CONVERTER_MODULE = PACKAGE_ROOT / "converter.py"
PROFILES_MODULE = PACKAGE_ROOT / "profiles.py"


def _load_module():
	import importlib.util
	import sys
	import types

	package_name = "_easy_audio_converter_profile_tests"
	package = types.ModuleType(package_name)
	package.__path__ = [str(CONVERTER_MODULE.parent)]
	sys.modules[package_name] = package
	converter_spec = importlib.util.spec_from_file_location(
		f"{package_name}.converter",
		CONVERTER_MODULE,
	)
	converter = importlib.util.module_from_spec(converter_spec)
	sys.modules[converter_spec.name] = converter
	converter_spec.loader.exec_module(converter)
	profiles_spec = importlib.util.spec_from_file_location(
		f"{package_name}.profiles",
		PROFILES_MODULE,
	)
	profiles = importlib.util.module_from_spec(profiles_spec)
	sys.modules[profiles_spec.name] = profiles
	profiles_spec.loader.exec_module(profiles)
	return converter, profiles


converter, profiles = _load_module()


class ProfileSerializationTests(unittest.TestCase):
	def test_complete_settings_round_trip(self):
		settings = converter.ConversionSettings(
			target_format="opus",
			quality="veryHigh",
			mp3_encoder="fraunhofer",
			same_folder=False,
			output_folder=r"D:\Converted",
			include_subfolders=False,
			preserve_folder_structure=False,
			metadata_mode="selected",
			metadata_fields=("title", "artist", "comment"),
			advanced_options={
				"enabled": True,
				"bitrate": 96,
				"sampleRate": 48000,
				"channels": 1,
				"codecLevel": 10,
				"bitDepth": 24,
			},
		)
		named = profiles.NamedConversionProfile("  Podcast   mono  ", settings)
		payload = profiles.dump_user_profiles([named])
		loaded = profiles.load_user_profiles(payload)
		self.assertEqual(1, len(loaded))
		self.assertEqual("Podcast mono", loaded[0].name)
		self.assertEqual(settings, loaded[0].settings)

	def test_invalid_values_fall_back_and_advanced_values_are_bounded(self):
		fallback = converter.ConversionSettings(
			target_format="flac",
			quality="high",
			same_folder=True,
			output_folder=r"D:\Audio",
		)
		settings = profiles.conversion_settings_from_mapping(
			{
				"targetFormat": "invalid",
				"quality": "invalid",
				"sameFolder": "false",
				"metadataFields": ["title", "invalid"],
				"advancedOptions": {
					"enabled": True,
					"bitrate": 99999,
					"sampleRate": 12345,
					"channels": 9,
					"codecLevel": 99,
					"bitDepth": 12,
				},
			},
			fallback=fallback,
		)
		self.assertEqual("flac", settings.target_format)
		self.assertEqual("high", settings.quality)
		self.assertTrue(settings.same_folder)
		self.assertEqual(("title",), settings.metadata_fields)
		self.assertEqual(
			{
				"enabled": True,
				"bitrate": 1536,
				"sampleRate": 0,
				"channels": 0,
				"codecLevel": 12,
				"bitDepth": 0,
			},
			settings.advanced_options,
		)

	def test_upsert_replaces_case_insensitively_and_remove_matches(self):
		first = profiles.NamedConversionProfile(
			"Speech",
			converter.ConversionSettings(target_format="mp3"),
		)
		replacement = profiles.NamedConversionProfile(
			"speech",
			converter.ConversionSettings(target_format="opus"),
		)
		result = profiles.upsert_user_profile([first], replacement)
		self.assertEqual(1, len(result))
		self.assertEqual("opus", result[0].settings.target_format)
		self.assertEqual([], profiles.remove_user_profile(result, "SPEECH"))

	def test_unknown_schema_and_duplicate_names_are_ignored(self):
		self.assertEqual([], profiles.load_user_profiles('{"version":99,"profiles":[]}'))
		payload = (
			'{"version":1,"profiles":['
			'"invalid",'
			'{"name":"Music","settings":{"targetFormat":"flac"}},'
			'{"name":"music","settings":{"targetFormat":"mp3"}}]}'
		)
		loaded = profiles.load_user_profiles(payload)
		self.assertEqual(1, len(loaded))
		self.assertEqual("flac", loaded[0].settings.target_format)


if __name__ == "__main__":
	unittest.main()
