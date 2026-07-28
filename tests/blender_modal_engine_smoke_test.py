"""Run a real windowed modal preview engine, then exit automatically."""

from __future__ import annotations

import os

import addon_utils
import bpy

MODULE = "bl_ext.user_default.blender_animated_ui"
sample_path = os.environ.get("ANIMTHUMB_SAMPLE_MEDIA", "")
if not sample_path:
    raise RuntimeError("ANIMTHUMB_SAMPLE_MEDIA is required")

addon_utils.enable(MODULE, default_set=True)
package = __import__(
    MODULE,
    fromlist=["ffmpeg_bridge", "library", "media_ingest", "preview_engine"],
)
ffmpeg = str(package.ffmpeg_bridge.status().get("executable", "") or "")
package.media_ingest.ingest_media(ffmpeg, [sample_path], display_name="Modal Smoke")
package.library.refresh_scene(bpy.context.scene)
item = bpy.context.scene.animthumb_items[0]
package.preview_cache.load_item(item)

window = bpy.context.window_manager.windows[0]
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
region = next(region for region in area.regions if region.type == "UI")
with bpy.context.temp_override(
    window=window,
    screen=window.screen,
    area=area,
    region=region,
    scene=window.scene,
):
    package.preview_engine.register_ui_region(
        bpy.context,
        (str(item.item_id),),
    )
    package.preview_engine.schedule_start()


def verify_and_quit() -> None:
    running = bool(package.preview_engine._ENGINE_RUNNING)
    heartbeat = float(package.preview_engine._LAST_HEARTBEAT_MONOTONIC)
    preview_tick = int(bpy.context.window_manager.animthumb_preview_tick)
    print(
        "ANIMTHUMB_MODAL_ENGINE",
        {
            "running": running,
            "heartbeat": heartbeat > 0.0,
            "preview_tick": preview_tick,
        },
    )
    if not running or heartbeat <= 0.0 or preview_tick <= 0:
        raise RuntimeError("The real-window modal preview engine did not advance")
    package.preview_engine.stop()
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(verify_and_quit, first_interval=1.5)
