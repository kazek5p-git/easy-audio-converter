"""Safe serialization for complete, named conversion profiles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .converter import (
	ADVANCED_BIT_DEPTHS,
	ADVANCED_CHANNEL_COUNTS,
	ADVANCED_SAMPLE_RATES,
	FORMAT_KEYS,
	LOUDNESS_PRESET_KEYS,
	METADATA_FIELD_KEYS,
	METADATA_MODE_KEYS,
	MP3_ENCODER_KEYS,
	QUALITY_KEYS,
	ConversionSettings,
)


PROFILE_SCHEMA_VERSION = 1
MAX_USER_PROFILES = 50
MAX_PROFILE_NAME_LENGTH = 80
MAX_PROFILE_DOCUMENT_BYTES = 256 * 1024


@dataclass(frozen=True)
class NamedConversionProfile:
	"""A user-visible name paired with a complete conversion snapshot."""

	name: str
	settings: ConversionSettings


def normalize_profile_name(value: Any) -> str:
	"""Normalize whitespace and bound profile names stored in NVDA config."""
	return " ".join(str(value or "").split())[:MAX_PROFILE_NAME_LENGTH]


def _validated_key(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
	value = str(value or "")
	return value if value in allowed else fallback


def _validated_bool(value: Any, fallback: bool) -> bool:
	return value if isinstance(value, bool) else fallback


def _safe_int(value: Any, fallback: int) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return fallback


def _safe_float(value: Any, fallback: float, minimum: float, maximum: float) -> float:
	try:
		result = float(value)
	except (TypeError, ValueError):
		return fallback
	if result != result or not minimum <= result <= maximum:
		return fallback
	return result


def _advanced_options_from_mapping(
	value: Any,
	fallback: Mapping[str, Any],
) -> dict[str, Any]:
	raw = value if isinstance(value, Mapping) else fallback
	enabled = _validated_bool(raw.get("enabled"), bool(fallback.get("enabled", False)))
	bitrate = max(0, min(1536, _safe_int(raw.get("bitrate"), 0)))
	sample_rate = _safe_int(raw.get("sampleRate"), 0)
	if sample_rate not in ADVANCED_SAMPLE_RATES:
		sample_rate = 0
	channels = _safe_int(raw.get("channels"), 0)
	if channels not in ADVANCED_CHANNEL_COUNTS:
		channels = 0
	codec_level = max(-1, min(12, _safe_int(raw.get("codecLevel"), -1)))
	bit_depth = _safe_int(raw.get("bitDepth"), 0)
	if bit_depth not in ADVANCED_BIT_DEPTHS:
		bit_depth = 0
	return {
		"enabled": enabled,
		"bitrate": bitrate,
		"sampleRate": sample_rate,
		"channels": channels,
		"codecLevel": codec_level,
		"bitDepth": bit_depth,
	}


def conversion_settings_to_mapping(settings: ConversionSettings) -> dict[str, Any]:
	"""Return the stable JSON representation of a conversion snapshot."""
	settings.validate()
	return {
		"targetFormat": settings.target_format,
		"quality": settings.quality,
		"mp3Encoder": settings.mp3_encoder,
		"sameFolder": settings.same_folder,
		"outputFolder": settings.output_folder,
		"includeSubfolders": settings.include_subfolders,
		"preserveFolderStructure": settings.preserve_folder_structure,
		"preserveTimestamps": settings.preserve_timestamps,
		"metadataMode": settings.metadata_mode,
		"metadataFields": list(settings.metadata_fields),
		"advancedOptions": _advanced_options_from_mapping(settings.advanced_options, {}),
		"outputNameTemplate": settings.output_name_template,
		"loudnessPreset": settings.loudness_preset,
		"loudnessTargetI": settings.loudness_target_i,
		"loudnessTargetTP": settings.loudness_target_tp,
		"loudnessTargetLRA": settings.loudness_target_lra,
		"copyArtwork": settings.copy_artwork,
		"copyChapters": settings.copy_chapters,
		"verifyOutput": settings.verify_output,
		"showPreflight": settings.show_preflight,
	}


def conversion_settings_from_mapping(
	value: Any,
	*,
	fallback: ConversionSettings | None = None,
) -> ConversionSettings:
	"""Load a profile defensively, replacing invalid values with known defaults."""
	base = fallback or ConversionSettings()
	raw = value if isinstance(value, Mapping) else {}
	metadata_fields = raw.get("metadataFields", base.metadata_fields)
	if isinstance(metadata_fields, str):
		metadata_fields = [field.strip() for field in metadata_fields.split(",")]
	if not isinstance(metadata_fields, (list, tuple)):
		metadata_fields = base.metadata_fields
	metadata_fields = tuple(
		field_name
		for field_name in metadata_fields
		if isinstance(field_name, str) and field_name in METADATA_FIELD_KEYS
	)
	same_folder = _validated_bool(raw.get("sameFolder"), base.same_folder)
	output_folder = str(raw.get("outputFolder") or base.output_folder).strip()
	if not same_folder and not output_folder:
		same_folder = True
	settings = ConversionSettings(
		target_format=_validated_key(
			raw.get("targetFormat"),
			FORMAT_KEYS,
			base.target_format,
		),
		quality=_validated_key(raw.get("quality"), QUALITY_KEYS, base.quality),
		mp3_encoder=_validated_key(
			raw.get("mp3Encoder"),
			MP3_ENCODER_KEYS,
			base.mp3_encoder,
		),
		same_folder=same_folder,
		output_folder=output_folder,
		include_subfolders=_validated_bool(
			raw.get("includeSubfolders"),
			base.include_subfolders,
		),
		preserve_folder_structure=_validated_bool(
			raw.get("preserveFolderStructure"),
			base.preserve_folder_structure,
		),
		preserve_timestamps=_validated_bool(
			raw.get("preserveTimestamps"),
			base.preserve_timestamps,
		),
		metadata_mode=_validated_key(
			raw.get("metadataMode"),
			METADATA_MODE_KEYS,
			base.metadata_mode,
		),
		metadata_fields=metadata_fields,
		advanced_options=_advanced_options_from_mapping(
			raw.get("advancedOptions"),
			base.advanced_options,
		),
		output_name_template=str(
			raw.get("outputNameTemplate") or base.output_name_template
		)[:240],
		loudness_preset=_validated_key(
			raw.get("loudnessPreset"),
			LOUDNESS_PRESET_KEYS,
			base.loudness_preset,
		),
		loudness_target_i=_safe_float(
			raw.get("loudnessTargetI"),
			base.loudness_target_i,
			-70.0,
			-5.0,
		),
		loudness_target_tp=_safe_float(
			raw.get("loudnessTargetTP"),
			base.loudness_target_tp,
			-9.0,
			0.0,
		),
		loudness_target_lra=_safe_float(
			raw.get("loudnessTargetLRA"),
			base.loudness_target_lra,
			1.0,
			50.0,
		),
		copy_artwork=_validated_bool(raw.get("copyArtwork"), base.copy_artwork),
		copy_chapters=_validated_bool(raw.get("copyChapters"), base.copy_chapters),
		verify_output=_validated_bool(raw.get("verifyOutput"), base.verify_output),
		show_preflight=_validated_bool(raw.get("showPreflight"), base.show_preflight),
	)
	settings.validate()
	return settings


def load_user_profiles(
	value: Any,
	*,
	fallback: ConversionSettings | None = None,
) -> list[NamedConversionProfile]:
	"""Load the bounded, versioned profile list from an NVDA config value."""
	document = str(value or "{}")
	if len(document.encode("utf-8", errors="replace")) > MAX_PROFILE_DOCUMENT_BYTES:
		return []
	try:
		payload = json.loads(document)
	except (TypeError, ValueError):
		return []
	if not isinstance(payload, Mapping):
		return []
	if _safe_int(payload.get("version"), 0) != PROFILE_SCHEMA_VERSION:
		return []
	raw_profiles = payload.get("profiles")
	if not isinstance(raw_profiles, list):
		return []
	profiles: list[NamedConversionProfile] = []
	seen_names: set[str] = set()
	for item in raw_profiles:
		if len(profiles) >= MAX_USER_PROFILES:
			break
		if not isinstance(item, Mapping):
			continue
		name = normalize_profile_name(item.get("name"))
		name_key = name.casefold()
		if not name or name_key in seen_names:
			continue
		try:
			settings = conversion_settings_from_mapping(
				item.get("settings"),
				fallback=fallback,
			)
		except (TypeError, ValueError):
			continue
		seen_names.add(name_key)
		profiles.append(NamedConversionProfile(name, settings))
	return profiles


def dump_user_profiles(profiles: Iterable[NamedConversionProfile]) -> str:
	"""Serialize profiles deterministically for NVDA's string configuration."""
	items = []
	seen_names: set[str] = set()
	for profile in profiles:
		if len(items) >= MAX_USER_PROFILES:
			break
		name = normalize_profile_name(profile.name)
		name_key = name.casefold()
		if not name or name_key in seen_names:
			continue
		seen_names.add(name_key)
		items.append(
			{
				"name": name,
				"settings": conversion_settings_to_mapping(profile.settings),
			}
		)
	return json.dumps(
		{"version": PROFILE_SCHEMA_VERSION, "profiles": items},
		ensure_ascii=True,
		sort_keys=True,
		separators=(",", ":"),
	)


def upsert_user_profile(
	profiles: Iterable[NamedConversionProfile],
	profile: NamedConversionProfile,
) -> list[NamedConversionProfile]:
	"""Add or replace one profile using a case-insensitive name match."""
	name = normalize_profile_name(profile.name)
	if not name:
		raise ValueError("A profile name is required")
	replacement = NamedConversionProfile(name, profile.settings)
	result: list[NamedConversionProfile] = []
	replaced = False
	for current in profiles:
		if normalize_profile_name(current.name).casefold() == name.casefold():
			if not replaced:
				result.append(replacement)
				replaced = True
			continue
		result.append(current)
	if not replaced:
		if len(result) >= MAX_USER_PROFILES:
			raise ValueError("The maximum number of profiles has been reached")
		result.append(replacement)
	return result


def remove_user_profile(
	profiles: Iterable[NamedConversionProfile],
	name: str,
) -> list[NamedConversionProfile]:
	"""Return the list without the case-insensitively matched profile name."""
	name_key = normalize_profile_name(name).casefold()
	return [
		profile
		for profile in profiles
		if normalize_profile_name(profile.name).casefold() != name_key
	]


def merge_user_profiles(
	current: Iterable[NamedConversionProfile],
	imported: Iterable[NamedConversionProfile],
) -> list[NamedConversionProfile]:
	"""Merge imported profiles, replacing same-name entries deterministically."""
	result = list(current)
	for profile in imported:
		result = upsert_user_profile(result, profile)
	return result
