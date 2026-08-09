from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "globalPlugins" / "easyAudioConverter"))

from converter import (  # noqa: E402
	AAC_M4A_COPY_FORMAT,
	FLAC_COMPRESSION_LEVELS,
	FORMAT_KEYS,
	MAX_PARALLEL_JOBS,
	ORIGINAL_AUDIO_COPY_FORMAT,
	PARALLEL_JOB_COUNTS,
	QUALITY_KEYS,
	STREAM_COPY_FORMATS,
	WAVPACK_COMPRESSION_PROFILES,
	ConversionSettings,
	ConversionCallbacks,
	Converter,
	MediaInfo,
	StreamCopySourceError,
	apply_advanced_codec_arguments,
	build_codec_arguments,
	build_loudnorm_filter,
	build_metadata_arguments,
	collect_audio_files,
	collect_audio_files_detailed,
	make_unique_output_path,
	output_extension_for,
	parse_duration,
	parse_ffmetadata,
	parse_loudnorm_measurement,
	parse_media_info,
	parse_progress_time,
	render_output_name,
	resolve_parallel_jobs,
	recommended_parallel_jobs,
	sanitize_windows_filename,
)


class ConversionSettingsTests(unittest.TestCase):
	def test_parallel_worker_count_is_validated_and_resolved(self):
		self.assertEqual(1, resolve_parallel_jobs(0, 1))
		self.assertEqual(2, resolve_parallel_jobs(2, 10))
		self.assertEqual(10, resolve_parallel_jobs(32, 10))
		self.assertEqual(MAX_PARALLEL_JOBS, PARALLEL_JOB_COUNTS[-1])
		with mock.patch("converter.os.cpu_count", return_value=8):
			self.assertEqual(4, recommended_parallel_jobs(20))
		with self.assertRaises(ValueError):
			ConversionSettings(parallel_jobs=MAX_PARALLEL_JOBS + 1).validate()

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
		with self.assertRaises(ValueError):
			ConversionSettings(output_name_template="{unknown}").validate()
		with self.assertRaises(ValueError):
			ConversionSettings(loudness_preset="invalid").validate()

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

	def test_lossless_compression_levels_are_bounded_and_applied(self):
		self.assertEqual(tuple(range(13)), FLAC_COMPRESSION_LEVELS)
		self.assertEqual(
			(
				(0, "-f"),
				(1, ""),
				(2, "-h"),
				(3, "-hh"),
				(4, "-hhx1"),
				(5, "-hhx2"),
				(6, "-hhx3"),
				(7, "-hhx4"),
				(8, "-hhx6"),
			),
			tuple((level, command) for level, _name, command in WAVPACK_COMPRESSION_PROFILES),
		)
		for target_format, requested, expected in (
			("flac", 0, 0),
			("flac", 12, 12),
			("flac", 99, 12),
			("wavpack", 0, 0),
			("wavpack", 7, 7),
			("wavpack", 8, 8),
			("wavpack", 99, 8),
		):
			with self.subTest(target_format=target_format, requested=requested):
				arguments = build_codec_arguments(
					target_format,
					"high",
					"lame",
					{"enabled": True, "codecLevel": requested},
				)
				self.assertEqual(
					str(expected),
					arguments[arguments.index("-compression_level") + 1],
				)

	def test_stream_copy_never_applies_encoder_overrides(self):
		for target_format in STREAM_COPY_FORMATS:
			with self.subTest(target_format=target_format):
				arguments = build_codec_arguments(
					target_format,
					"veryHigh",
					"fraunhofer",
					{
						"enabled": True,
						"bitrate": 512,
						"sampleRate": 16000,
						"channels": 1,
						"codecLevel": 9,
						"bitDepth": 24,
					},
				)
				self.assertEqual(["-c:a", "copy"], arguments)


class StreamCopyFormatTests(unittest.TestCase):
	def test_original_stream_extension_follows_the_audio_codec(self):
		self.assertEqual(".aac", output_extension_for(ORIGINAL_AUDIO_COPY_FORMAT, "aac"))
		self.assertEqual(".mp3", output_extension_for(ORIGINAL_AUDIO_COPY_FORMAT, "mp3"))
		self.assertEqual(".opus", output_extension_for(ORIGINAL_AUDIO_COPY_FORMAT, "opus"))
		self.assertEqual(".aiff", output_extension_for(ORIGINAL_AUDIO_COPY_FORMAT, "pcm_s24be"))
		self.assertEqual(".wav", output_extension_for(ORIGINAL_AUDIO_COPY_FORMAT, "pcm_s24le"))
		self.assertEqual(".mka", output_extension_for(ORIGINAL_AUDIO_COPY_FORMAT, "unknown_codec"))

	def test_aac_m4a_remux_rejects_other_codecs(self):
		self.assertEqual(".m4a", output_extension_for(AAC_M4A_COPY_FORMAT, "aac"))
		with self.assertRaises(StreamCopySourceError) as context:
			output_extension_for(AAC_M4A_COPY_FORMAT, "mp3")
		self.assertEqual("requiresAac", context.exception.reason)
		with self.assertRaises(StreamCopySourceError) as context:
			output_extension_for(AAC_M4A_COPY_FORMAT, "")
		self.assertEqual("noAudioStream", context.exception.reason)


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


class MediaInfoTests(unittest.TestCase):
	def test_media_info_parser_reports_audio_properties(self):
		info = parse_media_info(
			"Input #0, mp3, from 'song.mp3':\n"
			"  Duration: 00:03:02.50, start: 0.0, bitrate: 193 kb/s\n"
			"  Chapter #0:0: start 0.000000, end 60.000000\n"
			"  Stream #0:0: Audio: mp3, 48000 Hz, stereo, fltp, 192 kb/s\n"
			"  Stream #0:1: Video: mjpeg (attached pic)\n",
			source_path="song.mp3",
			size_bytes=123,
			metadata={"artist": "Artist"},
		)
		self.assertEqual("mp3", info.container)
		self.assertEqual("mp3", info.codec)
		self.assertEqual(182.5, info.duration)
		self.assertEqual(192, info.bitrate_kbps)
		self.assertEqual(48000, info.sample_rate)
		self.assertEqual("stereo", info.channels)
		self.assertTrue(info.has_artwork)
		self.assertEqual(1, info.chapter_count)

	def test_two_pass_loudness_filter_uses_measurements(self):
		settings = ConversionSettings(loudness_preset="podcast")
		first_pass = build_loudnorm_filter(settings)
		self.assertIn("I=-16", first_pass)
		self.assertIn("print_format=json", first_pass)
		measurement = parse_loudnorm_measurement(
			'[Parsed_loudnorm_0]\n{\n'
			' "input_i" : "-20.10",\n'
			' "input_tp" : "-2.30",\n'
			' "input_lra" : "4.20",\n'
			' "input_thresh" : "-30.00",\n'
			' "target_offset" : "0.10"\n'
			"}\n"
		)
		second_pass = build_loudnorm_filter(settings, measurement)
		self.assertIn("measured_I=-20.1", second_pass)
		self.assertIn("linear=true", second_pass)

	def test_artwork_mapping_is_limited_to_compatible_targets(self):
		mp3 = Converter._stream_mapping_arguments(
			ConversionSettings(target_format="mp3", copy_artwork=True),
			has_artwork=True,
		)
		self.assertIn("0:v:disp:attached_pic?", mp3)
		wav = Converter._stream_mapping_arguments(
			ConversionSettings(target_format="wav", copy_artwork=True),
			has_artwork=True,
		)
		self.assertIn("-vn", wav)


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

	def test_metadata_template_is_rendered_and_sanitized(self):
		name = render_output_name(
			"{artist} - {title}",
			Path("source.wav"),
			"mp3",
			{"artist": "AC/DC", "title": "A:Song?"},
		)
		self.assertEqual("AC_DC - A_Song_", name)

	def test_windows_reserved_names_and_traversal_are_safe(self):
		self.assertEqual("_CON", sanitize_windows_filename("CON"))
		self.assertEqual("_COM1.notes", sanitize_windows_filename("COM1.notes"))
		self.assertNotIn("\\", sanitize_windows_filename("..\\outside"))


class _FakeConverter(Converter):
	def __init__(self, ffmpeg_path, *, codec="", bitrate_kbps=None):
		super().__init__(ffmpeg_path)
		self.codec = codec
		self.bitrate_kbps = bitrate_kbps
		self.commands = []

	def _require_ffmpeg(self):
		pass

	def _probe_media_info(self, source, *, include_metadata):
		return MediaInfo(
			source_path=str(source),
			codec=self.codec,
			duration=10.0,
			bitrate_kbps=self.bitrate_kbps,
			size_bytes=source.stat().st_size,
			metadata={"artist": "Artist", "title": source.stem},
		)

	def _run_process(self, command, on_progress=None):
		self.commands.append(list(command))
		output = Path(command[-1])
		output.write_bytes(b"converted")
		if on_progress is not None:
			on_progress(10.0)
		return 0, ""


class _ParallelFakeConverter(_FakeConverter):
	_active = 0
	_max_active = 0
	_active_lock = threading.Lock()

	@classmethod
	def reset_activity(cls):
		with cls._active_lock:
			cls._active = 0
			cls._max_active = 0

	def _run_process(self, command, on_progress=None):
		with self._active_lock:
			type(self)._active += 1
			type(self)._max_active = max(type(self)._max_active, type(self)._active)
		try:
			time.sleep(0.04)
			output = Path(command[-1])
			output.write_bytes(b"converted")
			if on_progress is not None:
				on_progress(10.0)
			return 0, ""
		finally:
			with self._active_lock:
				type(self)._active -= 1


class ConversionPlanningTests(unittest.TestCase):
	def test_multiple_files_use_bounded_parallel_workers(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			sources = []
			for index in range(4):
				source = root / f"source-{index}.wav"
				source.write_bytes(b"source")
				sources.append(source)
			_ParallelFakeConverter.reset_activity()
			converter = _ParallelFakeConverter(root / "missing.exe")
			summary = converter.run(
				sources,
				ConversionSettings(
					target_format="mp3",
					same_folder=False,
					output_folder=str(root / "out"),
					parallel_jobs=2,
				),
			)
			self.assertEqual(4, summary.succeeded)
			self.assertEqual(2, _ParallelFakeConverter._max_active)

	def test_plan_contains_actual_names_sizes_and_lossy_warning(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "source.mp3"
			source.write_bytes(b"x" * 100)
			settings = ConversionSettings(
				target_format="opus",
				same_folder=False,
				output_folder=str(root / "out"),
				output_name_template="{artist} - {title}",
			)
			plan = _FakeConverter(root / "missing.exe").create_plan([source], settings)
			self.assertEqual(1, plan.total)
			self.assertEqual(100, plan.input_bytes)
			self.assertEqual(1, plan.lossy_to_lossy_count)
			self.assertEqual("Artist - source.opus", Path(plan.items[0].output_path).name)
			self.assertGreater(plan.estimated_output_bytes, 0)

	def test_plan_records_source_replacement_policy(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "source.wav"
			source.write_bytes(b"source")
			plan = _FakeConverter(root / "missing.exe").create_plan(
				[source],
				ConversionSettings(
					target_format="mp3",
					replace_source_files=True,
				),
			)
			self.assertTrue(plan.replace_source_files)

	def test_original_stream_plan_uses_codec_suffix_and_audio_bitrate(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "video.mp4"
			source.write_bytes(b"x" * 2_000_000)
			converter = _FakeConverter(
				root / "missing.exe",
				codec="aac",
				bitrate_kbps=128,
			)
			plan = converter.create_plan(
				[source],
				ConversionSettings(
					target_format=ORIGINAL_AUDIO_COPY_FORMAT,
					same_folder=False,
					output_folder=str(root / "out"),
				),
			)
			self.assertEqual("video.aac", Path(plan.items[0].output_path).name)
			self.assertLess(plan.items[0].estimated_output_size, source.stat().st_size)
			self.assertEqual(163_200, plan.items[0].estimated_output_size)
			self.assertEqual(0, plan.lossy_to_lossy_count)

	def test_aac_m4a_plan_skips_a_non_aac_source(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "video.mkv"
			source.write_bytes(b"video")
			plan = _FakeConverter(
				root / "missing.exe",
				codec="mp3",
				bitrate_kbps=192,
			).create_plan(
				[source],
				ConversionSettings(
					target_format=AAC_M4A_COPY_FORMAT,
					same_folder=False,
					output_folder=str(root / "out"),
				),
			)
			self.assertEqual(0, plan.total)
			self.assertEqual(1, plan.ignored)
			self.assertEqual("requiresAac", plan.skipped_files[0].reason)

	def test_original_stream_command_copies_only_audio_without_filters(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "video.mp4"
			source.write_bytes(b"video")
			converter = _FakeConverter(
				root / "missing.exe",
				codec="aac",
				bitrate_kbps=128,
			)
			summary = converter.run(
				[source],
				ConversionSettings(
					target_format=ORIGINAL_AUDIO_COPY_FORMAT,
					same_folder=False,
					output_folder=str(root / "out"),
					metadata_mode="all",
					loudness_preset="podcast",
					copy_artwork=True,
					copy_chapters=True,
					advanced_options={
						"enabled": True,
						"bitrate": 64,
						"sampleRate": 16000,
						"channels": 1,
					},
				),
			)
			self.assertEqual(1, summary.succeeded)
			self.assertEqual(".aac", Path(summary.outputs[0]).suffix)
			command = converter.commands[0]
			self.assertEqual("copy", command[command.index("-c:a") + 1])
			self.assertIn("0:a:0", command)
			self.assertNotIn("0:a:0?", command)
			self.assertIn("-vn", command)
			self.assertNotIn("-af", command)
			self.assertEqual("0", command[command.index("-threads") + 1])
			self.assertNotIn("-ar", command)
			self.assertNotIn("-ac", command)
			self.assertEqual("-1", command[command.index("-map_metadata") + 1])
			self.assertEqual("-1", command[command.index("-map_chapters") + 1])

	def test_conversion_preserves_source_creation_and_modification_dates(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			for index, target_format in enumerate(
				("mp3", ORIGINAL_AUDIO_COPY_FORMAT, AAC_M4A_COPY_FORMAT),
				start=1,
			):
				with self.subTest(target_format=target_format):
					case_root = root / target_format
					case_root.mkdir()
					source = case_root / "source.mp4"
					source.write_bytes(b"source")
					source_access_ns = source.stat().st_atime_ns
					source_modification_ns = 1_600_000_000_123_456_700 + index * 100
					os.utime(
						source,
						ns=(source_access_ns, source_modification_ns),
					)
					source_stat = source.stat()
					source_creation_ns = getattr(
						source_stat,
						"st_birthtime_ns",
						source_stat.st_ctime_ns,
					)
					time.sleep(0.02)
					converter = _FakeConverter(case_root / "missing.exe", codec="aac")
					summary = converter.run(
						[source],
						ConversionSettings(
							target_format=target_format,
							same_folder=False,
							output_folder=str(case_root / "out"),
							preserve_timestamps=True,
						),
					)
					self.assertEqual(1, summary.succeeded)
					output_stat = Path(summary.outputs[0]).stat()
					self.assertEqual(source_stat.st_mtime_ns, output_stat.st_mtime_ns)
					if os.name == "nt":
						output_creation_ns = getattr(
							output_stat,
							"st_birthtime_ns",
							output_stat.st_ctime_ns,
						)
						self.assertEqual(source_creation_ns, output_creation_ns)

	def test_successful_conversion_removes_source_when_replacement_is_enabled(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "source.wav"
			source.write_bytes(b"source")
			summary = _FakeConverter(root / "missing.exe").run(
				[source],
				ConversionSettings(
					target_format="mp3",
					same_folder=False,
					output_folder=str(root / "out"),
					replace_source_files=True,
				),
			)
			self.assertEqual(1, summary.succeeded)
			self.assertFalse(source.exists())
			self.assertTrue(Path(summary.outputs[0]).is_file())

	def test_failed_ffmpeg_keeps_source_when_replacement_is_enabled(self):
		class FailingConverter(_FakeConverter):
			def _run_process(self, command, on_progress=None):
				output = Path(command[-1])
				output.write_bytes(b"partial")
				return 1, "Conversion failed"

		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "source.wav"
			source.write_bytes(b"source")
			summary = FailingConverter(root / "missing.exe").run(
				[source],
				ConversionSettings(
					target_format="mp3",
					same_folder=False,
					output_folder=str(root / "out"),
					replace_source_files=True,
				),
			)
			self.assertEqual(1, summary.failed)
			self.assertTrue(source.is_file())
			self.assertEqual([], list((root / "out").glob("*")))

	def test_failed_verification_keeps_source_when_replacement_is_enabled(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "source.wav"
			source.write_bytes(b"source")
			converter = _FakeConverter(root / "missing.exe")
			converter._verify_output = lambda *args, **kwargs: (
				False,
				"Output verification failed",
			)
			summary = converter.run(
				[source],
				ConversionSettings(
					target_format="mp3",
					same_folder=False,
					output_folder=str(root / "out"),
					replace_source_files=True,
					verify_output=True,
				),
			)
			self.assertEqual(1, summary.failed)
			self.assertTrue(source.is_file())
			self.assertEqual([], list((root / "out").glob("*")))

	def test_canceled_conversion_keeps_source_when_replacement_is_enabled(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "source.wav"
			source.write_bytes(b"source")
			converter = _FakeConverter(root / "missing.exe")
			callbacks = ConversionCallbacks(
				on_progress=lambda *args: converter.cancel(),
			)
			summary = converter.run(
				[source],
				ConversionSettings(
					target_format="mp3",
					same_folder=False,
					output_folder=str(root / "out"),
					replace_source_files=True,
				),
				callbacks=callbacks,
			)
			self.assertTrue(summary.canceled)
			self.assertTrue(source.is_file())
			self.assertEqual([], list((root / "out").glob("*")))

	def test_source_removal_failure_keeps_completed_output(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / "source.wav"
			source.write_bytes(b"source")
			converter = _FakeConverter(root / "missing.exe")

			def fail_source_removal(_source):
				raise PermissionError("Access is denied")

			converter._remove_source_file = fail_source_removal
			summary = converter.run(
				[source],
				ConversionSettings(
					target_format="mp3",
					same_folder=False,
					output_folder=str(root / "out"),
					replace_source_files=True,
				),
			)
			self.assertEqual(0, summary.succeeded)
			self.assertEqual(1, summary.failed)
			self.assertTrue(source.is_file())
			self.assertEqual(1, len(summary.failures))
			kept_output = Path(summary.failures[0].output_path)
			self.assertTrue(kept_output.is_file())
			self.assertEqual(b"converted", kept_output.read_bytes())

	def test_stop_after_current_finishes_exactly_one_file(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			first = root / "first.wav"
			second = root / "second.wav"
			first.write_bytes(b"one")
			second.write_bytes(b"two")
			converter = _FakeConverter(root / "missing.exe")
			callbacks = ConversionCallbacks(
				on_file_start=lambda *args: converter.stop_after_current()
			)
			summary = converter.run(
				[first, second],
				ConversionSettings(
					target_format="mp3",
					same_folder=False,
					output_folder=str(root / "out"),
					parallel_jobs=1,
				),
				callbacks=callbacks,
			)
			self.assertEqual(2, summary.total)
			self.assertEqual(1, summary.succeeded)
			self.assertTrue(summary.stopped_after_current)
			self.assertFalse(summary.canceled)


if __name__ == "__main__":
	unittest.main()
