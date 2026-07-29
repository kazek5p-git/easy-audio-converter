"""Generate the small deterministic error and cancel notification sounds."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOUND_ROOT = PROJECT_ROOT / "src" / "globalPlugins" / "easyAudioConverter" / "sounds"
SAMPLE_RATE = 44100


def _envelope(position: float, duration: float) -> float:
	attack = min(1.0, position / 0.025)
	release = min(1.0, max(0.0, duration - position) / 0.12)
	return math.sin(math.pi * min(1.0, attack)) * math.sin(
		math.pi * 0.5 * min(1.0, release)
	)


def _write_sound(
	name: str,
	duration: float,
	sample_function,
) -> None:
	path = SOUND_ROOT / name
	frame_count = int(duration * SAMPLE_RATE)
	frames = bytearray()
	for index in range(frame_count):
		position = index / SAMPLE_RATE
		value = max(-1.0, min(1.0, sample_function(position) * _envelope(position, duration)))
		frames.extend(struct.pack("<h", int(value * 32767)))
	with wave.open(str(path), "wb") as output:
		output.setnchannels(1)
		output.setsampwidth(2)
		output.setframerate(SAMPLE_RATE)
		output.writeframes(frames)
	print(f"Generated: {path}")


def _error_tone(position: float) -> float:
	frequency = 660.0 if position < 0.23 else 440.0
	local_position = position if position < 0.23 else position - 0.23
	pulse = 1.0 if position < 0.18 or position > 0.27 else 0.0
	return pulse * (
		0.28 * math.sin(2 * math.pi * frequency * local_position)
		+ 0.05 * math.sin(2 * math.pi * frequency * 2 * local_position)
	)


def _cancel_tone(position: float) -> float:
	frequency = 392.0 - 120.0 * min(1.0, position / 0.65)
	return 0.22 * math.sin(2 * math.pi * frequency * position)


def main() -> None:
	SOUND_ROOT.mkdir(parents=True, exist_ok=True)
	_write_sound("notification_error.wav", 0.62, _error_tone)
	_write_sound("notification_cancel.wav", 0.68, _cancel_tone)


if __name__ == "__main__":
	main()
