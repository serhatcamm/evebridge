"""
Simple Update Checker & Installer
------------------------------------
Checks a JSON "manifest" URL for a newer app version, and can download +
apply a full-source .zip update in place, automatically backing up any
files it replaces first.

Expected manifest format (hosted anywhere reachable by HTTP, e.g. a raw
GitHub file):

    {
        "version": "1.6.0",
        "changelog": "- Added DHCP wizard\\n- Fixed PuTTY detection",
        "download_url": "https://github.com/<user>/<repo>/releases/download/v1.6.0/eve-ng-lab-automation.zip"
    }

The download_url should point to a .zip containing the updated .py files
(and optionally requirements.txt / README.md) either at the zip root or
inside a single top-level folder (e.g. GitHub's auto-generated
"Source code (zip)" layout both work).
"""

import io
import os
import shutil
import zipfile
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

APP_VERSION = "2.3.0"

# Files this app actively manages. Not used to restrict what gets installed
# (any file in the update package is applied), just documents what a normal
# update is expected to touch.
MANAGED_FILES = [
    "main_app.py", "eve_api.py", "config_builder.py", "image_uploader.py",
    "terminal_launcher.py", "capture_manager.py", "firewall_config_builder.py",
    "updater.py", "requirements.txt", "README.md", "icon.ico",
]


def _parse_version(v: str) -> tuple:
    """Parses '1.6.0' -> (1, 6, 0). Non-numeric segments become 0, so odd
    version strings don't crash the comparison, they just sort low."""
    parts = []
    for p in str(v).strip().split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def is_newer(remote_version: str, local_version: str = APP_VERSION) -> bool:
    return _parse_version(remote_version) > _parse_version(local_version)


def check_for_update(manifest_url: str, timeout: float = 10.0):
    """
    Fetches the JSON manifest at `manifest_url`. Returns the manifest dict if
    it describes a version newer than APP_VERSION, or None if already current.
    Raises RuntimeError / requests exceptions on failure.
    """
    if requests is None:
        raise RuntimeError("The 'requests' package is required to check for updates.")
    if not manifest_url or not manifest_url.strip():
        raise RuntimeError("No update manifest URL configured.")

    resp = requests.get(manifest_url.strip(), timeout=timeout)
    resp.raise_for_status()
    manifest = resp.json()

    remote_version = str(manifest.get("version", "")).strip()
    if not remote_version:
        raise RuntimeError("Update manifest is missing a 'version' field.")

    return manifest if is_newer(remote_version) else None


def download_and_apply_update(download_url: str, app_dir: str, progress_cb=None, timeout: float = 60.0) -> str:
    """
    Downloads the .zip at `download_url` and installs its contents into
    `app_dir`, backing up any files it's about to overwrite into
    app_dir/backup_<timestamp>/ first. Returns the backup directory path.

    `progress_cb(percent: int, message: str)` is called periodically if given.
    """
    if requests is None:
        raise RuntimeError("The 'requests' package is required to download updates.")
    if not download_url or not download_url.strip():
        raise RuntimeError("Update manifest did not provide a download_url.")

    if progress_cb:
        progress_cb(0, "Downloading update package...")

    resp = requests.get(download_url.strip(), timeout=timeout, stream=True)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0) or 0)
    buf = io.BytesIO()
    downloaded = 0
    for chunk in resp.iter_content(chunk_size=65536):
        if not chunk:
            continue
        buf.write(chunk)
        downloaded += len(chunk)
        if progress_cb:
            if total:
                progress_cb(int(downloaded / total * 60), f"Downloading... {downloaded // 1024} KB / {total // 1024} KB")
            else:
                progress_cb(min(downloaded // 1024, 59), f"Downloading... {downloaded // 1024} KB")

    if progress_cb:
        progress_cb(65, "Extracting update package...")

    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise RuntimeError("Update package is empty.")

        # Support a zip with files at the root, or nested inside a single
        # top-level folder (common with GitHub-generated source archives).
        top_levels = {n.split("/")[0] for n in names if "/" in n}
        prefix = ""
        if len(top_levels) == 1:
            candidate = next(iter(top_levels)) + "/"
            if all(n.startswith(candidate) for n in names):
                prefix = candidate

        backup_dir = os.path.join(app_dir, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        extracted = 0
        total_files = max(len(names), 1)

        for name in names:
            rel = name[len(prefix):] if prefix else name
            if not rel or rel.startswith("backup_") or ".." in rel.split("/"):
                continue  # skip empty/backup/path-traversal entries

            dest_path = os.path.join(app_dir, rel)
            dest_dir = os.path.dirname(dest_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)

            # Back up anything we're about to overwrite, on first write only.
            if os.path.isfile(dest_path):
                os.makedirs(backup_dir, exist_ok=True)
                backup_path = os.path.join(backup_dir, rel)
                backup_parent = os.path.dirname(backup_path)
                if backup_parent:
                    os.makedirs(backup_parent, exist_ok=True)
                shutil.copy2(dest_path, backup_path)

            with zf.open(name) as src, open(dest_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

            extracted += 1
            if progress_cb:
                pct = 65 + int(extracted / total_files * 35)
                progress_cb(min(pct, 99), f"Installing {rel}...")

    if progress_cb:
        progress_cb(100, "Update applied.")

    return backup_dir
