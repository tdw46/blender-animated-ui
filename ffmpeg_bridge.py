"""Platform-wheel FFmpeg installation and isolated executable discovery."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .constants import IMAGEIO_FFMPEG_REQUIREMENT
from .paths import dependency_root

_STATUS_CACHE: dict[str, object] | None = None


def _probe_wheel_executable(root: Path | None = None) -> tuple[str, str]:
    target = Path(root) if root is not None else dependency_root()
    probe_code = (
        "import json,sys;"
        f"sys.path.insert(0,{str(target)!r});"
        "import imageio_ffmpeg;"
        "print(json.dumps({'path':imageio_ffmpeg.get_ffmpeg_exe(),"
        "'version':getattr(imageio_ffmpeg,'__version__','unknown')}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe_code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return "", (result.stderr or result.stdout or "Wheel probe failed").strip()
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        executable = str(payload.get("path", "") or "")
        if executable and Path(executable).is_file():
            return executable, str(payload.get("version", "") or "")
    except (IndexError, json.JSONDecodeError, TypeError):
        pass
    return "", "imageio-ffmpeg did not return a usable executable"


def status() -> dict[str, object]:
    global _STATUS_CACHE
    if _STATUS_CACHE is not None:
        return dict(_STATUS_CACHE)
    wheel_executable, detail = _probe_wheel_executable()
    system_executable = shutil.which("ffmpeg") or ""
    executable = wheel_executable or system_executable
    _STATUS_CACHE = {
        "ready": bool(executable),
        "wheel_ready": bool(wheel_executable),
        "executable": executable,
        "wheel_executable": wheel_executable,
        "system_executable": system_executable,
        "detail": detail,
    }
    return dict(_STATUS_CACHE)


def refresh_status() -> dict[str, object]:
    global _STATUS_CACHE
    _STATUS_CACHE = None
    return status()


def _ensure_pip() -> tuple[bool, str]:
    probe = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if probe.returncode == 0:
        return True, probe.stdout.strip()
    ensure = subprocess.run(
        [sys.executable, "-m", "ensurepip", "--upgrade"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if ensure.returncode != 0:
        return False, (ensure.stderr or ensure.stdout or "ensurepip failed").strip()
    return True, ensure.stdout.strip()


def install_wheel() -> tuple[bool, str]:
    pip_ready, pip_detail = _ensure_pip()
    if not pip_ready:
        return False, pip_detail

    target = dependency_root()
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--target",
        str(target),
        "--only-binary=:all:",
        "--no-cache-dir",
        IMAGEIO_FFMPEG_REQUIREMENT,
    ]
    environment = os.environ.copy()
    environment["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=900,
        env=environment,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "pip install failed").strip()
        return False, detail[-4000:]

    executable, version = _probe_wheel_executable(target)
    if not executable:
        return False, version
    refresh_status()
    return True, f"imageio-ffmpeg {version} is ready: {executable}"
