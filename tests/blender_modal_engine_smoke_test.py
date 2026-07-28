"""Run a real windowed modal preview engine, then exit automatically."""

from __future__ import annotations

import os
import time

import addon_utils
import bpy

MODULE = os.environ.get(
    "ANIMTHUMB_MODULE",
    "bl_ext.user_default.blender_animated_ui",
)
sample_path = os.environ.get("ANIMTHUMB_SAMPLE_MEDIA", "")
second_sample_path = os.environ.get("ANIMTHUMB_SECOND_MEDIA", "")
preview_fps_setting = int(os.environ.get("ANIMTHUMB_PREVIEW_FPS", "60"))
if not sample_path:
    raise RuntimeError("ANIMTHUMB_SAMPLE_MEDIA is required")

addon_utils.enable(MODULE, default_set=True)
bpy.context.window_manager.animthumb_preview_fps = preview_fps_setting
package = __import__(
    MODULE,
    fromlist=["ffmpeg_bridge", "library", "media_ingest", "preview_engine"],
)
ffmpeg = str(package.ffmpeg_bridge.status().get("executable", "") or "")
source_paths = [sample_path]
if second_sample_path:
    source_paths.append(second_sample_path)
result_ids = []
for index, source_path in enumerate(source_paths):
    result = package.media_ingest.ingest_media(
        ffmpeg,
        [source_path],
        display_name=f"Modal Smoke {index + 1}",
        target_fps=60,
    )
    result_ids.append(str(result["item_id"]))
package.library.refresh_scene(bpy.context.scene)
items = tuple(
    item
    for item in bpy.context.scene.animthumb_items
    if str(item.item_id) in result_ids
)
if len(items) < len(source_paths):
    raise RuntimeError("Mixed-rate modal caches were not loaded")
for item in items:
    package.preview_cache.load_item(item)
effective_rates = tuple(float(item.effective_fps) for item in items)
item_ids = tuple(str(item.item_id) for item in items)
if second_sample_path and len({round(rate, 1) for rate in effective_rates}) < 2:
    raise RuntimeError("Mixed-rate modal caches did not retain distinct rates")

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
        item_ids,
    )
    package.preview_engine.schedule_start()

started_at = time.monotonic()
started_tick = int(bpy.context.window_manager.animthumb_preview_tick)


def verify_and_quit() -> None:
    running = bool(package.preview_engine._ENGINE_RUNNING)
    heartbeat = float(package.preview_engine._LAST_HEARTBEAT_MONOTONIC)
    preview_tick = int(bpy.context.window_manager.animthumb_preview_tick)
    preview_tick_delta = (preview_tick - started_tick) % 1_000_000
    preview_fps = package.preview_engine.preview_frame_rate()
    display_rates = tuple(
        package.preview_cache.display_frame_rate(
            item_id,
            fps_limit=preview_fps,
        )
        for item_id in item_ids
    )
    fastest_display_fps = max(display_rates, default=0.0)
    maximum_scheduler_fps = min(
        float(preview_fps),
        sum(display_rates),
    )
    elapsed_seconds = max(0.001, time.monotonic() - started_at)
    maximum_expected_ticks = max(
        4,
        int(maximum_scheduler_fps * elapsed_seconds) + 10,
    )
    loaded_before_tab_switch = {
        item_id: package.preview_cache.loaded_frame_count(item_id)
        for item_id in item_ids
    }
    for target in package.preview_engine._UI_REGION_TARGETS.values():
        target["last_seen"] = (
            time.monotonic() - package.constants.PREVIEW_UI_TARGET_STALE_SECONDS - 1.0
        )
    live_ids_after_tab_switch = package.preview_engine.visible_item_ids()
    warm_ids_after_tab_switch = package.preview_engine.warm_item_ids()
    package.preview_cache.trim_offscreen_items(
        warm_ids_after_tab_switch,
        now_monotonic=(
            time.monotonic() + package.constants.PREVIEW_OFFSCREEN_GRACE_SECONDS + 1.0
        ),
    )
    loaded_after_tab_switch = {
        item_id: package.preview_cache.loaded_frame_count(item_id)
        for item_id in item_ids
    }
    warm_cache_preserved = bool(
        not live_ids_after_tab_switch
        and set(warm_ids_after_tab_switch) == set(item_ids)
        and loaded_after_tab_switch == loaded_before_tab_switch
    )
    print(
        "ANIMTHUMB_MODAL_ENGINE",
        {
            "running": running,
            "heartbeat": heartbeat > 0.0,
            "preview_tick": preview_tick,
            "preview_tick_delta": preview_tick_delta,
            "preview_fps": preview_fps,
            "effective_rates": effective_rates,
            "display_rates": display_rates,
            "fastest_display_fps": fastest_display_fps,
            "maximum_scheduler_fps": maximum_scheduler_fps,
            "elapsed_seconds": elapsed_seconds,
            "maximum_expected_ticks": maximum_expected_ticks,
            "warm_cache_preserved": warm_cache_preserved,
            "warm_loaded_frames": loaded_after_tab_switch,
        },
    )
    if (
        not running
        or heartbeat <= 0.0
        or preview_tick_delta < 3
        or preview_tick_delta > maximum_expected_ticks
        or preview_fps != preview_fps_setting
        or not warm_cache_preserved
    ):
        raise RuntimeError("The real-window modal preview engine did not advance")
    package.preview_engine.stop()
    for item_id in item_ids:
        if not package.library.remove_item(item_id):
            raise RuntimeError("Modal smoke cache cleanup failed")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(verify_and_quit, first_interval=2.0)
