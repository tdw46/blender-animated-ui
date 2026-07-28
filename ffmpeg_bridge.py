"""Platform-wheel FFmpeg installation and isolated executable discovery."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .constants import IMAGEIO_FFMPEG_REQUIREMENT, PILLOW_REQUIREMENT
from .paths import dependency_root

_STATUS_CACHE: dict[str, object] | None = None


def _managed_import_root(module_name: str) -> Path | None:
    """Return Blender's managed site-packages root without importing a wheel."""
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if spec is None:
        return None
    locations = tuple(spec.submodule_search_locations or ())
    if locations:
        return Path(locations[0]).resolve().parent
    if spec.origin:
        return Path(spec.origin).resolve().parent
    return None


def _candidate_roots(module_name: str) -> tuple[tuple[str, Path], ...]:
    managed_root = _managed_import_root(module_name)
    runtime_root = dependency_root().resolve()
    candidates: list[tuple[str, Path]] = []
    if managed_root is not None:
        candidates.append(("managed", managed_root))
    if managed_root != runtime_root:
        candidates.append(("runtime", runtime_root))
    return tuple(candidates)


def _probe_wheel_executable_at(root: Path) -> tuple[str, str]:
    target = Path(root)
    probe_code = (
        "import json,sys;"
        f"sys.path.insert(0,{str(target)!r});"
        "import imageio_ffmpeg;"
        "print(json.dumps({'path':imageio_ffmpeg.get_ffmpeg_exe(),"
        "'version':getattr(imageio_ffmpeg,'__version__','unknown')}))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe_code],
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


def _materialize_managed_ffmpeg(root: Path) -> tuple[str, str]:
    """Copy Blender's read-only wheel binary to executable user storage."""
    binary_directory = Path(root) / "imageio_ffmpeg" / "binaries"
    candidates = sorted(
        path for path in binary_directory.glob("ffmpeg-*") if path.is_file()
    )
    if len(candidates) != 1:
        return "", "Managed imageio-ffmpeg wheel has no unique platform binary"
    source = candidates[0]
    destination_directory = dependency_root() / "ffmpeg"
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / source.name
    try:
        if (
            not destination.is_file()
            or destination.stat().st_size != source.stat().st_size
        ):
            temporary = destination.with_suffix(destination.suffix + ".part")
            try:
                shutil.copyfile(source, temporary)
                if os.name != "nt":
                    temporary.chmod(0o755)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        elif os.name != "nt" and not os.access(destination, os.X_OK):
            destination.chmod(0o755)
    except OSError as error:
        return "", f"Could not prepare bundled FFmpeg executable: {error}"
    if not destination.is_file() or (
        os.name != "nt" and not os.access(destination, os.X_OK)
    ):
        return "", "Bundled FFmpeg copy is not executable"
    probe = subprocess.run(
        [str(destination), "-version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if probe.returncode != 0:
        return "", (
            probe.stderr or probe.stdout or "Bundled FFmpeg copy did not run"
        ).strip()
    version = IMAGEIO_FFMPEG_REQUIREMENT.partition("==")[2] or "unknown"
    return str(destination), version


def _probe_wheel_executable(
    root: Path | None = None,
) -> tuple[str, str, str, Path | None]:
    candidates = (
        (("explicit", Path(root)),)
        if root is not None
        else _candidate_roots("imageio_ffmpeg")
    )
    details: list[str] = []
    for source, candidate in candidates:
        executable, detail = _probe_wheel_executable_at(candidate)
        if executable:
            return executable, detail, source, candidate
        if source == "managed":
            executable, managed_detail = _materialize_managed_ffmpeg(candidate)
            if executable:
                return executable, managed_detail, source, candidate
            detail = f"{detail}; {managed_detail}"
        details.append(detail)
    return "", "; ".join(details) or "imageio-ffmpeg wheel not found", "", None


def _probe_pillow_at(root: Path) -> tuple[bool, str]:
    target = Path(root)
    probe_code = (
        "import json,sys;"
        f"sys.path.insert(0,{str(target)!r});"
        "import PIL;"
        "from PIL import Image;"
        "print(json.dumps({'version':getattr(PIL,'__version__','unknown'),"
        "'image_open':callable(Image.open)}))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe_code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "Pillow probe failed").strip()
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        return bool(payload.get("image_open")), str(payload.get("version", "") or "")
    except (IndexError, json.JSONDecodeError, TypeError):
        return False, "Pillow did not return usable metadata"


def _probe_pillow(
    root: Path | None = None,
) -> tuple[bool, str, str, Path | None]:
    candidates = (
        (("explicit", Path(root)),) if root is not None else _candidate_roots("PIL")
    )
    details: list[str] = []
    for source, candidate in candidates:
        ready, detail = _probe_pillow_at(candidate)
        if ready:
            return True, detail, source, candidate
        details.append(detail)
    return False, "; ".join(details) or "Pillow wheel not found", "", None


def status() -> dict[str, object]:
    global _STATUS_CACHE
    if _STATUS_CACHE is not None:
        return dict(_STATUS_CACHE)
    wheel_executable, detail, ffmpeg_source, ffmpeg_root = _probe_wheel_executable()
    pillow_ready, pillow_detail, pillow_source, pillow_root = _probe_pillow()
    system_executable = shutil.which("ffmpeg") or ""
    executable = wheel_executable or system_executable
    target = dependency_root()
    dependency_directory = pillow_root or target
    bundled_wheels_ready = bool(
        wheel_executable
        and pillow_ready
        and ffmpeg_source == "managed"
        and pillow_source == "managed"
    )
    _STATUS_CACHE = {
        # Preserve the original readiness contract for integrations that only
        # need FFmpeg. Animated WebP has its own stricter capability flag.
        "ready": bool(executable),
        "wheel_ready": bool(wheel_executable),
        "media_wheels_ready": bool(wheel_executable and pillow_ready),
        "animated_webp_ready": bool(executable and pillow_ready),
        "executable": executable,
        "wheel_executable": wheel_executable,
        "system_executable": system_executable,
        "pillow_ready": pillow_ready,
        "pillow_version": pillow_detail if pillow_ready else "",
        "dependency_root": str(dependency_directory),
        "runtime_dependency_root": str(target),
        "imageio_dependency_root": str(ffmpeg_root or ""),
        "pillow_dependency_root": str(pillow_root or ""),
        "imageio_source": ffmpeg_source,
        "pillow_source": pillow_source,
        "bundled_wheels_ready": bundled_wheels_ready,
        "detail": f"imageio-ffmpeg {detail}; Pillow {pillow_detail}",
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
    existing = refresh_status()
    if existing.get("media_wheels_ready"):
        source = (
            "bundled manifest wheels"
            if existing.get("bundled_wheels_ready")
            else "extension-user repair wheels"
        )
        return (
            True,
            f"imageio-ffmpeg and Pillow are ready from {source}",
        )

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
        PILLOW_REQUIREMENT,
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

    executable, version, _source, _root = _probe_wheel_executable(target)
    if not executable:
        return False, version
    pillow_ready, pillow_version, _source, _root = _probe_pillow(target)
    if not pillow_ready:
        return False, pillow_version
    refresh_status()
    return (
        True,
        f"imageio-ffmpeg {version} and Pillow {pillow_version} are ready: {executable}",
    )
