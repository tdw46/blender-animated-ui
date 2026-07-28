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

scene = bpy.context.scene
scene.animthumb_gallery_page = 0
print(
    "ANIMTHUMB_SMOKE",
    {
        "version": tuple(bpy.app.version),
        "panel": True,
        "scene_properties": True,
        "optimized_mode": True,
    },
)

addon_utils.disable(MODULE)
if hasattr(bpy.types.Scene, "animthumb_items"):
    raise RuntimeError("Animated thumbnail Scene collection did not unregister")
print("ANIMTHUMB_SMOKE_UNREGISTERED", True)
