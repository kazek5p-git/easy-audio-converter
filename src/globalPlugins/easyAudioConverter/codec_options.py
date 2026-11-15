# Copyright (C) 2026 Kazimierz Parzych
# SPDX-License-Identifier: GPL-3.0-or-later
"""Możliwości i walidacja trybów przepływności dołączonych enkoderów."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


MP3_MPEG1_RATES = (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
MP3_MPEG2_RATES = (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
MP3_RATES = tuple(sorted(set(MP3_MPEG1_RATES + MP3_MPEG2_RATES)))
RATE_DEFAULTS = {
	"rateMode": "auto", "vbrQuality": -1.0,
	"minBitrate": 0, "maxBitrate": 0,
	"copyright": -1, "original": -1,
}


@dataclass(frozen=True)
class CodecCapabilities:
	modes: tuple[str, ...] = ("auto",)
	limit_modes: tuple[str, ...] = ()
	flags: bool = False
	quality_min: float = 0
	quality_max: float = 9
	quality_default: float = 2
	bitrate_max: int = 0


def codec_capabilities(target: str, encoder: str = "lame") -> CodecCapabilities:
	"""Opisuje faktyczny interfejs FFmpeg/GOGO, a nie cały standard formatu."""
	if target == "mp3":
		if encoder == "lame":
			return CodecCapabilities(("auto", "cbr", "abr", "vbr"), flags=True, bitrate_max=320)
		if encoder == "gogo":
			return CodecCapabilities(("auto", "cbr", "abr", "vbr"), ("vbr", "abr"), bitrate_max=320)
		return CodecCapabilities(("auto", "cbr"), bitrate_max=320)
	if target == "ogg":
		return CodecCapabilities(("auto", "vbr", "abr"), ("abr",), quality_max=10, quality_default=6, bitrate_max=512)
	if target == "opus":
		return CodecCapabilities(("auto", "cbr", "vbr", "cvbr"), bitrate_max=512)
	if target in {"aac", "m4a"}:
		return CodecCapabilities(("auto", "cbr", "vbr"), quality_min=0.1, quality_max=5, quality_default=2, bitrate_max=512)
	if target in {"ac3", "eac3"}:
		return CodecCapabilities(("auto", "cbr"), flags=True, bitrate_max=640 if target == "ac3" else 1536)
	limits = {"mp2": 384, "wma": 320, "amr": 13, "amrwb": 24}
	if target in limits:
		return CodecCapabilities(("auto", "cbr"), bitrate_max=limits[target])
	return CodecCapabilities()


def codec_profile_key(target: str, encoder: str = "lame") -> str:
	return f"mp3:{encoder}" if target == "mp3" else target


def get_codec_profile(profiles: Mapping[str, Any], target: str, encoder: str) -> dict[str, Any]:
	"""Czyta osobne profile MP3, z zachowaniem starych ustawień wersji 1.9."""
	key = codec_profile_key(target, encoder)
	if key in profiles:
		return dict(profiles[key])
	legacy = dict(profiles.get(target, {}))
	if target == "mp3" and encoder == "gogo":
		# Starsze wersje w ogóle nie stosowały profilu zaawansowanego do GOGO.
		return {}
	return legacy


def rate_options_from_mapping(raw: Mapping[str, Any]) -> dict[str, Any]:
	"""Zachowuje jawne wybory, odrzucając błędne typy zamiast zgadywania."""
	result = {key: raw.get(key, default) for key, default in RATE_DEFAULTS.items()}
	if not isinstance(result["rateMode"], str):
		raise ValueError("Nieprawidłowy tryb przepływności.")
	for key in ("minBitrate", "maxBitrate", "copyright", "original"):
		value = result[key]
		if type(value) is not int:
			raise ValueError("Granice przepływności i flagi muszą być liczbami całkowitymi.")
	for key in ("minBitrate", "maxBitrate"):
		if not 0 <= result[key] <= 1536:
			raise ValueError("Granica przepływności jest poza dozwolonym zakresem.")
	for key in ("copyright", "original"):
		if result[key] not in (-1, 0, 1):
			raise ValueError("Flaga wymaga wyboru: domyślnie, nie albo tak.")
	quality = result["vbrQuality"]
	if type(quality) not in (float, int) or not math.isfinite(quality):
		raise ValueError("Jakość VBR musi być skończoną liczbą.")
	result["vbrQuality"] = float(quality)
	return result


def validate_rate_options(target: str, encoder: str, options: Mapping[str, Any] | None) -> None:
	if options is not None and not isinstance(options, Mapping):
		raise ValueError("Ustawienia kodeka muszą być mapą wartości.")
	if not options or not options.get("enabled") or target in {"copyAudio", "aacM4a"}:
		return
	values = rate_options_from_mapping(options)
	caps = codec_capabilities(target, encoder)
	mode = values["rateMode"]
	if mode not in caps.modes:
		raise ValueError("Wybrany enkoder nie obsługuje tego trybu przepływności.")
	try:
		rate = int(options.get("bitrate", 0))
		sample_rate = int(options.get("sampleRate", 0))
	except (TypeError, ValueError, OverflowError) as error:
		raise ValueError("Przepływność i częstotliwość próbkowania muszą być liczbami.") from error
	if mode != "auto" and caps.bitrate_max and not 0 <= rate <= caps.bitrate_max:
		raise ValueError("Docelowa przepływność przekracza możliwości enkodera.")
	if target == "mp3" and mode == "cbr" and rate and rate not in MP3_RATES:
		raise ValueError("CBR MP3 wymaga przepływności zgodnej ze standardem MPEG.")
	if target == "mp3" and sample_rate:
		allowed = MP3_MPEG1_RATES if sample_rate >= 32000 else MP3_MPEG2_RATES
		if mode == "cbr" and rate and rate not in allowed:
			raise ValueError("Przepływność CBR MP3 nie jest zgodna z częstotliwością próbkowania.")
	if target == "mp3" and encoder == "gogo":
		if sample_rate not in (0, 16000, 22050, 24000, 32000, 44100, 48000):
			raise ValueError("GOGO obsługuje częstotliwości od 16000 do 48000 Hz.")
		if options.get("codecLevel", -1) not in range(-1, 10):
			raise ValueError("Jakość algorytmu GOGO musi być liczbą całkowitą od 0 do 9.")
	low, high = values["minBitrate"], values["maxBitrate"]
	if low or high:
		if mode not in caps.limit_modes:
			raise ValueError("Wybrany enkoder lub tryb nie obsługuje granic przepływności.")
		if low > caps.bitrate_max or high > caps.bitrate_max:
			raise ValueError("Granica przepływności przekracza możliwości enkodera.")
		if low and high and low > high:
			raise ValueError("Minimalna przepływność nie może przekraczać maksymalnej.")
		if target == "mp3" and any(value and value not in MP3_RATES for value in (low, high)):
			raise ValueError("Granice MP3 muszą odpowiadać przepływnościom standardu MPEG.")
		if target == "mp3" and sample_rate and any(value and value not in allowed for value in (low, high)):
			raise ValueError("Granice MP3 nie są zgodne z częstotliwością próbkowania.")
		if mode == "abr":
			if rate and ((low and rate < low) or (high and rate > high)):
				raise ValueError("Docelowa przepływność ABR musi mieścić się między minimum i maksimum.")
	quality = values["vbrQuality"]
	if quality != -1:
		if mode != "vbr" or target not in {"mp3", "ogg", "aac", "m4a"}:
			raise ValueError("Jakość VBR jest dostępna tylko w trybie VBR tego enkodera.")
		if not caps.quality_min <= quality <= caps.quality_max:
			raise ValueError("Jakość VBR jest poza zakresem wybranego enkodera.")
		if encoder == "gogo" and target == "mp3" and not quality.is_integer():
			raise ValueError("GOGO wymaga całkowitej jakości VBR od 0 do 9.")
	if not caps.flags and any(values[key] != -1 for key in ("copyright", "original")):
		raise ValueError("Wybrany enkoder nie udostępnia flag copyright i original.")
	# CRC nie jest udostępnione przez żaden z aktualnie dołączonych interfejsów.
	if options.get("crc", -1) != -1:
		raise ValueError("Dołączony enkoder nie udostępnia przełącznika CRC.")


def apply_rate_arguments(arguments: list[str], target: str, encoder: str, options: Mapping[str, Any]) -> list[str]:
	"""Stosuje rozłączne tryby; nigdy nie przekazuje ignorowanych granic LAME."""
	if not options.get("enabled") or target in {"copyAudio", "aacM4a"}:
		return list(arguments)
	validate_rate_options(target, encoder, options)
	values = rate_options_from_mapping(options)
	mode = values["rateMode"]
	result = list(arguments)

	def remove(key: str) -> None:
		while key in result:
			index = result.index(key)
			del result[index:index + 2]

	def put(key: str, value: Any) -> None:
		remove(key)
		result.extend((key, str(value)))

	caps = codec_capabilities(target, encoder)
	quality = values["vbrQuality"]
	if quality == -1:
		quality = caps.quality_default
	if target == "ogg" and values["vbrQuality"] == -1 and "-q:a" in result:
		quality = float(result[result.index("-q:a") + 1])
	if mode != "auto":
		if target == "mp3" and encoder == "lame":
			remove("-q:a")
			put("-abr", 1 if mode == "abr" else 0)
			if mode == "vbr":
				remove("-b:a")
				put("-q:a", f"{quality:g}")
		elif target == "opus":
			put("-vbr", {"cbr": "off", "vbr": "on", "cvbr": "constrained"}[mode])
		elif target in {"m4a", "aac", "ogg"}:
			remove("-q:a")
			if mode == "vbr":
				remove("-b:a")
				put("-q:a", f"{quality:g}")
			elif "-b:a" not in result:
				put("-b:a", "160k")
	if mode in caps.limit_modes:
		for field, argument in (("minBitrate", "-minrate:a"), ("maxBitrate", "-maxrate:a")):
			if values[field]:
				put(argument, f"{values[field]}k")
		# Domyślny bitrate też musi spełniać zadane granice Vorbis.
		if mode == "abr" and "-b:a" in result:
			rate = int(result[result.index("-b:a") + 1].rstrip("k"))
			if (values["minBitrate"] and rate < values["minBitrate"]) or (values["maxBitrate"] and rate > values["maxBitrate"]):
				raise ValueError("Docelowa przepływność ABR musi mieścić się między minimum i maksimum.")
	for field in ("copyright", "original"):
		if values[field] != -1:
			put(f"-{field}", values[field])
	return result
