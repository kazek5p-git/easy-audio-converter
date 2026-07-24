from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "globalPlugins" / "easyAudioConverter"))

from updater import (  # noqa: E402
	ReleaseInfo,
	UpdateCanceled,
	UpdateError,
	download_release,
	fetch_latest_release,
	is_newer_version,
	parse_github_release,
	validate_addon_package,
	version_key,
)


class _Response(io.BytesIO):
	def __init__(self, data: bytes, content_type: str = "application/octet-stream"):
		super().__init__(data)
		self.headers = {
			"Content-Length": str(len(data)),
			"Content-Type": content_type,
		}

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		self.close()


def _addon_bytes(
	version: str = "1.1.0",
	name: str = "easyAudioConverter",
	unsafe_member: str | None = None,
) -> bytes:
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
		archive.writestr(
			"manifest.ini",
			f"name = {name}\nversion = {version}\nminimumNVDAVersion = 2024.1.0\n",
		)
		archive.writestr("globalPlugins/easyAudioConverter/__init__.py", "# test")
		if unsafe_member:
			archive.writestr(unsafe_member, "unsafe")
	return buffer.getvalue()


class VersionTests(unittest.TestCase):
	def test_numeric_versions_compare_reliably(self):
		self.assertTrue(is_newer_version("1.10.0", "1.9.9"))
		self.assertFalse(is_newer_version("v1.1", "1.1.0"))
		self.assertEqual((2, 4, 1), version_key("v2.4.1-beta1")[:3])


class ReleaseParsingTests(unittest.TestCase):
	def test_release_parser_selects_nvda_asset_and_digest(self):
		release = parse_github_release(
			{
				"tag_name": "v1.1.0",
				"html_url": "https://example.invalid/release",
				"body": "Changes",
				"assets": [
					{"name": "source.zip", "browser_download_url": "https://example.invalid/source"},
					{
						"name": "EasyAudioConverter-1.1.0.nvda-addon",
						"browser_download_url": "https://example.invalid/addon",
						"digest": "sha256:" + "A" * 64,
						"size": 123,
					},
				],
			}
		)
		self.assertEqual("1.1.0", release.version)
		self.assertTrue(release.download_url.endswith("/addon"))
		self.assertEqual("A" * 64, release.sha256)
		self.assertEqual(123, release.size)

	def test_fetch_latest_release_accepts_bounded_json(self):
		payload = json.dumps(
			{
				"tag_name": "v1.2.0",
				"html_url": "https://example.invalid/release",
				"assets": [],
			}
		).encode()
		release = fetch_latest_release(opener=lambda request, timeout: _Response(payload))
		self.assertEqual("1.2.0", release.version)


class PackageValidationTests(unittest.TestCase):
	def test_valid_package_is_accepted(self):
		with tempfile.TemporaryDirectory() as temporary:
			path = Path(temporary) / "addon.nvda-addon"
			path.write_bytes(_addon_bytes())
			validate_addon_package(path, expected_version="1.1.0")

	def test_wrong_addon_or_version_is_rejected(self):
		with tempfile.TemporaryDirectory() as temporary:
			path = Path(temporary) / "addon.nvda-addon"
			path.write_bytes(_addon_bytes(version="9.0", name="otherAddon"))
			with self.assertRaises(UpdateError):
				validate_addon_package(path, expected_version="1.1.0")

	def test_unsafe_archive_path_is_rejected(self):
		with tempfile.TemporaryDirectory() as temporary:
			path = Path(temporary) / "addon.nvda-addon"
			path.write_bytes(_addon_bytes(unsafe_member="../outside.txt"))
			with self.assertRaises(UpdateError):
				validate_addon_package(path, expected_version="1.1.0")

	def test_download_verifies_hash_and_package_before_renaming(self):
		data = _addon_bytes()
		release = ReleaseInfo(
			version="1.1.0",
			page_url="https://example.invalid/release",
			download_url="https://example.invalid/addon",
			asset_name="addon.nvda-addon",
			notes="",
			sha256=hashlib.sha256(data).hexdigest(),
			size=len(data),
		)
		progress = []
		with tempfile.TemporaryDirectory() as temporary:
			destination = Path(temporary) / "downloaded.nvda-addon"
			result = download_release(
				release,
				destination,
				progress_callback=lambda done, total: progress.append((done, total)),
				opener=lambda request, timeout: _Response(data),
			)
			self.assertEqual(destination, result)
			self.assertEqual(data, destination.read_bytes())
			self.assertEqual(len(data), progress[-1][0])

	def test_canceled_download_removes_partial_file(self):
		data = _addon_bytes()
		release = ReleaseInfo(
			version="1.1.0",
			page_url="",
			download_url="https://example.invalid/addon",
			asset_name="addon.nvda-addon",
			notes="",
			size=len(data),
		)
		cancel = threading.Event()
		cancel.set()
		with tempfile.TemporaryDirectory() as temporary:
			destination = Path(temporary) / "downloaded.nvda-addon"
			with self.assertRaises(UpdateCanceled):
				download_release(
					release,
					destination,
					cancel_event=cancel,
					opener=lambda request, timeout: _Response(data),
				)
			self.assertFalse(destination.exists())
			self.assertFalse(destination.with_suffix(".nvda-addon.part").exists())


if __name__ == "__main__":
	unittest.main()
