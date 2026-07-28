"""RNA property definitions kept separate from runtime engines."""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

from .constants import DEFAULT_PREVIEW_FPS, MAX_PREVIEW_FPS, MIN_PREVIEW_FPS


def _update_gallery_settings(_owner, _context) -> None:
    from . import preview_engine, ui_gallery

    preview_engine.request_fast_reschedule()
    preview_engine.tag_targeted_redraw()
    ui_gallery.tag_layout_refresh()


class ANIMTHUMB_PG_ThumbnailItem(bpy.types.PropertyGroup):
    item_id: StringProperty(name="Item ID", options={"HIDDEN"})
    name: StringProperty(name="Name")
    cache_dir: StringProperty(name="Cache Directory", subtype="DIR_PATH")
    source_path: StringProperty(name="Source", subtype="FILE_PATH")
    frame_count: IntProperty(name="Frame Count", default=0, min=0)
    duration_ms: IntProperty(name="Duration (ms)", default=0, min=0)
    source_fps: FloatProperty(name="Source FPS", default=0.0, min=0.0, precision=3)
    effective_fps: FloatProperty(
        name="Effective FPS",
        default=0.0,
        min=0.0,
        precision=3,
    )
    width: IntProperty(name="Source Width", default=0, min=0)
    height: IntProperty(name="Source Height", default=0, min=0)


def register_properties() -> None:
    bpy.types.Scene.animthumb_items = CollectionProperty(
        type=ANIMTHUMB_PG_ThumbnailItem
    )
    bpy.types.Scene.animthumb_gallery_page = IntProperty(
        name="Gallery Page",
        default=0,
        min=0,
    )
    bpy.types.WindowManager.animthumb_preview_tick = IntProperty(
        name="Animated Preview Tick",
        default=0,
        options={"HIDDEN"},
    )
    bpy.types.WindowManager.animthumb_thumbnail_scale = FloatProperty(
        name="Thumbnail Scale",
        description="Scale thumbnails in the animated preview gallery",
        default=1.0,
        min=0.5,
        max=2.0,
        soft_min=0.75,
        soft_max=1.5,
        step=5,
        precision=2,
        update=_update_gallery_settings,
    )
    bpy.types.WindowManager.animthumb_preview_fps = IntProperty(
        name="Maximum Preview FPS",
        description=(
            "Playback and ingest ceiling from 8 to 60 FPS; genuinely slower "
            "media remains capped by its native frame rate"
        ),
        default=DEFAULT_PREVIEW_FPS,
        min=MIN_PREVIEW_FPS,
        max=MAX_PREVIEW_FPS,
        soft_min=MIN_PREVIEW_FPS,
        soft_max=MAX_PREVIEW_FPS,
        step=1,
        update=_update_gallery_settings,
    )
    bpy.types.WindowManager.animthumb_optimized_playback = BoolProperty(
        name="Optimized Playback Mode",
        description=(
            "Pause animated thumbnails during scene playback, real viewport "
            "interaction, and scrolling inside this gallery"
        ),
        default=False,
        update=_update_gallery_settings,
    )
    bpy.types.WindowManager.animthumb_status = StringProperty(
        name="Animated Thumbnail Status",
        default="",
    )
    bpy.types.WindowManager.animthumb_status_level = StringProperty(
        name="Animated Thumbnail Status Level",
        default="INFO",
        options={"HIDDEN"},
    )


def unregister_properties() -> None:
    property_names = (
        (bpy.types.WindowManager, "animthumb_status_level"),
        (bpy.types.WindowManager, "animthumb_status"),
        (bpy.types.WindowManager, "animthumb_optimized_playback"),
        (bpy.types.WindowManager, "animthumb_preview_fps"),
        (bpy.types.WindowManager, "animthumb_thumbnail_scale"),
        (bpy.types.WindowManager, "animthumb_preview_tick"),
        (bpy.types.Scene, "animthumb_gallery_page"),
        (bpy.types.Scene, "animthumb_items"),
    )
    for owner, name in property_names:
        if hasattr(owner, name):
            delattr(owner, name)
