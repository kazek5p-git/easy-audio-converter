"""Build and validate the Easy Audio Converter NVDA package."""

from __future__ import annotations

import hashlib
import os
import re
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
DIST_ROOT = PROJECT_ROOT / "dist"


def _manifest_value(name: str) -> str:
	text = (SOURCE_ROOT / "manifest.ini").read_text(encoding="utf-8")
	match = re.search(rf"(?m)^{re.escape(name)}\s*=\s*[\"']?([^\"'\r\n]+)", text)
	if not match:
		raise RuntimeError(f"Missing {name} in manifest.ini")
	return match.group(1).strip()


def _included_files() -> list[Path]:
	files = []
	for path in SOURCE_ROOT.rglob("*"):
		if not path.is_file():
			continue
		relative = path.relative_to(SOURCE_ROOT)
		if "__pycache__" in relative.parts or path.suffix.lower() in {".pyc", ".pyo"}:
			continue
		files.append(path)
	return sorted(files, key=lambda path: path.relative_to(SOURCE_ROOT).as_posix().lower())


def _sha256(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as stream:
		for block in iter(lambda: stream.read(1024 * 1024), b""):
			digest.update(block)
	return digest.hexdigest().upper()


def build() -> Path:
	required = (
		SOURCE_ROOT / "manifest.ini",
		SOURCE_ROOT / "installTasks.py",
		SOURCE_ROOT / "globalPlugins" / "easyAudioConverter" / "__init__.py",
		SOURCE_ROOT / "globalPlugins" / "easyAudioConverter" / "converter.py",
		SOURCE_ROOT / "globalPlugins" / "easyAudioConverter" / "bin" / "ffmpeg.exe",
		SOURCE_ROOT / "licenses" / "COPYING-GPL-3.txt",
	)
	missing = [str(path) for path in required if not path.is_file()]
	if missing:
		raise RuntimeError("Required package files are missing:\n" + "\n".join(missing))

	DIST_ROOT.mkdir(parents=True, exist_ok=True)
	name = _manifest_value("name")
	version = _manifest_value("version")
	output = DIST_ROOT / f"{name}-{version}.nvda-addon"
	temporary = output.with_suffix(output.suffix + ".tmp")
	if temporary.exists():
		temporary.unlink()

	with zipfile.ZipFile(
		temporary,
		"w",
		compression=zipfile.ZIP_DEFLATED,
		compresslevel=6,
		allowZip64=True,
	) as archive:
		for path in _included_files():
			relative = path.relative_to(SOURCE_ROOT).as_posix()
			archive.write(path, relative)

	os.replace(temporary, output)
	with zipfile.ZipFile(output, "r") as archive:
		bad_member = archive.testzip()
		if bad_member:
			raise RuntimeError(f"Corrupt ZIP member: {bad_member}")
		names = set(archive.namelist())
		for expected in (
			"manifest.ini",
			"installTasks.py",
			"globalPlugins/easyAudioConverter/__init__.py",
			"globalPlugins/easyAudioConverter/converter.py",
			"globalPlugins/easyAudioConverter/bin/ffmpeg.exe",
		):
			if expected not in names:
				raise RuntimeError(f"Missing archive member: {expected}")
		if any(name.startswith("src/") for name in names):
			raise RuntimeError("The package contains an unexpected src directory")

	print(f"Built: {output}")
	print(f"Bytes: {output.stat().st_size}")
	print(f"SHA-256: {_sha256(output)}")
	return output


if __name__ == "__main__":
	try:
		build()
	except Exception as error:
		print(f"Build failed: {error}", file=sys.stderr)
		raise SystemExit(1)
