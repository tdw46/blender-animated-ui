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
if not hasattr(bpy.types.WindowManager, "animthumb_preview_ram_budget_mb"):
    raise RuntimeError("Preview RAM budget setting did not register")
if not hasattr(bpy.types.WindowManager, "animthumb_gallery_search"):
    raise RuntimeError("Gallery search setting did not register")
if not hasattr(bpy.types.WindowManager, "animthumb_gallery_media_type"):
    raise RuntimeError("Gallery media-type setting did not register")
if not hasattr(bpy.types.WindowManager, "animthumb_gallery_sort"):
    raise RuntimeError("Gallery sort setting did not register")
if not hasattr(bpy.types, "ANIMTHUMB_OT_refresh_item"):
    raise RuntimeError("Per-thumbnail refresh operator did not register")
if not hasattr(bpy.types, "ANIMTHUMB_OT_open_item_actions"):
    raise RuntimeError("Per-thumbnail action-menu operator did not register")
if not hasattr(bpy.types, "ANIMTHUMB_OT_open_cache_directory"):
    raise RuntimeError("Cache-directory operator did not register")
if not hasattr(bpy.types, "ANIMTHUMB_OT_rename_item"):
    raise RuntimeError("Per-thumbnail rename operator did not register")
if not hasattr(bpy.types, "ANIMTHUMB_OT_reset_gallery_settings"):
    raise RuntimeError("Gallery settings reset operator did not register")

scene = bpy.context.scene
scene.animthumb_gallery_page = 0
if bpy.context.window_manager.animthumb_preview_fps != 10:
    raise RuntimeError("Preview frame-rate setting has the wrong default")
scale_property = bpy.types.WindowManager.bl_rna.properties["animthumb_thumbnail_scale"]
if float(scale_property.default) != 1.0:
    raise RuntimeError("Thumbnail scale default is not 1.0")
if float(scale_property.hard_min) != 0.5:
    raise RuntimeError("Thumbnail scale minimum does not preserve the old 0.75 size")
if float(scale_property.hard_max) != 4.0:
    raise RuntimeError("Thumbnail scale hard maximum is not 4.0")
if float(scale_property.soft_min) != 0.5:
    raise RuntimeError("Thumbnail scale slider minimum is not 0.5")
if float(scale_property.soft_max) != 4.0:
    raise RuntimeError("Thumbnail scale slider does not reach 4.0")
ingest_properties = bpy.ops.animthumb.ingest_media.get_rna_type().properties
ingest_fps_property = ingest_properties["target_fps"]
if "display_name" not in ingest_properties:
    raise RuntimeError("File-browser import is missing Imported Name")
if int(ingest_fps_property.default) != 22:
    raise RuntimeError("Per-media import FPS does not default to 22")
if bool(ingest_properties["trim_media"].default):
    raise RuntimeError("Trim Media must default to disabled")
refresh_properties = bpy.ops.animthumb.refresh_item.get_rna_type().properties
if "display_name" not in refresh_properties:
    raise RuntimeError("Per-item refresh is missing Imported Name")
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
wm = bpy.context.window_manager
wm.animthumb_gallery_search = "changed"
wm.animthumb_gallery_media_type = "MP4"
wm.animthumb_gallery_sort = "NAME_ASC"
wm.animthumb_thumbnail_scale = 4.0
wm.animthumb_preview_fps = 60
wm.animthumb_preview_ram_budget_mb = 512
wm.animthumb_optimized_playback = True
scene.animthumb_gallery_page = 2
reset_result = set(bpy.ops.animthumb.reset_gallery_settings())
if "FINISHED" not in reset_result:
    raise RuntimeError(f"Gallery reset returned {sorted(reset_result)}")
if wm.animthumb_gallery_search:
    raise RuntimeError("Gallery reset did not clear Search")
if wm.animthumb_gallery_media_type != "ALL":
    raise RuntimeError("Gallery reset did not restore Media Type")
if wm.animthumb_gallery_sort != "DATE_ADDED_DESC":
    raise RuntimeError("Gallery reset did not restore Sort")
if float(wm.animthumb_thumbnail_scale) != 1.0:
    raise RuntimeError("Gallery reset did not restore the 1.0 scale")
if int(wm.animthumb_preview_fps) != 10:
    raise RuntimeError("Gallery reset did not restore the playback FPS")
if int(wm.animthumb_preview_ram_budget_mb) != 32:
    raise RuntimeError("Gallery reset did not restore the preview RAM budget")
if bool(wm.animthumb_optimized_playback):
    raise RuntimeError("Gallery reset did not disable optimized playback")
if int(scene.animthumb_gallery_page) != 0:
    raise RuntimeError("Gallery reset did not return to the first page")
print(
    "ANIMTHUMB_SMOKE",
    {
        "version": tuple(bpy.app.version),
        "panel": True,
        "scene_properties": True,
        "optimized_mode": True,
        "gallery_reset": True,
        "imported_name_fields": True,
        "rename_operator": True,
        "thumbnail_scale_default": float(scale_property.default),
        "thumbnail_scale_min": float(scale_property.soft_min),
        "thumbnail_scale_max": float(scale_property.soft_max),
        "per_media_import_fps_default": int(ingest_fps_property.default),
        "trim_media_default": bool(ingest_properties["trim_media"].default),
        "custom_cache_preference": True,
        "gallery_query": True,
        "preview_fps": int(bpy.context.window_manager.animthumb_preview_fps),
        "preview_fps_max": int(fps_property.hard_max),
        "preview_ram_budget_mb": int(wm.animthumb_preview_ram_budget_mb),
    },
)

addon_utils.disable(MODULE)
if hasattr(bpy.types.Scene, "animthumb_items"):
    raise RuntimeError("Animated thumbnail Scene collection did not unregister")
if hasattr(bpy.types.WindowManager, "animthumb_preview_fps"):
    raise RuntimeError("Preview frame-rate setting did not unregister")
if hasattr(bpy.types.WindowManager, "animthumb_preview_ram_budget_mb"):
    raise RuntimeError("Preview RAM budget setting did not unregister")
print("ANIMTHUMB_SMOKE_UNREGISTERED", True)
