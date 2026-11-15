# Copyright (C) 2026 Kazimierz Parzych
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rzeczywiste kodowanie i kontrola parametrów ramek na sztucznym nagraniu."""

from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "globalPlugins" / "easyAudioConverter"))
from converter import ConversionSettings, Converter, build_codec_arguments  # noqa: E402
from gogo import build_gogo_command  # noqa: E402
from codec_options import MP3_MPEG1_RATES  # noqa: E402

FFMPEG = ROOT / "src/globalPlugins/easyAudioConverter/bin/ffmpeg.exe"


def run(command: list[str]) -> bytes:
	process = subprocess.run(
		command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
		stderr=subprocess.PIPE, timeout=45,
		creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
	)
	if process.returncode:
		raise AssertionError(process.stderr.decode("utf-8", errors="replace"))
	return process.stdout


def make_source(path: Path) -> None:
	"""Cisza, ton, wieloton i szum; brak danych ani nagrań użytkownika."""
	rng = random.Random(20261115)
	frames = bytearray()
	for n in range(44100 * 8):
		part = n // 44100
		time = n / 44100
		if part < 2:
			value = 0
		elif part < 4:
			value = int(12000 * math.sin(2 * math.pi * 997 * time))
		elif part < 6:
			value = int(sum(2200 * math.sin(2 * math.pi * f * time) for f in (61, 397, 997, 5071, 13691)))
		else:
			value = rng.randint(-18000, 18000)
		frames.extend(struct.pack("<hh", value, value))
	with wave.open(str(path), "wb") as stream:
		stream.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
		stream.writeframes(frames)


def mp3_frames(path: Path) -> list[dict[str, int]]:
	data = path.read_bytes()
	position = 0
	if data.startswith(b"ID3"):
		position = 10 + sum((data[6 + i] & 127) << (7 * (3 - i)) for i in range(4))
	frames = []
	while position + 4 <= len(data):
		header = int.from_bytes(data[position:position + 4], "big")
		version = (header >> 19) & 3
		layer = (header >> 17) & 3
		index = (header >> 12) & 15
		sampling = (header >> 10) & 3
		if header >> 21 != 2047 or version == 1 or layer != 1 or index in (0, 15) or sampling == 3:
			position += 1
			continue
		rates = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320) if version == 3 else (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
		sample_rate = (44100, 48000, 32000)[sampling] // (1 if version == 3 else 2 if version == 2 else 4)
		size = (144000 if version == 3 else 72000) * rates[index] // sample_rate + ((header >> 9) & 1)
		frame = data[position:position + size]
		if len(frame) != size:
			break
		if b"Xing" not in frame[:150] and b"Info" not in frame[:150]:
			frames.append({
				"bitrate": rates[index], "copyright": (header >> 3) & 1,
				"original": (header >> 2) & 1, "crc": 1 - ((header >> 16) & 1),
				"sampleRate": sample_rate,
			})
		position += size
	assert len(frames) > 50, "Nie rozpoznano ramek MP3."
	return frames


def ogg_packets(path: Path) -> list[bytes]:
	data, position, partial, packets = path.read_bytes(), 0, bytearray(), []
	while position < len(data):
		assert data[position:position + 4] == b"OggS"
		segments = data[position + 26]
		lacing = data[position + 27:position + 27 + segments]
		position += 27 + segments
		for size in lacing:
			partial.extend(data[position:position + size])
			position += size
			if size < 255:
				packets.append(bytes(partial))
				partial.clear()
	return packets


def dolby_flags(path: Path, target: str) -> tuple[int, int]:
	"""Odczyt flag pierwszej niezależnej ramki stereo z próbki testowej."""
	data, position = path.read_bytes(), 0

	def read(count: int) -> int:
		nonlocal position
		value = 0
		for _ in range(count):
			value = (value << 1) | ((data[position // 8] >> (7 - position % 8)) & 1)
			position += 1
		return value

	assert read(16) == 0x0B77
	if target == "ac3":
		read(16 + 2 + 6 + 5 + 3)
		assert read(3) == 2  # Próbka stereo, nie parser dowolnego układu kanałów.
		read(2 + 1 + 5)
		if read(1):
			read(8)
		if read(1):
			read(8)
		if read(1):
			read(7)
	else:
		assert read(2) == 0
		read(3 + 11)
		fscod = read(2)
		read(2)
		assert fscod != 3
		assert read(3) == 2
		read(1 + 5 + 5)
		if read(1):
			read(8)
		assert read(1) == 0, "Próbka niespodziewanie zawiera metadane miksowania."
		assert read(1) == 1, "Brak metadanych informacyjnych E-AC-3."
		read(3)
	return read(1), read(1)


def main() -> None:
	with tempfile.TemporaryDirectory(prefix="kodeki-") as directory:
		root = Path(directory)
		source = root / "próba.wav"
		make_source(source)
		cases = []
		for encoder in ("lame", "gogo", "fraunhofer"):
			for mode in (("cbr",) if encoder == "fraunhofer" else ("cbr", "abr", "vbr")):
				options = {"enabled": True, "rateMode": mode, "bitrate": 160}
				if mode == "vbr":
					options["vbrQuality"] = 4
				if encoder == "gogo" and mode != "cbr":
					options.update(minBitrate=96, maxBitrate=192)
				if encoder == "lame":
					options.update(copyright=1, original=0)
				cases.append((f"mp3-{encoder}-{mode}", "mp3", encoder, options))
		for target, modes in (("ogg", ("vbr", "abr")), ("opus", ("cbr", "vbr", "cvbr")), ("aac", ("cbr", "vbr")), ("m4a", ("cbr", "vbr")), ("ac3", ("cbr",)), ("eac3", ("cbr",))):
			for mode in modes:
				options = {"enabled": True, "rateMode": mode, "bitrate": 160}
				if target == "ogg" and mode == "abr":
					options.update(minBitrate=96, maxBitrate=192)
				if target in ("ac3", "eac3"):
					options.update(copyright=1, original=0)
				cases.append((f"{target}-{mode}", target, "lame", options))
		for mode in ("vbr", "abr"):
			for low, high in ((96, 0), (0, 192), (0, 0)):
				cases.append((f"gogo-{mode}-{low}-{high}", "mp3", "gogo", {
					"enabled": True, "rateMode": mode, "bitrate": 160,
					"minBitrate": low, "maxBitrate": high,
				}))
		cases.append(("gogo-mono-22050", "mp3", "gogo", {
			"enabled": True, "rateMode": "vbr", "vbrQuality": 3,
			"sampleRate": 22050, "channels": 1, "codecLevel": 5,
			"minBitrate": 64, "maxBitrate": 160,
		}))
		for target in ("mp3", "ac3", "eac3"):
			cases.append((f"{target}-flagi-odwrotne", target, "lame", {
				"enabled": True, "rateMode": "cbr", "bitrate": 160,
				"copyright": 0, "original": 1,
			}))
		for quality in (0.1, 5):
			cases.append((f"aac-jakosc-{quality}", "aac", "lame", {
				"enabled": True, "rateMode": "vbr", "vbrQuality": quality,
			}))
		for encoder in ("lame", "gogo", "fraunhofer"):
			for bitrate in MP3_MPEG1_RATES:
				if encoder == "fraunhofer" and bitrate < 96:
					continue  # Osobna próba wykrycia cichej zamiany bitrate poniżej.
				cases.append((f"mp3-{encoder}-cbr-{bitrate}", "mp3", encoder, {
					"enabled": True, "rateMode": "cbr", "bitrate": bitrate,
					"sampleRate": 44100,
					**({"copyright": 1, "original": 0} if encoder == "lame" else {}),
				}))
		for name, target, encoder, options in cases:
			output = root / f"{name}.{target}"
			if encoder == "gogo":
				command = build_gogo_command("", source, output, advanced_options=options)
			else:
				command = [str(FFMPEG), "-nostdin", "-v", "error", "-i", str(source), *build_codec_arguments(target, "high", encoder, options), str(output)]
			run(command)
			run([str(FFMPEG), "-nostdin", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"])
			result = {"próba": name, "bajty": output.stat().st_size}
			if target == "mp3":
				frames = mp3_frames(output)
				result["bitrate_ramek"] = dict(sorted(Counter(f["bitrate"] for f in frames).items()))
				result["flagi"] = sorted({(f["copyright"], f["original"], f["crc"]) for f in frames})
				if options["rateMode"] == "cbr":
					assert {f["bitrate"] for f in frames} == {options["bitrate"]}, result
				else:
					assert len({f["bitrate"] for f in frames}) > 1, result
				if encoder == "lame":
					assert {(f["copyright"], f["original"]) for f in frames} == {(options["copyright"], options["original"])}, result
				if encoder == "gogo" and options.get("maxBitrate"):
					assert max(f["bitrate"] for f in frames) <= options["maxBitrate"], result
				if encoder == "gogo" and options.get("minBitrate") and options["rateMode"] == "abr":
					assert min(f["bitrate"] for f in frames) >= options["minBitrate"], result
				if options.get("sampleRate"):
					assert {f["sampleRate"] for f in frames} == {options["sampleRate"]}, result
			if target == "opus":
				sizes = {len(packet) for packet in ogg_packets(output)[2:]}
				assert (len(sizes) == 1) == (options["rateMode"] == "cbr"), sizes
				result["rozmiary_pakietów"] = [min(sizes), max(sizes)]
			if target == "ogg" and options["rateMode"] == "abr":
				header = ogg_packets(output)[0]
				assert header.startswith(b"\x01vorbis")
				assert struct.unpack_from("<iii", header, 16) == (192000, 160000, 96000)
			if target in ("ac3", "eac3"):
				flags = dolby_flags(output, target)
				assert flags == (options["copyright"], options["original"]), flags
				result["flagi"] = flags
			print(json.dumps(result, ensure_ascii=False), flush=True)
		for encoder in ("lame", "gogo", "fraunhofer"):
			options = {"enabled": True, "rateMode": "vbr", "vbrQuality": 4}
			if encoder == "gogo":
				options.update(minBitrate=96, maxBitrate=192)
			elif encoder == "lame":
				options.update(copyright=1, original=0)
			else:
				options = {"enabled": True, "rateMode": "cbr", "bitrate": 160}
			settings = ConversionSettings(
				mp3_encoder=encoder, advanced_options=options, parallel_jobs=1,
				same_folder=False, output_folder=str(root / f"silnik-{encoder}"),
				show_preflight=False, verify_output=True,
			)
			summary = Converter(FFMPEG).run([source], settings)
			assert summary.succeeded == 1 and summary.failed == 0, summary
			frames = mp3_frames(Path(summary.outputs[0]))
			assert (len({f["bitrate"] for f in frames}) > 1) == (encoder != "fraunhofer")
			if encoder == "gogo":
				assert max(f["bitrate"] for f in frames) <= 192
			elif encoder == "lame":
				assert {(f["copyright"], f["original"]) for f in frames} == {(1, 0)}
			else:
				assert {f["bitrate"] for f in frames} == {160}
			print(f"Pełna ścieżka konwersji {encoder}: poprawna.")
		settings = ConversionSettings(
			mp3_encoder="fraunhofer", parallel_jobs=1, same_folder=False,
			output_folder=str(root / "mf-niezgodny-bitrate"), replace_source_files=True,
			advanced_options={"enabled": True, "rateMode": "cbr", "bitrate": 32, "sampleRate": 44100, "channels": 2},
		)
		summary = Converter(FFMPEG).run([source], settings)
		assert summary.failed == 1 and summary.succeeded == 0, summary
		assert source.is_file() and not list((root / "mf-niezgodny-bitrate").glob("*.mp3"))
		assert "96 kb/s" in summary.failures[0].message, summary.failures
		print("Media Foundation: wykryto 32 → 96 kb/s; źródło zachowane, błędny wynik usunięty.")
		print(f"Sprawdzono {len(cases) + 4} rzeczywistych konwersji (w tym oczekiwane odrzucenie niezgodnego CBR).")


if __name__ == "__main__":
	main()
