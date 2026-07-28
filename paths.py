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


def cache_root() -> Path:
    path = user_root() / "thumbnail_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dependency_root() -> Path:
    path = user_root() / "python_dependencies"
    path.mkdir(parents=True, exist_ok=True)
    return path
