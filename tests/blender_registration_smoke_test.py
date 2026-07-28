"""Validate source-package registration and gallery settings across Blender versions."""

from __future__ import annotations

import importlib
import os
import sys

import bpy

source_parent = os.environ.get("ANIMTHUMB_SOURCE_PARENT", "")
if not source_parent:
    raise RuntimeError("ANIMTHUMB_SOURCE_PARENT is required")

sys.path.insert(0, source_parent)
package = importlib.import_module("blender_animated_ui")
package.register()

try:
    scale_property = bpy.types.WindowManager.bl_rna.properties[
        "animthumb_thumbnail_scale"
    ]
    if float(scale_property.default) != 1.0:
        raise RuntimeError("Thumbnail scale default is not 1.0")
    if float(scale_property.hard_min) != 0.5:
        raise RuntimeError("Thumbnail scale minimum is not 0.5")
    if float(scale_property.hard_max) != 4.0:
        raise RuntimeError("Thumbnail scale maximum is not 4.0")
    if not hasattr(bpy.types, "ANIMTHUMB_OT_reset_gallery_settings"):
        raise RuntimeError("Gallery settings reset operator did not register")
    if not hasattr(bpy.types, "ANIMTHUMB_OT_rename_item"):
        raise RuntimeError("Gallery rename operator did not register")

    ingest_properties = bpy.ops.animthumb.ingest_media.get_rna_type().properties
    refresh_properties = bpy.ops.animthumb.refresh_item.get_rna_type().properties
    if "display_name" not in ingest_properties:
        raise RuntimeError("Ingest operator is missing Imported Name")
    if "display_name" not in refresh_properties:
        raise RuntimeError("Refresh operator is missing Imported Name")

    wm = bpy.context.window_manager
    scene = bpy.context.scene
    wm.animthumb_gallery_search = "changed"
    wm.animthumb_gallery_media_type = "MP4"
    wm.animthumb_gallery_sort = "NAME_ASC"
    wm.animthumb_thumbnail_scale = 4.0
    wm.animthumb_preview_fps = 60
    wm.animthumb_optimized_playback = True
    scene.animthumb_gallery_page = 2
    reset_result = set(bpy.ops.animthumb.reset_gallery_settings())
    if "FINISHED" not in reset_result:
        raise RuntimeError(f"Gallery reset returned {sorted(reset_result)}")
    if (
        wm.animthumb_gallery_search
        or wm.animthumb_gallery_media_type != "ALL"
        or wm.animthumb_gallery_sort != "DATE_ADDED_DESC"
        or float(wm.animthumb_thumbnail_scale) != 1.0
        or int(wm.animthumb_preview_fps) != 10
        or bool(wm.animthumb_optimized_playback)
        or int(scene.animthumb_gallery_page) != 0
    ):
        raise RuntimeError("Gallery reset did not restore every default")

    print(
        "ANIMTHUMB_REGISTRATION",
        {
            "version": tuple(bpy.app.version),
            "thumbnail_scale": [
                float(scale_property.hard_min),
                float(scale_property.default),
                float(scale_property.hard_max),
            ],
            "gallery_reset": True,
            "rename_operator": True,
            "imported_name_fields": True,
        },
    )
finally:
    package.unregister()
