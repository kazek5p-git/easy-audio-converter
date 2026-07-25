"""GitHub release updater core with no dependency on NVDA."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


GITHUB_REPOSITORY_URL = "https://github.com/kazek5p-git/easy-audio-converter"
GITHUB_RELEASE_API_URL = (
	"https://api.github.com/repos/kazek5p-git/easy-audio-converter/releases/latest"
)
USER_AGENT = "EasyAudioConverter-NVDA-Updater/1.1.2"
MAX_RELEASE_RESPONSE_BYTES = 2 * 1024 * 1024


class UpdateError(RuntimeError):
	pass


class UpdateCanceled(UpdateError):
	pass


@dataclass(frozen=True)
class ReleaseInfo:
	version: str
	page_url: str
	download_url: str
	asset_name: str
	notes: str
	sha256: str | None = None
	size: int | None = None


def version_key(version: str) -> tuple[int, ...]:
	"""Return a comparable numeric key for common add-on version strings."""
	cleaned = str(version or "").strip().lstrip("vV")
	numbers = re.findall(r"\d+", cleaned)
	if not numbers:
		return (0,)
	return tuple(int(number) for number in numbers[:6])


def is_newer_version(candidate: str, current: str) -> bool:
	candidate_key = version_key(candidate)
	current_key = version_key(current)
	length = max(len(candidate_key), len(current_key))
	return candidate_key + (0,) * (length - len(candidate_key)) > current_key + (0,) * (
		length - len(current_key)
	)


def parse_github_release(payload: Mapping[str, Any]) -> ReleaseInfo:
	if bool(payload.get("draft", False)):
		raise UpdateError("The latest GitHub release is still a draft")
	version = str(payload.get("tag_name") or payload.get("name") or "").strip().lstrip("vV")
	if not version or version_key(version) == (0,):
		raise UpdateError("The release does not contain a valid version")
	page_url = str(payload.get("html_url") or GITHUB_REPOSITORY_URL)
	assets = payload.get("assets")
	if not isinstance(assets, list):
		assets = []
	candidates = [
		asset
		for asset in assets
		if isinstance(asset, Mapping)
		and str(asset.get("name", "")).lower().endswith(".nvda-addon")
	]
	if candidates:
		candidates.sort(
			key=lambda asset: (
				"easyaudioconverter" not in str(asset.get("name", "")).replace("-", "").lower(),
				str(asset.get("name", "")).lower(),
			)
		)
		asset = candidates[0]
		download_url = str(asset.get("browser_download_url") or "")
		asset_name = str(asset.get("name") or f"easyAudioConverter-{version}.nvda-addon")
		digest = str(asset.get("digest") or "")
		sha256 = digest.split(":", 1)[1].upper() if digest.lower().startswith("sha256:") else None
		try:
			size = int(asset.get("size")) if asset.get("size") is not None else None
		except (TypeError, ValueError):
			size = None
	else:
		download_url = ""
		asset_name = ""
		sha256 = None
		size = None
	return ReleaseInfo(
		version=version,
		page_url=page_url,
		download_url=download_url,
		asset_name=asset_name,
		notes=str(payload.get("body") or "").strip(),
		sha256=sha256,
		size=size,
	)


def fetch_latest_release(
	api_url: str = GITHUB_RELEASE_API_URL,
	*,
	timeout: float = 15,
	opener: Callable[..., Any] = urllib.request.urlopen,
) -> ReleaseInfo:
	request = urllib.request.Request(
		api_url,
		headers={
			"User-Agent": USER_AGENT,
			"Accept": "application/vnd.github+json",
			"X-GitHub-Api-Version": "2022-11-28",
		},
	)
	with opener(request, timeout=timeout) as response:
		content_length = response.headers.get("Content-Length")
		if content_length and int(content_length) > MAX_RELEASE_RESPONSE_BYTES:
			raise UpdateError("The update response is unexpectedly large")
		data = response.read(MAX_RELEASE_RESPONSE_BYTES + 1)
	if len(data) > MAX_RELEASE_RESPONSE_BYTES:
		raise UpdateError("The update response is unexpectedly large")
	try:
		payload = json.loads(data.decode("utf-8"))
	except (UnicodeDecodeError, ValueError) as error:
		raise UpdateError("The update response is not valid JSON") from error
	if not isinstance(payload, Mapping):
		raise UpdateError("The update response has an unexpected structure")
	return parse_github_release(payload)


def _manifest_value(text: str, name: str) -> str:
	match = re.search(
		rf"(?m)^{re.escape(name)}\s*=\s*[\"']?([^\"'\r\n]+)",
		text,
	)
	return match.group(1).strip() if match else ""


def validate_addon_package(
	path: str | os.PathLike[str],
	*,
	expected_version: str,
	expected_name: str = "easyAudioConverter",
) -> None:
	try:
		with zipfile.ZipFile(path, "r") as archive:
			if archive.testzip() is not None:
				raise UpdateError("The downloaded add-on archive is corrupt")
			names = archive.namelist()
			if any(
				name.startswith(("/", "\\"))
				or re.match(r"^[A-Za-z]:", name) is not None
				or ".." in Path(name.replace("\\", "/")).parts
				for name in names
			):
				raise UpdateError("The downloaded add-on contains an unsafe path")
			manifest = archive.read("manifest.ini").decode("utf-8")
	except (KeyError, OSError, UnicodeDecodeError, zipfile.BadZipFile) as error:
		raise UpdateError("The downloaded file is not a valid NVDA add-on") from error
	if _manifest_value(manifest, "name") != expected_name:
		raise UpdateError("The downloaded package belongs to another add-on")
	if version_key(_manifest_value(manifest, "version")) != version_key(expected_version):
		raise UpdateError("The downloaded package version does not match the release")


def download_release(
	release: ReleaseInfo,
	destination: str | os.PathLike[str],
	*,
	progress_callback: Callable[[int, int | None], None] | None = None,
	cancel_event: threading.Event | None = None,
	timeout: float = 60,
	opener: Callable[..., Any] = urllib.request.urlopen,
) -> Path:
	if not release.download_url:
		raise UpdateError("The release does not contain an NVDA add-on package")
	cancel_event = cancel_event or threading.Event()
	destination_path = Path(destination)
	destination_path.parent.mkdir(parents=True, exist_ok=True)
	partial_path = destination_path.with_suffix(destination_path.suffix + ".part")
	request = urllib.request.Request(
		release.download_url,
		headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"},
	)
	hasher = hashlib.sha256()
	bytes_read = 0
	try:
		with opener(request, timeout=timeout) as response, partial_path.open("wb") as output:
			content_length = response.headers.get("Content-Length")
			try:
				total_size = int(content_length) if content_length else release.size
			except (TypeError, ValueError):
				total_size = release.size
			if progress_callback is not None:
				progress_callback(0, total_size)
			while True:
				if cancel_event.is_set():
					raise UpdateCanceled("The update download was canceled")
				block = response.read(1024 * 1024)
				if not block:
					break
				output.write(block)
				hasher.update(block)
				bytes_read += len(block)
				if progress_callback is not None:
					progress_callback(bytes_read, total_size)
		if total_size is not None and bytes_read != total_size:
			raise UpdateError("The downloaded update has an incorrect size")
		actual_hash = hasher.hexdigest().upper()
		if release.sha256 and actual_hash != release.sha256.upper():
			raise UpdateError("The downloaded update failed SHA-256 verification")
		validate_addon_package(partial_path, expected_version=release.version)
		os.replace(partial_path, destination_path)
		return destination_path
	finally:
		if partial_path.exists():
			try:
				partial_path.unlink()
			except OSError:
				pass
