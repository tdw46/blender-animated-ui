"""Run with Blender in an isolated profile and the extension discoverable."""

from __future__ import annotations

import addon_utils
import bpy

MODULE = "bl_ext.user_default.blender_animated_ui"

addon_utils.enable(MODULE, default_set=True)
if not hasattr(bpy.types, "ANIMTHUMB_PT_animated_gallery"):
    raise RuntimeError("Animated gallery panel did not register")
if not hasattr(bpy.types.Scene, "animthumb_items"):
    raise RuntimeError("Animated thumbnail Scene collection did not register")
if not hasattr(bpy.types.WindowManager, "animthumb_optimized_playback"):
    raise RuntimeError("Optimized playback setting did not register")
if not hasattr(bpy.types.WindowManager, "animthumb_preview_fps"):
    raise RuntimeError("Preview frame-rate setting did not register")

scene = bpy.context.scene
scene.animthumb_gallery_page = 0
if bpy.context.window_manager.animthumb_preview_fps != 10:
    raise RuntimeError("Preview frame-rate setting has the wrong default")
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
