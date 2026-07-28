"""Run with Blender in an isolated profile and the extension discoverable."""

from __future__ import annotations

import os

import addon_utils
import bpy

MODULE = os.environ.get(
    "ANIMTHUMB_MODULE",
    "bl_ext.user_default.blender_animated_ui",
)

addon_utils.enable(MODULE, default_set=True)
if not hasattr(bpy.types, "ANIMTHUMB_PT_animated_gallery"):
    raise RuntimeError("Animated gallery panel did not register")
if not hasattr(bpy.types.Scene, "animthumb_items"):
    raise RuntimeError("Animated thumbnail Scene collection did not register")
if not hasattr(bpy.types.WindowManager, "animthumb_optimized_playback"):
    raise RuntimeError("Optimized playback setting did not register")
if not hasattr(bpy.types.WindowManager, "animthumb_preview_fps"):
    raise RuntimeError("Preview frame-rate setting did not register")
if not hasattr(bpy.types, "ANIMTHUMB_OT_refresh_item"):
    raise RuntimeError("Per-thumbnail refresh operator did not register")
if not hasattr(bpy.types, "ANIMTHUMB_OT_open_item_actions"):
    raise RuntimeError("Per-thumbnail action-menu operator did not register")
if not hasattr(bpy.types, "ANIMTHUMB_OT_open_cache_directory"):
    raise RuntimeError("Cache-directory operator did not register")

scene = bpy.context.scene
scene.animthumb_gallery_page = 0
if bpy.context.window_manager.animthumb_preview_fps != 10:
    raise RuntimeError("Preview frame-rate setting has the wrong default")
scale_property = bpy.types.WindowManager.bl_rna.properties["animthumb_thumbnail_scale"]
if float(scale_property.hard_max) != 2.0:
    raise RuntimeError("Thumbnail scale hard maximum is not 2.0")
if float(scale_property.soft_max) != 2.0:
    raise RuntimeError("Thumbnail scale slider does not reach 2.0")
ingest_properties = bpy.ops.animthumb.ingest_media.get_rna_type().properties
ingest_fps_property = ingest_properties["target_fps"]
if int(ingest_fps_property.default) != 60:
    raise RuntimeError("Per-media import FPS does not default to 60")
if bool(ingest_properties["trim_media"].default):
    raise RuntimeError("Trim Media must default to disabled")
addon_entry = bpy.context.preferences.addons.get(MODULE)
if addon_entry is None:
    raise RuntimeError("Extension preferences entry did not register")
addon_preferences = addon_entry.preferences
if not hasattr(addon_preferences, "thumbnail_cache_directory"):
    raise RuntimeError("Custom thumbnail cache preference is unavailable")
fps_property = bpy.types.WindowManager.bl_rna.properties["animthumb_preview_fps"]
if int(fps_property.hard_min) != 8:
    raise RuntimeError(f"Expected an 8 FPS minimum, got {fps_property.hard_min}")
if int(fps_property.hard_max) != 60:
    raise RuntimeError("Preview frame-rate setting does not allow 60 FPS")
print(
    "ANIMTHUMB_SMOKE",
    {
        "version": tuple(bpy.app.version),
        "panel": True,
        "scene_properties": True,
        "optimized_mode": True,
        "thumbnail_scale_max": float(scale_property.soft_max),
        "per_media_import_fps_default": int(ingest_fps_property.default),
        "trim_media_default": bool(ingest_properties["trim_media"].default),
        "custom_cache_preference": True,
        "preview_fps": int(bpy.context.window_manager.animthumb_preview_fps),
        "preview_fps_max": int(fps_property.hard_max),
    },
)

addon_utils.disable(MODULE)
if hasattr(bpy.types.Scene, "animthumb_items"):
    raise RuntimeError("Animated thumbnail Scene collection did not unregister")
if hasattr(bpy.types.WindowManager, "animthumb_preview_fps"):
    raise RuntimeError("Preview frame-rate setting did not unregister")
print("ANIMTHUMB_SMOKE_UNREGISTERED", True)
