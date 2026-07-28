"""Verify custom cache-root preferences without moving existing caches."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import addon_utils
import bpy

MODULE = os.environ.get(
    "ANIMTHUMB_MODULE",
    "bl_ext.user_default.blender_animated_ui",
)

addon_utils.enable(MODULE, default_set=True)
package = __import__(MODULE, fromlist=["paths"])
preferences = bpy.context.preferences.addons[MODULE].preferences
original = str(preferences.thumbnail_cache_directory or "")

try:
    with tempfile.TemporaryDirectory() as temporary:
        selected = Path(temporary) / "custom_thumbnail_cache"
        preferences.thumbnail_cache_directory = str(selected)
        resolved = package.paths.cache_root()
        if resolved != selected.resolve():
            raise RuntimeError(
                f"Custom cache root did not resolve: {resolved} != {selected.resolve()}"
            )
        if not resolved.is_dir():
            raise RuntimeError("Custom cache root was not created")
finally:
    preferences.thumbnail_cache_directory = original

print(
    "ANIMTHUMB_CACHE_PREFERENCES",
    {
        "custom_location": True,
        "default_location_restored": package.paths.cache_root().is_dir(),
        "open_directory_operator": hasattr(
            bpy.types,
            "ANIMTHUMB_OT_open_cache_directory",
        ),
    },
)
addon_utils.disable(MODULE)
