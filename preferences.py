"""Extension preferences for persistent thumbnail-cache storage."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty


def _cache_directory_updated(_preferences, _context) -> None:
    try:
        from . import library, preview_engine

        library.refresh_all_scenes()
        preview_engine.tag_targeted_layout_refresh()
    except Exception as error:
        print(f"Animated thumbnails: cache location refresh failed: {error}")


class ANIMTHUMB_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    thumbnail_cache_directory: StringProperty(
        name="Thumbnail Cache Location",
        description=(
            "Optional custom directory for generated thumbnail caches; leave empty "
            "to use Blender's persistent extension-user storage"
        ),
        subtype="DIR_PATH",
        default="",
        update=_cache_directory_updated,
    )

    def draw(self, context):
        del context
        from .paths import cache_root, default_cache_root

        layout = self.layout
        cache_box = layout.box()
        cache_box.label(text="Animated Thumbnail Cache", icon="FILE_FOLDER")
        cache_box.prop(self, "thumbnail_cache_directory")
        if self.thumbnail_cache_directory:
            cache_box.label(text=f"Active: {cache_root()}")
        else:
            cache_box.label(text=f"Default: {default_cache_root()}")
        cache_box.label(
            text="Changing this location does not move or delete existing caches.",
            icon="INFO",
        )
        cache_box.operator(
            "animthumb.open_cache_directory",
            text="Open Active Cache Directory",
            icon="FILE_FOLDER",
        )
