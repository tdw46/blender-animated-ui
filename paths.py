"""Persistent path helpers with Blender 4.2+ and legacy fallbacks."""

from __future__ import annotations

from pathlib import Path

import bpy

from .constants import ADDON_ID


def extension_package() -> str:
    return __package__ or ADDON_ID


def user_root() -> Path:
    extension_path_user = getattr(bpy.utils, "extension_path_user", None)
    if callable(extension_path_user):
        try:
            return Path(
                extension_path_user(
                    extension_package(),
                    path="",
                    create=True,
                )
            )
        except (RuntimeError, TypeError, ValueError):
            pass
    return Path(
        bpy.utils.user_resource(
            "DATAFILES",
            path=f"{ADDON_ID}",
            create=True,
        )
    )


def default_cache_root() -> Path:
    return user_root() / "thumbnail_cache"


def _configured_cache_directory() -> str:
    preferences = getattr(getattr(bpy.context, "preferences", None), "addons", None)
    if preferences is None:
        return ""
    addon = preferences.get(extension_package())
    if addon is None:
        return ""
    addon_preferences = getattr(addon, "preferences", None)
    return str(
        getattr(addon_preferences, "thumbnail_cache_directory", "") or ""
    ).strip()


def cache_root() -> Path:
    configured = _configured_cache_directory()
    if configured:
        try:
            path = Path(bpy.path.abspath(configured)).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            path = default_cache_root()
    else:
        path = default_cache_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def dependency_root() -> Path:
    path = user_root() / "python_dependencies"
    path.mkdir(parents=True, exist_ok=True)
    return path
